"""Local DFM plans and measured reports. No network or Autodesk imports.

Generated inspection code supplies measurements; this contract does not prove
that code correct or sandbox it. Read-only behavior remains an execution policy.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from .secure_store import SecureStore
from . import machines


GUIDES = {
    'milling': {
        'checks': 'Measure supported holes/pockets. Compare minimum internal corner radius with the chosen cutter radius; compare axial depth with confirmed cutting reach. Read adsk.cam.Tool help for library-derived dimensions and units; a library entry does not establish physical availability, and flute length alone is not safe reach. Inspect installed adsk.cam recognition APIs and extension availability first. A cylindrical face alone is not a complete hole.',
        'unchecked': 'Holder/fixture collision, workholding, chatter, rigidity, full tool approach, and unseen/intersecting features require separate evidence.',
    },
    'turning': {
        'checks': 'Establish turning axis, stock, workholding and actual process stages. Measure diameters, axial lengths, bores and grooves against confirmed machine/tool profiles. Secondary flats and cross-holes may require milling/drilling.',
        'unchecked': 'A rotational shape does not prove chucking, tool access, deflection, stability or a complete setup. No universal slenderness limit.',
    },
    'sheet_metal': {
        'checks': 'Read native thickness and sheet-metal rule, bends and existing flat pattern. Compare supported radii, flange/relief dimensions and hole-to-bend/edge distances with a sourced material/tool profile and explicit distance convention. Respect cutting/forming/machining order.',
        'unchecked': 'Flat pattern creation is a modification. Bend sequence, springback, tooling collision and imported-solid unfolding require additional validation. Optional RMFG supplier analysis uses rmfg_materials and fusion_rmfg, requires connection and explicit UI approval for each exported snapshot; native checks need no supplier connection.',
    },
    'fdm': {
        'checks': 'Establish FDM/FFF printer, material, orientation, nozzle/extrusion settings and supports. Compare dimensions in the proposed build frame with its envelope; measure supported walls/features/clearances against that profile. Overhang checks depend on build direction.',
        'unchecked': 'Geometry alone cannot prove adhesion, strength, bridging, warping, support success or slicer results. Do not infer wall thickness from a bounding box or use universal overhang/clearance limits.',
    },
    'resin': {
        'checks': 'Establish SLA/DLP/MSLA process, resin, machine, orientation and hollow/solid intent. Compare build-frame dimensions and supported features against a supplied profile. Investigate drainage and support needs only with explicit topology/orientation evidence.',
        'unchecked': 'Bounding boxes and appearance cannot prove drainage, absence of suction cups, support coverage, curing or strength. Unsupported cavity analysis stays unknown.',
    },
    'powder': {
        'checks': 'Identify the actual polymer SLS/MJF or metal powder process and supplier/material profile. Compare supported build-frame dimensions and features with that profile. Track post-processing and secondary machining stages.',
        'unchecked': 'Do not transfer polymer assumptions to metal. Powder escape, support needs, thermal distortion, residual stress and strength require separately qualified analysis.',
    },
}


def short(value, label, limit=400):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label} must be nonempty text, at most {limit} characters.')
    return value


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Use a finite numeric measurement, not a Boolean or API object.')
    return value


def guide(process=None):
    common = {
        'experimental': True,
        'workflow': 'Inspect the target and resolve a BRepBody token. Read/set its plan with fusion_dfm_plan; pass stages=[] only when the user asks to forget that part\'s manufacturing plan. Repeated instances share the native part plan. Use fusion_dfm_check for a selected stage. Derive criteria from user requirements or a documented profile, never invent availability or limits. Preserve functional requirements; recheck after relevant edits.',
        'historicalReports': 'Reports are snapshots, not live certifications. Before reusing one, read fusion_dfm_plan for the same document and resolved native body. Its reportBinding.revision and planHash must both match the report, and machineStatus must be current. The hash covers all ordered stages, including material, notes and criteria. Changed/removed plans, edited geometry or unavailable bindings require a new check. A matching binding alone does not validate external machine/tool settings, occurrence placement, build orientation or the correctness/completeness of the prior inspection.',
        'machines': 'Discover definitions with fusion_api_help steve.machines; read steve.machines.<id> and confirm the intended machine before copying its selection into a stage machine field. Each file defines sourced capabilities, scope and unknowns. context[\'dfm\'].machine returns the selected snapshot or None. compare uses machine.<capability> with its declared relation/units; these reserved limits cannot be overridden by stage criteria. Unknown capabilities require separate sourced setup criteria, not guesses. Definitions are hash-bound; changed/missing definitions require review and explicit plan refresh. A machine envelope excludes tooling/supports/fixtures and does not establish manufacturing success.',
        'assemblyFrames': 'Plans and dfm.body describe the native part definition; repeated occurrences share that plan. They do not share placement or automatically share a print orientation. For an explicitly chosen assembly build frame, retain the intended BRepBody proxy, obtain its assemblyContext occurrence in the root context (including nested childOccurrences), copy occurrence.transform2 and invert it. Transform build-direction Vector3D objects by that inverse before passing their components to native envelope/overhang helpers. Use Point3D for axis origins so translation is included; Fusion point coordinates are cm, while rotational_surfaces takes an origin in mm. Do not use the retired occurrence.transform. Record the occurrence, chosen axes and measured revision; changing placement requires a new orientation-dependent assessment. Do not silently measure every occurrence with native XYZ or infer a build orientation from assembly placement.',
        'signatures': [
            "context['dfm'].body: selected native BRepBody (component coordinates; account for assembly/build transforms)",
            "context['dfm'].stage: copied process/material/notes/criteria",
            "context['dfm'].compare(label, actual, criterion, relation, units, evidence=''): relation is <=, >= or ==; units must exactly match the criterion",
            "context['dfm'].unknown(label, reason): explicit missing/unsupported coverage",
            "context['dfm'].not_applicable(label, reason, evidence): a check excluded by verified part/process context; both reason and evidence are required. Missing settings, unsupported geometry, incomplete scans and failed measurements are unknown, never not applicable. This is a stated applicability judgment, not independent certification",
            "context['dfm'].measurements.sheet_bends(offset=0, limit=10): angles and line lengths from this body's existing flat pattern, without creating it. Missing/foreign patterns remain unknown. Page by nextOffset, inspect each item status; lines are not necessarily unique bends. No radius, tooling or pattern-currency certification",
            "context['dfm'].measurements.envelope(x_axis, y_axis): explicit perpendicular directions in native body coordinates; returns oriented dimensions_mm and excluded geometry",
            "context['dfm'].measurements.face_distance(first_index, second_index): native minimum distance_mm and endpoints between two distinct current trimmed faces on this body. Establish feature membership and material-versus-air before interpreting it. If abs(distance_mm - criterion) <= modelingTolerance_mm, report unknown boundary interpretation instead of claiming pass/violation; this is not a manufacturing allowance. Zero can be a shared boundary, not a defect; this is not a whole-part minimum wall/gap, directional clearance or printability check. Missing/failed native results stay unknown",
            "context['dfm'].measurements.cylindrical_walls(offset=0, limit=10): full cylindrical bands with diameter_mm, axial_span_mm, side, faceToken; NOT complete-hole recognition; page by returned nextOffset",
            "context['dfm'].measurements.cylindrical_surfaces(offset=0, limit=10): radius_mm and solid-face internal/external side for analytic cylindrical faces, including partial rounded corners. No trimming or pocket recognition. First establish pocket membership and the applicable tool axis/approach; do not confuse bores with corners or infer a safe strategy from radius equality. Page by nextOffset. Sharp edges and non-cylindrical surfaces are unassessed; no matches does not prove no tight corners",
            "context['dfm'].measurements.rotational_surfaces(axis_origin_mm, axis_direction, offset=0, limit=10): analytic surface and circular-trim compatibility about a chosen turning axis; compatible/nonrotational/unknown per face. Read every page; no lathe/process approval inferred",
            "context['dfm'].measurements.sheet_metal(): native folded-body flag, configured sheet-metal rule thickness/gap/kFactor and existing component flat-pattern presence. Rule settings are NOT a physical thickness measurement; imported solids stay unknown",
            "context['dfm'].measurements.normal_thickness(face_index): ray-measured material thickness at ONE interior face sample, in mm; requires a solid and a confirmed inward material origin/outward exit on the SAME body. Not a global minimum or whole-part wall check; record unsampled/thin-region coverage as unknown",
            "context['dfm'].measurements.enclosed_voids(lump_index=0, offset=0, limit=10): closed native void shells and enclosed volume_mm3 for resin/powder entrapment screening. Inspect every page/lump; absence is NOT proof of drainage, escape-hole sizing, flow, orientation or no suction cups. Do not transfer resin/powder assumptions to FDM or open holes in intentionally sealed parts",
            "context['dfm'].measurements.holes(offset=0, limit=10): native recognized holes/segments or status unknown when API/extension unavailable; honor warnings and segmentsComplete",
            "context['dfm'].measurements.pockets(attack_direction, offset=0, limit=10): native pocket depths for a downward tool direction; may require an extension; no inferred corner radius or tool clearance",
            "context['dfm'].measurements.planar_overhangs(x_axis, y_axis, offset=0, limit=10): downward planar faces of solid bodies; open surfaces return unknown. Check status before using items. Tilt is 0 degrees for a horizontal underside, 90 for a vertical wall. Lowest horizontal faces are potential bed contact, not automatically unsupported; curved surfaces remain unassessed",
        ],
        'limits': 'Read-only Python, at most 24 findings. Query actual state, not desired dimensions. Measurements and criteria are not independently certified. A checked report covers only its listed checks and geometry revision.',
    }
    if process is None:
        return {**common, 'processes': list(GUIDES)}
    if process not in GUIDES:
        raise ValueError('Choose a supported process: ' + ', '.join(GUIDES))
    return {**common, 'process': process, **GUIDES[process]}


def validate_stages(stages):
    if not isinstance(stages, list) or not 1 <= len(stages) <= 8:
        raise ValueError('Provide 1 to 8 ordered manufacturing stages.')
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) - {'process', 'material', 'notes', 'criteria', 'machine'}:
            raise ValueError('Stages contain process, material, notes, criteria and optional machine only.')
        if stage.get('process') not in GUIDES:
            raise ValueError('Choose a supported DFM process.')
        if 'machine' in stage:
            machines.validate_reference(stage['machine'])
        for key in ('material', 'notes'):
            if key in stage:
                short(stage[key], key)
        criteria = stage.get('criteria', {})
        if not isinstance(criteria, dict) or len(criteria) > 24:
            raise ValueError('Use at most 24 named criteria per stage.')
        for key, criterion in criteria.items():
            short(key, 'Criterion key', 80)
            if key.startswith('machine.'):
                raise ValueError('machine.* criteria come from the selected definition; use another key for part/setup requirements.')
            if not isinstance(criterion, dict) or set(criterion) != {'value', 'units', 'source', 'basis'}:
                raise ValueError('Each criterion requires value, units, source and basis.')
            finite(criterion['value'])
            short(criterion['units'], 'Criterion units', 30)
            short(criterion['source'], 'Criterion source', 300)
            if criterion['basis'] not in ('requirement', 'profile', 'guideline', 'assumption'):
                raise ValueError('Criterion basis must be requirement, profile, guideline or assumption.')
    # Enforce a total limit too, so saved context cannot grow without bound.
    if len(json.dumps(stages, allow_nan=False)) > 12000:
        raise ValueError('Narrow this plan to at most 12,000 characters.')
    return copy.deepcopy(stages)


def native(body):
    return getattr(body, 'nativeObject', None) or body


def revision(body):
    try:
        value = body.revisionId
        return value if isinstance(value, str) and value else None
    except (AttributeError, RuntimeError):
        return None


class DfmStore:
    """Saved documents use file identity; unsaved documents stay session-local.

    Resolve tokens back to native bodies, never compare token strings. Local
    records don't travel with shared Fusion files and never contain credentials.
    """
    def __init__(self, home):
        self.path = Path(home) / 'dfm.json'
        self.enabled = False
        self._plans = {}
        self._lock = threading.RLock()
        self._guard = SecureStore(home, 'dfm-plan-write')
        try:
            if self.path.stat().st_size > 2_000_000:
                return
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self.enabled = value.get('enabled') is True
            plans = value.get('plans', {})
            if isinstance(plans, dict):
                for key, entries in list(plans.items())[:128]:
                    if not isinstance(entries, list):
                        continue
                    valid = []
                    for entry in entries[:64]:
                        try:
                            short(entry['token'], 'Part token', 4096)
                            valid.append({'token': entry['token'], 'stages': validate_stages(entry['stages'])})
                        except (ValueError, KeyError, TypeError):
                            continue
                    self._plans[key] = valid
        except (OSError, ValueError, AttributeError):
            pass

    def _refresh(self):
        # Process-local unsaved documents never enter the shared file. Refresh
        # persistent plans under the writer lock, without toggling an active
        # instance's DFM behavior in the middle of its task.
        current = DfmStore(self.path.parent)
        sessions = {key:value for key,value in self._plans.items() if key.startswith('session:')}
        self._plans = {**current._plans, **sessions}
        return current.enabled

    def _file_lock(self):
        return self._guard.locked('Another STEVE instance is saving DFM plans. Retry when that write finishes; no Fusion operation was cancelled.')

    def _write(self, enabled, plans):
        persistent = {key: value for key, value in plans.items() if not key.startswith('session:')}
        encoded = json.dumps({'enabled': enabled, 'plans': persistent}, allow_nan=False)
        if len(encoded.encode('utf-8')) > 2_000_000:
            raise ValueError('DFM local plan storage is full. Remove unused plans before adding more.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('DFM enabled must be true or false.')
        with self._lock, self._file_lock():
            self._refresh()
            self._write(enabled, self._plans)
            self.enabled = enabled

    @staticmethod
    def _key(document_key):
        return document_key if document_key.startswith('session:') else hashlib.sha256(document_key.encode('utf-8')).hexdigest()

    def _entry(self, key, body, design):
        for entry in self._plans.get(key, []):
            try:
                found = design.findEntityByToken(entry['token'])
                if len(found) == 1 and native(found[0]) == native(body):
                    return entry
            except (RuntimeError, AttributeError):
                continue
        return None

    def plan(self, document_key, body, design):
        with self._lock, self._file_lock():
            self._refresh()
            return copy.deepcopy(self._entry(self._key(document_key), body, design))

    def save_plan(self, document_key, body, design, stages):
        stages = validate_stages(stages)
        for stage in stages:
            if 'machine' in stage:
                machines.resolve(stage['machine'], stage['process'])
        body = native(body)
        short(body.entityToken, 'Part token', 4096)
        with self._lock, self._file_lock():
            persistent_enabled = self._refresh()
            key = self._key(document_key)
            old = self._entry(key, body, design)
            plans = copy.deepcopy(self._plans)
            entries = plans.setdefault(key, [])
            if old is not None:
                entries.remove(old)
            if len(entries) >= 64 or len(plans) > 128:
                raise ValueError('DFM plans support up to 64 bodies per document and 128 documents.')
            entries.append({'token': body.entityToken, 'stages': stages})
            self._write(persistent_enabled, plans)
            self._plans = plans

    def clear_plan(self, document_key, body, design):
        """Forget only this native part's plan, preserving other documents/parts."""
        with self._lock, self._file_lock():
            persistent_enabled = self._refresh()
            key = self._key(document_key)
            entry = self._entry(key, native(body), design)
            if entry is None:
                return False
            plans = copy.deepcopy(self._plans)
            plans[key].remove(entry)
            if not plans[key]:
                del plans[key]
            self._write(persistent_enabled, plans)
            self._plans = plans
            return True


def plan_hash(plan):
    """Bind evidence to all ordered stages, independently of rotating entity tokens."""
    if plan is None:
        return None
    return hashlib.sha256(json.dumps(plan['stages'], sort_keys=True).encode('utf-8')).hexdigest()


class DfmChecks:
    def __init__(self, body, stage):
        self.body = native(body)
        self._stage = validate_stages([stage])[0]
        self._criteria = copy.deepcopy(self._stage.get('criteria', {}))
        self._machine = machines.resolve(self._stage['machine'], self._stage['process']) if 'machine' in self._stage else None
        if self._machine:
            for key, entry in self._machine['capabilities'].items():
                self._criteria['machine.' + key] = {'value': entry['value'], 'units': entry['units'],
                    'basis': 'profile', 'source': self._machine['sources'][entry['source']]}
        self._revision = revision(self.body)
        self._findings = []

    @property
    def stage(self):
        """The assessed stage snapshot; editing the returned value cannot change evidence."""
        return copy.deepcopy(self._stage)

    @property
    def machine(self):
        """Immutable-by-copy capability snapshot selected for this check, or None."""
        return copy.deepcopy(self._machine)

    def machine_status(self):
        if self._machine is None:
            return 'current'
        return machines.status(self._stage['machine'])

    def _add(self, value):
        if len(self._findings) >= 24:
            raise ValueError('Return at most 24 DFM findings per call; narrow the scope and continue separately.')
        if len(json.dumps(self._findings + [value], ensure_ascii=False)) > 14000:
            raise ValueError('DFM findings exceeded 14,000 characters; narrow the scope and continue separately.')
        self._findings.append(value)

    def unknown(self, label, reason):
        self._add({'label': short(label, 'Label', 100), 'status': 'unknown',
                   'reason': short(reason, 'Reason')})

    def not_applicable(self, label, reason, evidence):
        self._add({'label': short(label, 'Label', 100), 'status': 'not_applicable',
                   'reason': short(reason, 'Reason'), 'evidence': short(evidence, 'Evidence')})

    def compare(self, label, actual, criterion, relation, units, evidence=''):
        short(label, 'Label', 100)
        finite(actual)
        if relation not in ('<=', '>=', '=='):
            raise ValueError('Use <=, >= or ==; encode a tolerance as explicit upper/lower criteria.')
        if isinstance(criterion, str) and criterion.startswith('machine.') and self._machine:
            capability = self._machine['capabilities'].get(criterion[len('machine.'):])
            if capability and relation != capability['relation']:
                raise ValueError('Use the selected machine capability relation; it cannot be inverted to produce a pass.')
        if evidence:
            short(evidence, 'Evidence', 400)
        limit = self._criteria.get(criterion)
        if limit is None:
            self.unknown(label, 'Missing criterion ' + str(criterion)[:80] + '; query available context or ask for the consequential requirement.')
            return
        if units != limit['units']:
            raise ValueError('Measurement units must match criterion units; convert through Fusion units helpers first.')
        expected = limit['value']
        passed = actual <= expected if relation == '<=' else actual >= expected if relation == '>=' else actual == expected
        # A handful of binary64 rounding steps can accumulate in native geometry
        # and cm-to-mm conversion. This is NOT a shop tolerance or kernel distance
        # tolerance: preserve raw values and disclose any adjusted boundary result.
        numerical = None
        if not passed and (type(actual) is float or type(expected) is float):
            window = 8 * max(math.ulp(actual), math.ulp(expected))
            if abs(actual - expected) <= window:
                passed = True
                numerical = {'method': 'binary64 boundary comparison', 'maxUlps': 8,
                             'absoluteWindow': window, 'units': units,
                             'scope': 'Floating-point rounding only; not a manufacturing tolerance or measurement uncertainty allowance.'}
        result = {'label': label, 'actual': actual, 'criterion': criterion, 'relation': relation,
                  'limit': expected, 'units': units, 'source': limit['source'], 'basis': limit['basis'],
                  'status': 'pass' if passed else 'concern', 'evidence': evidence}
        if isinstance(criterion, str) and criterion.startswith('machine.') and self._machine:
            result['capabilityScope'] = self._machine['capabilities'][criterion[len('machine.'):]]['scope']
        if numerical is not None:
            result['numericalComparison'] = numerical
        if limit['basis'] in ('assumption', 'guideline'):
            result['conditionalResult'] = result['status']
            result['status'] = 'unknown'
            result['reason'] = 'Confirm applicability of this criterion before treating the conditional result as verified.'
        self._add(result)

    def report(self, execution_ok, configuration_status='current'):
        if configuration_status not in ('current', 'stale', 'unknown'):
            raise ValueError('Use current, stale or unknown configuration status.')
        current = revision(self.body)
        stale = bool(self._revision and current != self._revision) or configuration_status == 'stale'
        findings = copy.deepcopy(self._findings)
        verified = bool(execution_ok and self._revision and current == self._revision and configuration_status == 'current')
        if not verified:
            for finding in findings:
                finding['status'] = 'unknown'
                finding['reason'] = ('The manufacturing plan changed or could not be revalidated; read the current plan and recheck.'
                    if configuration_status != 'current' else
                    'Execution or geometry revision was not verified; remeasure before relying on this result.')
        status = ('stale' if stale else 'incomplete' if not verified or not findings else
                  'concerns' if any(f['status'] == 'concern' for f in findings) else
                  'incomplete' if any(f['status'] == 'unknown' for f in findings) else
                  'not_applicable' if all(f['status'] == 'not_applicable' for f in findings) else 'checked')
        return {'status': status, 'process': self._stage['process'], 'body': str(self.body.name)[:200],
                'bodyToken': self.body.entityToken, 'revision': self._revision,
                'configurationHash': hashlib.sha256(json.dumps(self._stage, sort_keys=True).encode('utf-8')).hexdigest(),
                'configurationStatus': configuration_status,
                'findings': findings, 'coverage': 'Only the listed measurements for this body and revision. Generated inspection code is not independently certified.',
                'unchecked': GUIDES[self._stage['process']]['unchecked'],
                'machine': self._stage.get('machine'),
                'machineUnchecked': self._machine['unverified'] if self._machine else []}

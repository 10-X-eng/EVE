"""Opt-in nominal printer-envelope benchmark; no product printer defaults.

run() creates named disposable bodies only in the dedicated test document.
Call measure(design) separately for read-only verification. This does not slice
or print, and the fixture printer choice says nothing about the user's equipment.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


COMPONENT = 'DFM sourced FDM envelope fixture'
MACHINE_PROFILES = {
    'prusa-mk4s': ('fdm', (250, 210, 220)),
    'prusa-core-one': ('fdm', (250, 220, 270)),
    'formlabs-form-4': ('resin', (200, 125, 210)),
    'formlabs-fuse-1-plus-30w': ('powder', (165, 165, 300)),
}
PARTS = (
    ('DFM orientation plate', (218, 200, 10)),
    ('DFM envelope boundary', (250, 20, 10)),
    ('DFM oversized plate', (251, 20, 10)),
)


def context():
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong test document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command'
    design = adsk.fusion.Design.cast(app.activeProduct)
    assert design is not None
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    return app, design


def measure(design):
    app, active = context()
    assert design == active
    protected = [(body, body.revisionId) for comp in design.allComponents for body in comp.bRepBodies]
    component = next(c for c in design.allComponents if c.name == COMPONENT)
    assert component.bRepBodies.count == len(PARTS)
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_sourced_envelope_probe'
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
    results = []
    machines = __import__(package + '.machines', fromlist=['help'])
    with tempfile.TemporaryDirectory(prefix='steve-sourced-envelope-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'sourced-envelope-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        bodies = [(next(b for b in component.bRepBodies if b.name == name), expected) for name, expected in PARTS]
        bodies.append((design.rootComponent.bRepBodies.item(0), (60, 40, 8)))
        for machine_id, (process, expected_nominal) in MACHINE_PROFILES.items():
            selected = machines.help(machine_id)
            nominal = tuple(selected['capabilities']['nominal_build_' + axis]['value'] for axis in 'xyz')
            assert nominal == expected_nominal, 'Review fixture expectations after definition changes'
            for body, expected in bodies:
                name = body.name
                volume = expected[0] * expected[1] * expected[2]
                assert body.isSolid
                if name != 'DFM fixture block':
                    assert body.faces.count == 6 and abs(body.volume*1000 - volume) < .00001
                args = {'document_id': tools.document_id, 'part_token': body.entityToken}
                tools.dfm_plan({**args, 'stages': [{'process': process, 'machine': selected['selection'],
                    'notes': 'Benchmark machine choice; no actual installed machine, material, slicer or print qualification.'}]})
                frames = [('upright', [1,0,0], [0,1,0], expected)]
                if name == PARTS[0][0]:
                    frames.append(('quarter_turn', [0,1,0], [-1,0,0], (expected[1], expected[0], expected[2])))
                if name == PARTS[1][0]:
                    frames.append(('on_edge', [0,1,0], [0,0,1], (expected[1], expected[2], expected[0])))
                for orientation, x, y, dimensions in frames:
                    code = '''def run(context):
        d = context['dfm']
        measured = d.measurements.envelope(X_AXIS, Y_AXIS)
        for axis, actual in zip(('machine.nominal_build_x', 'machine.nominal_build_y', 'machine.nominal_build_z'), measured['dimensions_mm']):
            d.compare(axis, actual, axis, '<=', 'mm', 'Selected nominal printer envelope in explicit native build frame; part only')
        d.unknown('Print outcome', 'Nominal box only. No usable-boundary, material compensation, slicer, support, placement, adhesion or strength qualification')
        return measured
    '''.replace('X_AXIS', repr(x)).replace('Y_AXIS', repr(y))
                    checked = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**args, 'stage': 0,
                        'title': 'Compare sourced nominal envelope', 'code': code}, 'cancelled': lambda: False})
                    assert checked['ok'], checked
                    actual = checked['result']['dimensions_mm']
                    assert all(abs(a-b) < 1e-6 for a,b in zip(actual, dimensions)), (name, orientation, actual)
                    expected_statuses = ['pass' if a <= b else 'concern' for a,b in zip(dimensions, nominal)] + ['unknown']
                    statuses = [f['status'] for f in checked['dfm']['findings']]
                    assert statuses == expected_statuses, (name, orientation, statuses)
                    assert checked['dfm']['status'] == ('concerns' if 'concern' in statuses else 'incomplete')
                    results.append({'machine': selected['selection'], 'process': process, 'body': name, 'orientation': orientation, 'dimensions_mm': actual,
                                    'volume_mm3': body.volume*1000, 'statuses': statuses,
                                    'reportStatus': checked['dfm']['status']})
    assert all(b.isValid and b.revisionId == rev for b,rev in protected), 'Inspection changed geometry'
    return {'fusionVersion': app.version, 'cases': results, 'allBodiesUnchanged': True}


def run(_context):
    app, design = context()
    assert not any(c.name == COMPONENT for c in design.allComponents), 'Fixture exists; inspect instead of recreating'
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    comp = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    comp.name = COMPONENT
    for name, (x, y, z) in PARTS:
        sketch = comp.sketches.add(comp.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(x/10,y/10,0))
        feature = comp.features.extrudeFeatures.addSimple(sketch.profiles.item(0),
            adsk.core.ValueInput.createByString(f'{z} mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        body = feature.bodies.item(0)
        body.name = name
        assert abs(body.volume*1000 - x*y*z) < .00001
        sketch.isVisible = False
    assert all(b.isValid and b.revisionId == rev for b,rev in protected), 'Pre-existing geometry changed'
    print(json.dumps({'created': COMPONENT, 'bodies': [name for name,_ in PARTS],
                      'preExistingBodiesUnchanged': True, 'next': 'Call measure(design) read-only after creation commits.'}))


if __name__ == '__main__':
    run(None)

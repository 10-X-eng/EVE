"""Read-only build-frame validation against the existing disposable block fixture."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


def run(_context):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong test document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command'
    design = adsk.fusion.Design.cast(app.activeProduct)
    assert design.rootComponent.bRepBodies.count == 1
    body = design.rootComponent.bRepBodies.item(0)
    assert body.name == 'DFM fixture block'
    assert body.isSolid
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_build_orientation_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
    geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
    # Analytic expectations for this block and its bottom-opening blind hole.
    # At 30 degrees about X, the bottom and hole ceiling slope 30 degrees,
    # and the positive-Y side slopes 60 degrees. Neither is horizontal.
    angle = math.pi / 6
    cases = [
        ('upright', [1, 0, 0], [0, 1, 0], [0, 0], 1),
        ('upside_down', [1, 0, 0], [0, -1, 0], [0], 1),
        ('sideways', [0, 1, 0], [0, 0, 1], [0], 1),
        ('tilted_30', [1, 0, 0], [0, math.cos(angle), math.sin(angle)], [30, 30, 60], 0),
    ]
    reports = []
    for name, x, y, expected, beds in cases:
        offset, items, unsupported, pages = 0, [], [], 0
        while offset is not None:
            result = geometry.planar_overhangs(x, y, offset=offset, limit=1)
            items.extend(result['items'])
            unsupported.extend(result['unsupported'])
            offset = result['nextOffset']
            pages += 1
            assert pages <= body.faces.count + 1
        slopes = sorted(face['tilt_from_build_plane_deg'] for face in items)
        assert len(slopes) == len(expected), (name, slopes)
        assert all(abs(a - b) < 1e-6 for a, b in zip(slopes, expected)), (name, slopes)
        assert sum(face['lowestHorizontalFace'] for face in items) == beds, name
        assert len(unsupported) == 1, (name, unsupported)
        reports.append({'orientation': name, 'slopes_deg': slopes, 'bedCandidates': beds,
                        'unsupportedCurves': len(unsupported), 'pages': pages})
    # Exercise supplied profile comparisons at both sides of the 30-degree boundary.
    # These are synthetic test criteria, not printer capability recommendations.
    with tempfile.TemporaryDirectory(prefix='steve-build-orientation-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'build-orientation-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        args = {'document_id': tools.document_id, 'part_token': body.entityToken}
        comparisons = []
        for minimum in (29, 30, 31):
            tools.dfm_plan({**args, 'stages': [{'process': 'fdm', 'criteria': {
                'minimum_slope': {'value': minimum, 'units': 'deg', 'basis': 'profile',
                                 'source': 'Synthetic fixture profile; tilt from build plane, not vertical'}}}]})
            code = '''def run(context):
    d = context['dfm']
    offset = 0
    while offset is not None:
        measured = d.measurements.planar_overhangs(X_AXIS, Y_AXIS, offset=offset, limit=1)
        for face in measured['items']:
            d.compare('Downward face ' + str(face['faceIndex']), face['tilt_from_build_plane_deg'],
                'minimum_slope', '>=', 'deg', 'Native planar face normal in explicit tilted build frame')
        for face in measured['unsupported']:
            d.unknown('Unsupported face ' + str(face['faceIndex']), face['reason'])
        offset = measured['nextOffset']
    d.unknown('Printing outcome', 'No slicer, supports, bridging, strength or adhesion validation')
'''.replace('X_AXIS', repr(cases[-1][1])).replace('Y_AXIS', repr(cases[-1][2]))
            checked = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**args,
                'stage': 0, 'title': 'Check tilted build slopes', 'code': code}, 'cancelled': lambda: False})
            assert checked['ok'], checked
            statuses = [f['status'] for f in checked['dfm']['findings']]
            assert statuses.count('pass') == (3 if minimum <= 30 else 1), statuses
            assert statuses.count('concern') == (0 if minimum <= 30 else 2), statuses
            assert statuses.count('unknown') == 2, statuses
            comparisons.append({'minimumSlope_deg': minimum, 'findings': statuses,
                                'overall': checked['dfm']['status']})
    assert all(b.isValid and b.revisionId == old for b, old in protected), 'Existing geometry changed'
    print(json.dumps({'fusionVersion': app.version, 'orientations': reports,
                      'profileComparisons': comparisons, 'allBodiesUnchanged': True}))


if __name__ == '__main__':
    run(None)

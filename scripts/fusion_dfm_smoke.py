"""Run inside Fusion against the explicitly named, disposable DFM fixture.

This is a developer check, not an add-in entry point. It imports STEVE under an
isolated package name so a running add-in is not reloaded. No network, document
save, or modification occurs. Create the 60 x 40 x 8 mm test block with a
4 mm diameter, 5 mm deep blind hole opening on its bottom face separately.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


def run(_context):
    app = adsk.core.Application.get()
    if app.activeDocument.name != 'STEVE DFM development tests':
        raise RuntimeError('Activate only the disposable STEVE DFM development tests document.')
    design = adsk.fusion.Design.cast(app.activeProduct)
    bodies = design.rootComponent.bRepBodies
    if bodies.count != 1 or bodies.item(0).name != 'DFM fixture block':
        raise RuntimeError('Expected one named DFM fixture body; no work was performed.')
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_dfm_development_probe'
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
    body = bodies.item(0)
    before = body.revisionId
    with tempfile.TemporaryDirectory(prefix='steve-dfm-probe-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'isolated-dfm-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        arguments = {'document_id': tools.document_id, 'part_token': body.entityToken}
        tools.dfm_plan({**arguments, 'stages': [{'process': 'milling', 'criteria': {
            'required_length': {'value': 65, 'units': 'mm', 'source': 'Deliberate fixture requirement', 'basis': 'requirement'},
            'envelope_length': {'value': 70, 'units': 'mm', 'source': 'Fixture machine envelope', 'basis': 'profile'}}}]})
        result = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**arguments,
            'stage': 0, 'title': 'Check real fixture dimensions', 'code': """def run(context):
    dfm = context['dfm']
    box = dfm.body.boundingBox
    length = 10 * (box.maxPoint.x - box.minPoint.x)
    dfm.compare('Required length', length, 'required_length', '>=', 'mm', 'Native body boundingBox X span, cm converted to mm')
    dfm.compare('Machine envelope length', length, 'envelope_length', '<=', 'mm', 'Native body boundingBox X span')
    dfm.unknown('Tool access', 'No tool or approach direction has been selected')
    return {'length_mm': length}
"""}, 'cancelled': lambda: False})
        assert result['ok'], result
        assert result['result']['length_mm'] == 60, result
        assert [f['status'] for f in result['dfm']['findings']] == ['concern', 'pass', 'unknown'], result
        assert before == body.revisionId, 'Read-only DFM changed the body'
        geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
        walls = geometry.cylindrical_walls()
        assert len(walls['items']) == 1, walls
        assert abs(walls['items'][0]['diameter_mm'] - 4) < 1e-6, walls
        assert abs(walls['items'][0]['axial_span_mm'] - 5) < 1e-6, walls
        assert walls['items'][0]['side'] == 'internal', walls
        envelope = geometry.envelope([1,0,0], [0,1,0])
        assert all(abs(a-b) < 1e-6 for a,b in zip(envelope['dimensions_mm'], [60,40,8])), envelope
        rotated = geometry.envelope([0,1,0], [1,0,0])
        assert all(abs(a-b) < 1e-6 for a,b in zip(rotated['dimensions_mm'], [40,60,8])), rotated
        overhangs = geometry.planar_overhangs([1,0,0], [0,1,0])
        assert len(overhangs['items']) == 2, overhangs
        assert sorted(v['lowestHorizontalFace'] for v in overhangs['items']) == [False, True], overhangs
        plan = tools.dfm_plan(arguments)['plan']['stages']
        plan.append({'process': 'fdm', 'criteria': {key: {'value': size, 'units': 'mm',
            'source': 'Explicit fixture printer envelope', 'basis': 'profile'}
            for key, size in zip(('build_x','build_y','build_z'), (62,45,10))}})
        tools.dfm_plan({**arguments, 'stages': plan})
        orientation_results = []
        for x, y in (([0,1,0], [1,0,0]), ([1,0,0], [0,1,0])):
            code = """def run(context):
    dfm = context['dfm']
    measurement = dfm.measurements.envelope(X_AXIS, Y_AXIS)
    for key, value in zip(('build_x', 'build_y', 'build_z'), measurement['dimensions_mm']):
        dfm.compare(key, value, key, '<=', 'mm', 'Native oriented envelope for the explicitly proposed build frame')
    return measurement
""".replace('X_AXIS', repr(x)).replace('Y_AXIS', repr(y))
            outcome = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**arguments,
                'stage': 1, 'title': 'Check printer envelope', 'code': code}, 'cancelled': lambda: False})
            assert outcome['ok'], outcome
            orientation_results.append(outcome['dfm']['status'])
        assert orientation_results == ['concerns', 'checked'], orientation_results
        floor = next(face for face in overhangs['items'] if not face['lowestHorizontalFace'])
        thickness = geometry.normal_thickness(floor['faceIndex'])
        assert thickness['status'] == 'measured' and abs(thickness['thickness_mm'] - 3) < 1e-6, thickness
        assert before == body.revisionId, 'Measurements changed the body'
        print(json.dumps({'fusionVersion': app.version, 'unchanged': True,
                          'test': 'Actual STEVE run_script and DFM plan on real Fusion geometry',
                          'walls': walls, 'envelope': envelope, 'rotatedEnvelope': rotated,
                          'planarOverhangs': overhangs, 'printerOrientationResults': orientation_results,
                          'blindHoleFloorThickness': thickness,
                          'holes': geometry.holes(), 'result': result}, ensure_ascii=False))


if __name__ == '__main__':
    run(None)

"""Disposable slot fixtures for native trimmed-face distances, not print qualification.

run() creates three guarded U sections; measure(component) only inspects existing
fixtures and uses temporary local DFM plans. All limits are synthetic test values.
"""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


NAME = 'DFM face distance fixtures'
GAPS = (.2, .4, .8)


def measure(component):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests'
    assert component.name == NAME and component.bRepBodies.count == len(GAPS)
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_face_distance_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['DfmGeometry'])
    revisions = [(b, b.revisionId) for b in component.bRepBodies]
    samples = []
    with tempfile.TemporaryDirectory(prefix='steve-face-distance-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'face-distance-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        for index, gap in enumerate(GAPS):
            body = component.bRepBodies.item(index)
            assert body.name == f'DFM slot {gap:g} mm' and body.isSolid
            assert abs(body.volume*1000 - (200+10*gap)) < 1e-6
            x0 = 20*index
            def face_at(axis, coordinate, area):
                matches = [i for i, f in enumerate(body.faces)
                           if adsk.core.Plane.cast(f.geometry) is not None
                           and abs(getattr(f.pointOnFace, axis)*10-coordinate) < 1e-6
                           and abs(f.area*100-area) < 1e-6]
                assert len(matches) == 1, matches
                return matches[0]
            first = face_at('x', x0+2, 40)
            second = face_at('x', x0+2+gap, 40)
            floor = face_at('y', 2, gap*5)
            outside = face_at('x', x0, 50)
            ends = [i for i, f in enumerate(body.faces)
                    if abs(f.pointOnFace.y*10-10) < 1e-6 and abs(f.area*100-10) < 1e-6]
            assert len(ends) == 2
            geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
            readings = []
            for label, pair, expected in [('slot', (first, second), gap),
                                          ('coplanar trimmed ends', ends, gap),
                                          ('shared edge', (first, floor), 0),
                                          ('material separation', (outside, first), 2)]:
                result = geometry.face_distance(*pair)
                assert result['status'] == 'measured' and abs(result['distance_mm']-expected) < 1e-6, result
                assert abs(math.dist(*result['closestPoints_mm'])-expected) < 1e-6
                for point in result['closestPoints_mm']:
                    assert x0-1e-6 <= point[0] <= x0+4+gap+1e-6, point
                    assert -1e-6 <= point[1] <= 10+1e-6 and -1e-6 <= point[2] <= 5+1e-6, point
                if label == 'slot':
                    measured_x = sorted(point[0] for point in result['closestPoints_mm'])
                    assert all(abs(actual-wanted) < 1e-6 for actual,wanted in zip(measured_x,(x0+2,x0+2+gap)))
                elif label == 'coplanar trimmed ends':
                    assert all(abs(point[1]-10) < 1e-6 for point in result['closestPoints_mm'])
                readings.append({'kind': label, 'expected_mm': expected, **result})
            # These points independently establish air/material for this analytic
            # fixture only. One midpoint is not a general gap-classification algorithm.
            air = adsk.core.Point3D.create((x0+2+gap/2)/10, .6, .25)
            solid = adsk.core.Point3D.create((x0+1)/10, .6, .25)
            assert body.pointContainment(air) == adsk.fusion.PointContainment.PointOutsidePointContainment
            assert body.pointContainment(solid) == adsk.fusion.PointContainment.PointInsidePointContainment
            profiles = []
            arguments = {'document_id': tools.document_id, 'part_token': body.entityToken}
            for process in ('fdm', 'resin', 'powder'):
                tools.dfm_plan({**arguments, 'stages': [{'process': process, 'criteria': {
                    'gap': {'value': .4, 'units': 'mm', 'source': 'Synthetic slot test only; not a manufacturing recommendation', 'basis': 'profile'}}}]})
                code = '''def run(context):
    dfm = context['dfm']
    result = dfm.measurements.face_distance(FIRST, SECOND)
    if result['status'] == 'measured':
        limit = dfm.stage['criteria']['gap']['value']
        if abs(result['distance_mm']-limit) <= result['modelingTolerance_mm']:
            dfm.unknown('Known fixture slot boundary', 'Measured '+str(result['distance_mm'])+' mm lies within Fusion modeling tolerance of '+str(limit)+' mm; no manufacturing allowance or violation inferred')
        else:
            dfm.compare('Known fixture slot', result['distance_mm'], 'gap', '>=', 'mm', 'Analytic U-section slot; independent topology and fixture point containment establish air')
    else:
        dfm.unknown('Known fixture slot', result['reason'])
    dfm.unknown('Manufacturing qualification', 'Actual machine/material/settings, directional or assembly clearances, unsampled features, drainage and process outcome are unassessed')
    return result
'''.replace('FIRST', str(first)).replace('SECOND', str(second))
                report = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**arguments, 'stage': 0,
                    'title': 'Check known slot against synthetic profile', 'code': code}, 'cancelled': lambda: False})
                assert report['ok'], report
                statuses = [f['status'] for f in report['dfm']['findings']]
                assert statuses == [('concern' if gap < .4 else 'unknown' if gap == .4 else 'pass'), 'unknown'], report
                assert report['dfm']['status'] != 'checked'
                profiles.append({'process': process, 'statuses': statuses})
            samples.append({'gap_mm': gap, 'volume_mm3': body.volume*1000, 'measurements': readings, 'syntheticProfiles': profiles})
    assert all(b.isValid and b.revisionId == rev for b, rev in revisions), 'Inspection changed a body'
    return {'fusionVersion': app.version, 'samples': samples, 'inspectionUnchanged': True}


def run(_context):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests'
    assert app.userInterface.activeCommand == 'SelectCommand'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    assert not any(c.name == NAME for c in design.allComponents), 'Fixture exists; inspect before retrying'
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = NAME
    for index, gap in enumerate(GAPS):
        sketch = component.sketches.add(component.xYConstructionPlane)
        width, x0 = 4+gap, 20*index
        profile = [(0,0), (width,0), (width,10), (2+gap,10), (2+gap,2), (2,2), (2,10), (0,10)]
        points = [adsk.core.Point3D.create((x0+x)/10, y/10, 0) for x, y in profile]
        for start, end in zip(points, points[1:]+points[:1]):
            sketch.sketchCurves.sketchLines.addByTwoPoints(start, end)
        assert sketch.profiles.count == 1
        feature = component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),
            adsk.core.ValueInput.createByString('5 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        sketch.isVisible = False
        assert feature.bodies.count == 1
        feature.bodies.item(0).name = f'DFM slot {gap:g} mm'
    assert all(b.isValid and b.revisionId == rev for b, rev in protected), 'Pre-existing body changed'
    print(json.dumps({'created': NAME, 'bodyCount': component.bRepBodies.count,
                      'preExistingBodiesUnchanged': True,
                      'next': 'Call measure(component) in a separate read-only invocation after creation completes.'}))


if __name__ == '__main__':
    run(None)

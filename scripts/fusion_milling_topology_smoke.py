"""Counterbore, intersecting-hole and sharp open-pocket acceptance fixtures.

run() creates only explicitly named disposable components. Call measure(design)
separately after creation to inspect existing geometry without changing it.
"""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


NAMES = ('DFM counterbore fixture', 'DFM intersecting bores fixture', 'DFM open pocket fixture')
VOLUMES = (4800-84*math.pi, 1000-80*math.pi+128/3, 3500)


def context():
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests'
    design = adsk.fusion.Design.cast(app.activeProduct)
    assert design is not None
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    return app, design


def measure(design):
    app, active = context()
    assert design == active
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_milling_topology_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['DfmGeometry'])
    results = []
    for index, name in enumerate(NAMES):
        component = next(c for c in design.allComponents if c.name == name)
        assert component.bRepBodies.count == 1
        body = component.bRepBodies.item(0)
        assert body.isSolid and abs(body.volume*1000-VOLUMES[index]) < 1e-5
        geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
        bands, unsupported, offset, pages = [], [], 0, 0
        while True:
            page = geometry.cylindrical_walls(offset=offset, limit=1)
            bands.extend(page['items'])
            unsupported.extend(page['unsupported'])
            pages += 1
            if page['nextOffset'] is None:
                break
            assert page['nextOffset'] > offset
            offset = page['nextOffset']
        surfaces = geometry.cylindrical_surfaces(limit=20)
        assert surfaces['nextOffset'] is None
        if index == 0:
            assert not unsupported and len(bands) == 2, (bands, unsupported)
            measured = sorted((round(b['diameter_mm'],6), round(b['axial_span_mm'],6), b['side']) for b in bands)
            assert measured == [(4,9,'internal'), (8,3,'internal')], measured
            # The narrow band's 9 mm is not the complete 12 mm through-hole path.
            assert len(surfaces['items']) == 2
            recognition = geometry.holes(limit=1)
        elif index == 1:
            assert not bands and unsupported, (bands, unsupported)
            assert surfaces['items'] and all(s['side']=='internal' and abs(s['radius_mm']-2)<1e-6 for s in surfaces['items'])
            recognition = {'status': 'not_requested', 'reason': 'Analytic surface radius is not complete intersecting-hole recognition.'}
        else:
            assert not bands and not unsupported and not surfaces['items']
            assert all(adsk.core.Plane.cast(f.geometry) is not None for f in body.faces)
            # Independently identify the open side, floor and two sharp vertical
            # pocket edges. No cylinder matches must not turn into a radius pass.
            corners = []
            for edge in body.edges:
                a, b = edge.startVertex.geometry, edge.endVertex.geometry
                if (abs(a.x-1)<1e-7 and abs(b.x-1)<1e-7 and abs(a.y-b.y)<1e-7
                    and any(abs(a.y-y)<1e-7 for y in (.5,1.5))
                    and sorted(round(p.z,7) for p in (a,b)) == [.5,1]):
                    corners.append(edge)
            assert len(corners) == 2
            assert body.pointContainment(adsk.core.Point3D.create(.1,1,.75)) == adsk.fusion.PointContainment.PointOutsidePointContainment
            assert body.pointContainment(adsk.core.Point3D.create(1.1,1,.75)) == adsk.fusion.PointContainment.PointInsidePointContainment
            recognition = geometry.pockets([0,0,-1], limit=1)
        with tempfile.TemporaryDirectory(prefix='steve-milling-topology-') as folder:
            tools = bridge.FusionTools.__new__(bridge.FusionTools)
            tools.app, tools.task, tools.debug = app, None, None
            tools.document, tools.document_id, tools.closed = app.activeDocument, 'milling-topology-probe', False
            tools.dfm = bridge.DfmStore(folder)
            tools.dfm.set_enabled(True)
            arguments = {'document_id': tools.document_id, 'part_token': body.entityToken}
            tools.dfm_plan({**arguments, 'stages': [{'process': 'milling', 'criteria': {}}]})
            code = '''def run(context):
    dfm = context['dfm']
    result = dfm.measurements.cylindrical_surfaces()
    dfm.unknown('Complete machining coverage', 'Cylinder radii/bands alone do not establish complete holes, sharp-corner cutter fit, tool reach, holder clearance or workholding')
    return {'cylindricalFaceCount': len(result['items']), 'nextOffset': result['nextOffset']}
'''
            report = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**arguments, 'stage': 0,
                'title': 'Preserve incomplete milling coverage', 'code': code}, 'cancelled': lambda: False})
            assert report['ok'] and report['dfm']['status'] == 'incomplete', report
            assert report['dfm']['findings'][0]['status'] == 'unknown'
            empty_report = None
            if index == 2:
                empty_code = '''def run(context):
    result = context['dfm'].measurements.cylindrical_surfaces()
    assert not result['items'] and result['nextOffset'] is None
    return {'cylindricalFaceCount': 0}
'''
                empty_report = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**arguments, 'stage': 0,
                    'title': 'No curved corners does not establish cutter fit', 'code': empty_code}, 'cancelled': lambda: False})
                assert empty_report['ok'] and empty_report['dfm']['status'] == 'incomplete', empty_report
                assert not empty_report['dfm']['findings']
        results.append({'fixture': name, 'expectedVolume_mm3': VOLUMES[index], 'volume_mm3': body.volume*1000,
                        'fullBands': bands, 'unsupportedBands': unsupported, 'bandPages': pages,
                        'cylindricalFaceCount': len(surfaces['items']), 'nativeRecognition': recognition,
                        'reportStatus': report['dfm']['status'],
                        'emptyCandidateReportStatus': empty_report['dfm']['status'] if empty_report else None})
    assert all(b.isValid and b.revisionId == rev for b, rev in protected), 'Inspection changed geometry'
    return {'fusionVersion': app.version, 'fixtures': results, 'allBodiesUnchanged': True}


def run(_context):
    app, design = context()
    assert app.userInterface.activeCommand == 'SelectCommand'
    assert not any(c.name in NAMES for c in design.allComponents), 'Fixture exists; inspect before retrying'
    protected = [(b,b.revisionId) for c in design.allComponents for b in c.bRepBodies]

    def plane_at(component, z):
        request = component.constructionPlanes.createInput()
        assert request.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByString(f'{z} mm'))
        return component.constructionPlanes.add(request)

    def cut(component, sketch, length, direction=adsk.fusion.ExtentDirections.PositiveExtentDirection):
        assert sketch.profiles.count == 1 and component.bRepBodies.count == 1
        request = component.features.extrudeFeatures.createInput(sketch.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
        assert request.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString(f'{length} mm')), direction)
        request.participantBodies = [component.bRepBodies.item(0)]
        feature = component.features.extrudeFeatures.add(request)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        sketch.isVisible = False

    for index, (name, dimensions) in enumerate(zip(NAMES, ((20,20,12),(10,10,10),(20,20,10)))):
        comp = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        comp.name = name
        sketch = comp.sketches.add(comp.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(dimensions[0]/10,dimensions[1]/10,0))
        feature = comp.features.extrudeFeatures.addSimple(sketch.profiles.item(0), adsk.core.ValueInput.createByString(f'{dimensions[2]} mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        sketch.isVisible = False
        if index in (0,1):
            center = 1 if index == 0 else .5
            hole = comp.sketches.add(comp.xYConstructionPlane)
            hole.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(center,center,0), .2)
            cut(comp, hole, dimensions[2])
            if index == 0:
                bore = comp.sketches.add(plane_at(comp, 9))
                bore.sketchCurves.sketchCircles.addByCenterRadius(bore.modelToSketchSpace(adsk.core.Point3D.create(1,1,.9)), .4)
                cut(comp, bore, 3)
            else:
                cross = comp.sketches.add(comp.yZConstructionPlane)
                cross.sketchCurves.sketchCircles.addByCenterRadius(cross.modelToSketchSpace(adsk.core.Point3D.create(0,.5,.5)), .2)
                origin = cross.sketchToModelSpace(adsk.core.Point3D.create(0,0,0))
                normal = cross.sketchToModelSpace(adsk.core.Point3D.create(0,0,1))
                assert abs(abs(normal.x-origin.x)-1)<1e-7
                direction = adsk.fusion.ExtentDirections.PositiveExtentDirection if normal.x>origin.x else adsk.fusion.ExtentDirections.NegativeExtentDirection
                cut(comp, cross, 10, direction)
        else:
            pocket = comp.sketches.add(plane_at(comp, 5))
            a = pocket.modelToSketchSpace(adsk.core.Point3D.create(-.2,.5,.5))
            b = pocket.modelToSketchSpace(adsk.core.Point3D.create(1,1.5,.5))
            pocket.sketchCurves.sketchLines.addTwoPointRectangle(a,b)
            cut(comp, pocket, 5)
        assert comp.bRepBodies.count == 1
        body = comp.bRepBodies.item(0)
        body.name = name.removeprefix('DFM ')
        assert abs(body.volume*1000-VOLUMES[index]) < 1e-5
    assert all(b.isValid and b.revisionId == rev for b,rev in protected), 'Pre-existing geometry changed'
    print(json.dumps({'created': list(NAMES), 'preExistingBodiesUnchanged': True,
                      'next': 'Run measure(design) read-only after creation completes.'}))


if __name__ == '__main__':
    run(None)

"""Opt-in multiple-cavity topology fixture; no drainage or powder-flow claim.

run() creates three disposable bodies in the dedicated development document.
Call measure() separately after setup commits; it changes no geometry or UI state.
The zero-sealed-void criterion is a fixture requirement, not a process default.
"""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


CASES = (
    ('DFM two sealed cavities', 0),
    ('DFM one cavity with two openings', 1),
    ('DFM two cavities with four openings', 2),
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


def expected_volume(opened):
    # Two radius-2, height-4 voids; each vented cavity adds two radius-1,
    # height-3 passages through the bottom/top walls. Dimensions are mm.
    return 20 * 20 * 10 - 2 * math.pi * 2**2 * 4 - opened * 2 * math.pi * 3


def run(_context):
    app, design = context()
    names = {name for name, _ in CASES}
    assert not any(c.name in names for c in design.allComponents), 'Fixtures exist; inspect instead of recreating'
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    for name, opened in CASES:
        component = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        component.name = name
        sketch = component.sketches.add(component.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(2,2,0))
        component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),
            adsk.core.ValueInput.createByString('10 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        sketch.isVisible = False

        def cut(x_mm, z_mm, radius_mm, depth_mm):
            plane_input = component.constructionPlanes.createInput()
            plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByString(f'{z_mm} mm'))
            plane = component.constructionPlanes.add(plane_input)
            sketch = component.sketches.add(plane)
            center = sketch.modelToSketchSpace(adsk.core.Point3D.create(x_mm/10, 1, z_mm/10))
            sketch.sketchCurves.sketchCircles.addByCenterRadius(center, radius_mm/10)
            settings = component.features.extrudeFeatures.createInput(sketch.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
            settings.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString(f'{depth_mm} mm')),
                                     adsk.fusion.ExtentDirections.PositiveExtentDirection)
            settings.participantBodies = [component.bRepBodies.item(0)]
            feature = component.features.extrudeFeatures.add(settings)
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, feature.errorOrWarningMessage
            sketch.isVisible = False

        for x in (5, 15):
            cut(x, 3, 2, 4)
        for x in (5, 15)[:opened]:
            cut(x, 0, 1, 3)
            cut(x, 7, 1, 3)
        assert component.bRepBodies.count == 1
        body = component.bRepBodies.item(0)
        body.name = name
        assert body.isSolid and abs(body.volume*1000 - expected_volume(opened)) < 1e-5
    assert all(b.isValid and b.revisionId == rev for b,rev in protected)
    print(json.dumps({'created': list(names), 'preExistingBodiesUnchanged': True, 'next': 'Call measure() read-only after creation commits.'}))


def measure():
    app, design = context()
    protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    package = 'steve_multiple_cavity_probe'
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    results = []
    try:
        bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
        with tempfile.TemporaryDirectory(prefix='steve-multiple-cavity-') as folder:
            tools = bridge.FusionTools.__new__(bridge.FusionTools)
            tools.app, tools.task, tools.debug = app, None, None
            tools.document, tools.document_id, tools.closed = app.activeDocument, 'multiple-cavity-probe', False
            tools.dfm = bridge.DfmStore(folder)
            tools.dfm.set_enabled(True)
            for name, opened in CASES:
                component = next(c for c in design.allComponents if c.name == name)
                assert component.bRepBodies.count == 1
                body = component.bRepBodies.item(0)
                assert body.isSolid and body.lumps.count == 1
                box = body.boundingBox
                dimensions = [10*(getattr(box.maxPoint,k)-getattr(box.minPoint,k)) for k in 'xyz']
                assert all(abs(a-b) < 1e-6 for a,b in zip(dimensions, (20,20,10)))
                assert abs(body.volume*1000-expected_volume(opened)) < 1e-5
                args = {'document_id': tools.document_id, 'part_token': body.entityToken}
                for process in ('resin', 'powder'):
                    plan = {'process': process, 'criteria': {'sealed_voids': {'value': 0, 'units': 'count',
                        'basis': 'requirement', 'source': 'Synthetic fixture requires no sealed voids; not drainage/flow qualification'}}}
                    tools.dfm_plan({**args, 'stages': [plan]})
                    code = '''def run(context):
    d = context['dfm']
    offset, items, pages = 0, [], 0
    while True:
        page = d.measurements.enclosed_voids(0, offset, 1)
        assert page['status'] == 'measured' and page['totalLumps'] == 1
        items.extend(page['items'])
        pages += 1
        if page['nextOffset'] is None:
            break
        offset = page['nextOffset']
        assert pages < 8, 'Unexpected fixture topology'
    count = sum(item['sealedVoid'] for item in items)
    d.compare('Sealed cavities', count, 'sealed_voids', '<=', 'count', 'All native shells in the only lump, paged individually')
    d.unknown('Practical escape', 'Open topology does not establish passage sizing, flow, wash access, build orientation or absence of suction cups')
    return {'sealedVoids': count, 'shellCount': len(items), 'pages': pages}
'''
                    result = tools.run_script({'tool': 'fusion_dfm_check', 'arguments': {**args, 'stage': 0,
                        'title': 'Inspect all cavities', 'code': code}, 'cancelled': lambda: False})
                    assert result['ok'], result
                    assert result['result']['sealedVoids'] == 2-opened, result
                    assert result['result']['shellCount'] == 3-opened, result
                    assert result['result']['pages'] == 3-opened, result
                    expected = ['concern' if opened < 2 else 'pass', 'unknown']
                    assert [f['status'] for f in result['dfm']['findings']] == expected
                    assert result['dfm']['status'] == ('concerns' if opened < 2 else 'incomplete')
                    results.append({'body': name, 'process': process, 'openings': opened*2,
                        'volume_mm3': body.volume*1000, **result['result'], 'reportStatus': result['dfm']['status']})
    finally:
        for name in list(sys.modules):
            if name == package or name.startswith(package + '.'):
                del sys.modules[name]
    assert all(b.isValid and b.revisionId == rev for b,rev in protected)
    return {'fusionVersion': app.version, 'cases': results, 'allBodiesUnchanged': True}


if __name__ == '__main__':
    run(None)

"""Create/measure a disposable bent-strip solid with a known R3/R5 quarter bend.

No preview API is used here. Converting the fixture to native sheet metal and
creating its flat pattern are separate, explicit setup steps. measure(component)
can then be called read-only to inspect the existing native sheet-metal state.
"""
import importlib.util
import json
import math
from pathlib import Path
import sys

import adsk.core
import adsk.fusion


def measure(component):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests'
    assert component.name == 'DFM formed sheet fixture' and component.bRepBodies.count == 1
    body = component.bRepBodies.item(0)
    revision = body.revisionId
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_formed_sheet_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package + '.fusion_tools', fromlist=['DfmGeometry'])
    geometry = bridge.DfmGeometry(body, app, adsk.core, bridge.adsk.cam, fusion=adsk.fusion)
    expected_volume = (2*25 + 2*30 + math.pi/4*(5**2-3**2))*20
    assert abs(body.volume*1000 - expected_volume) < 1e-5
    cylinders = geometry.cylindrical_surfaces(limit=20)
    assert cylinders['nextOffset'] is None and len(cylinders['items']) == 2
    assert sorted((c['side'], round(c['radius_mm'], 6)) for c in cylinders['items']) == [('external',5),('internal',3)]
    thicknesses = []
    for cylinder in cylinders['items']:
        sampled = geometry.normal_thickness(cylinder['faceIndex'])
        assert sampled['status'] == 'measured' and abs(sampled['thickness_mm']-2)<1e-6, sampled
        thicknesses.append(sampled['thickness_mm'])
    metadata, bends = geometry.sheet_metal(), geometry.sheet_bends(limit=1)
    if body.isSheetMetal:
        assert metadata['status'] == 'measured' and abs(metadata['rule']['thickness_mm']-2)<1e-6
        if component.flatPattern is not None:
            # Fusion exposes this bend on both sheet surfaces, not one line per bend.
            assert bends['status'] == 'measured' and bends['totalLines'] == 2 and bends['nextOffset'] == 1, bends
            second = geometry.sheet_bends(offset=bends['nextOffset'], limit=1)
            assert second['status'] == 'measured' and second['totalLines'] == 2 and second['nextOffset'] is None, second
            lines = bends['items'] + second['items']
            assert [line['lineIndex'] for line in lines] == [0, 1], lines
            for line in lines:
                assert line['status'] == 'measured' and abs(abs(line['angle_deg'])-90)<1e-6, line
                assert abs(line['lineLength_mm']-20)<1e-6, line
                assert type(line['isBendUp']) is bool, line
            bends = {**bends, 'items': lines, 'nextOffset': None, 'pagesRead': 2}
    else:
        assert bends['status'] == 'unknown' and metadata['status'] == 'unknown'
    assert body.revisionId == revision
    return {'fusionVersion': app.version, 'volume_mm3': body.volume*1000,
            'expectedVolume_mm3': expected_volume, 'sampledBendWalls_mm': thicknesses,
            'radii_mm': sorted(c['radius_mm'] for c in cylinders['items']),
            'sheetMetadata': metadata, 'bendLines': bends, 'inspectionUnchanged': True}


def run(_context):
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests'
    assert app.userInterface.activeCommand == 'SelectCommand'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    name = 'DFM formed sheet fixture'
    assert not any(c.name == name for c in design.allComponents), 'Fixture exists; do not duplicate'
    protected = [(b,b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = name
    sketch = component.sketches.add(component.xYConstructionPlane)
    def p(x,y):
        return adsk.core.Point3D.create(x/10,y/10,0)
    for first, last in [((3,-25),(5,-25)),((5,-25),(5,0)),((0,5),(-30,5)),
                        ((-30,5),(-30,3)),((-30,3),(0,3)),((3,0),(3,-25))]:
        sketch.sketchCurves.sketchLines.addByTwoPoints(p(*first),p(*last))
    sketch.sketchCurves.sketchArcs.addByCenterStartSweep(p(0,0),p(5,0),math.pi/2)
    sketch.sketchCurves.sketchArcs.addByCenterStartSweep(p(0,0),p(0,3),-math.pi/2)
    assert sketch.profiles.count == 1
    feature = component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),
        adsk.core.ValueInput.createByString('20 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
    sketch.isVisible = False
    component.bRepBodies.item(0).name = 'DFM R3 bent strip'
    result = measure(component)
    assert all(b.isValid and b.revisionId == rev for b,rev in protected), 'Pre-existing body changed'
    print(json.dumps({**result,'preExistingBodiesUnchanged':True}))


if __name__ == '__main__':
    run(None)

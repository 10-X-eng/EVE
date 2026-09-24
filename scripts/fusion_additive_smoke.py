"""Development-only sealed/open cavity fixture for native additive DFM measurements."""
import importlib.util
import json
import math
from pathlib import Path
import sys

import adsk.core
import adsk.fusion
import adsk.cam


def run(_context):
    app = adsk.core.Application.get()
    if app.activeDocument.name != 'STEVE DFM development tests':
        raise RuntimeError('Activate the disposable STEVE DFM development tests document.')
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    if root.bRepBodies.count != 1 or root.bRepBodies.item(0).name != 'DFM fixture block':
        raise RuntimeError('Expected the original DFM fixture; nothing was changed.')
    if any(root.occurrences.item(i).component.name == 'DFM resin powder fixture' for i in range(root.occurrences.count)):
        raise RuntimeError('This cavity fixture already exists. Inspect it instead of repeating the changes.')
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_additive_development_probe'
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    helper = __import__(package + '.dfm_geometry', fromlist=['DfmGeometry'])
    original = root.bRepBodies.item(0).revisionId
    component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = 'DFM resin powder fixture'
    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(1,1,0))
    component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),
        adsk.core.ValueInput.createByString('10 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    body = component.bRepBodies.item(0)
    body.name = 'DFM cavity with drain'
    sketch.isVisible = False
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByString('3 mm'))
    plane = component.constructionPlanes.add(plane_input)
    cavity = component.sketches.add(plane)
    cavity.sketchCurves.sketchCircles.addByCenterRadius(cavity.modelToSketchSpace(adsk.core.Point3D.create(.5,.5,.3)), .2)

    def cut(profile, distance):
        settings = component.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        settings.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString(distance)),
                                 adsk.fusion.ExtentDirections.PositiveExtentDirection)
        settings.participantBodies = [component.bRepBodies.item(0)]
        feature = component.features.extrudeFeatures.add(settings)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, feature.errorOrWarningMessage

    cut(cavity.profiles.item(0), '4 mm')
    cavity.isVisible = False
    body = component.bRepBodies.item(0)
    measured = helper.DfmGeometry(body,app,adsk.core,adsk.cam,fusion=adsk.fusion)
    sealed = measured.enclosed_voids()
    voids = [shell for shell in sealed['items'] if shell['sealedVoid']]
    assert len(voids) == 1 and sealed['totalLumps'] == 1 and sealed['nextOffset'] is None, sealed
    # BRepShell.volume currently fails for some void shells. Independently
    # verify the known fixture through the change in total material volume.
    missing_material_mm3 = 1000*(1-body.volume)
    assert abs(missing_material_mm3 - math.pi*2**2*4) < 1e-5, sealed
    # Identify the inner ceiling from its measured point, not a guessed face index.
    ceiling = next(i for i in range(body.faces.count) if abs(body.faces.item(i).pointOnFace.z-.7)<1e-7)
    wall = measured.normal_thickness(ceiling)
    assert wall['status']=='measured' and abs(wall['thickness_mm']-3)<1e-6, wall
    drain = component.sketches.add(component.xYConstructionPlane)
    drain.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(.5,.5,0), .1)
    cut(drain.profiles.item(0), '4 mm')
    drain.isVisible = False
    opened = helper.DfmGeometry(component.bRepBodies.item(0),app,adsk.core,adsk.cam,fusion=adsk.fusion).enclosed_voids()
    assert not any(shell['sealedVoid'] for shell in opened['items']), opened
    assert opened['totalLumps']==1 and opened['nextOffset'] is None, opened
    assert root.bRepBodies.item(0).revisionId == original, 'Original fixture changed'
    print(json.dumps({'fusionVersion':app.version,'fixtureRemovedMaterial_mm3':missing_material_mm3,
        'nativeShellVolumeStatus':voids[0]['volumeStatus'],
        'ceilingThickness_mm':wall['thickness_mm'],'sealedVoidsAfterOpening':0,
        'originalFixtureUnchanged':True,'drainageCapability':'Not assessed; geometry alone does not prove practical drainage.'}))


if __name__ == '__main__':
    run(None)

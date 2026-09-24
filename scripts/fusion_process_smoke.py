"""Development-only mutating fixture test; run only in the named disposable document.

Creates a fresh child component containing a 20 mm diameter, 40 mm long cylinder,
verifies its rotational surfaces, then cuts a transverse hole and checks that
pure turning no longer covers every face. Never run on a customer design.
"""
import importlib.util
import json
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
        raise RuntimeError('Original DFM fixture is missing; no model was changed.')
    for index in range(root.occurrences.count):
        if root.occurrences.item(index).component.name == 'DFM turning fixture':
            raise RuntimeError('Turning fixture already exists. Inspect it instead of creating duplicate geometry.')
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_process_development_probe'
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    helper = __import__(package + '.dfm_geometry', fromlist=['DfmGeometry'])
    original_revision = root.bRepBodies.item(0).revisionId
    component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = 'DFM turning fixture'
    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(0,0,0), 1)
    feature = component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),
        adsk.core.ValueInput.createByString('40 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    body = component.bRepBodies.item(0)
    body.name = 'DFM cylinder with secondary drilling'
    sketch.isVisible = False
    measurements = helper.DfmGeometry(body, app, adsk.core, adsk.cam)
    clean = measurements.rotational_surfaces([0,0,0], [0,0,1])
    assert clean['nextOffset'] is None, clean
    assert all(face['status'] == 'compatible' for face in clean['items']), clean
    sheet = measurements.sheet_metal()
    assert sheet['status'] == 'unknown' and not sheet['isSheetMetal'], sheet
    # This component contains only the intended fixture, so the cut cannot touch
    # the original block or any document outside this disposable test document.
    cross = component.sketches.add(component.yZConstructionPlane)
    center = cross.modelToSketchSpace(adsk.core.Point3D.create(0,0,2))
    cross.sketchCurves.sketchCircles.addByCenterRadius(center, .2)
    cut_input = component.features.extrudeFeatures.createInput(cross.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
    cut_input.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString('20 mm')),
                               adsk.fusion.ExtentDirections.PositiveExtentDirection)
    cut_input.participantBodies = [body]
    cut = component.features.extrudeFeatures.add(cut_input)
    assert cut.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, cut.errorOrWarningMessage
    cross.isVisible = False
    body = component.bRepBodies.item(0)
    drilled = helper.DfmGeometry(body, app, adsk.core, adsk.cam).rotational_surfaces([0,0,0], [0,0,1])
    assert any(face['status'] == 'nonrotational' for face in drilled['items']), drilled
    stale_rejected = False
    try:
        measurements.rotational_surfaces([0,0,0], [0,0,1])
    except ValueError:
        stale_rejected = True
    assert stale_rejected, 'Old geometry revision remained usable'
    assert root.bRepBodies.item(0).revisionId == original_revision, 'Original fixture changed'
    print(json.dumps({'fusionVersion': app.version, 'cylinderFaces': [f['status'] for f in clean['items']],
        'drilledFaces': [{'surface': f['surface'], 'status': f['status']} for f in drilled['items']],
        'sheetMetal': sheet, 'oldRevisionRejected': stale_rejected, 'originalFixtureUnchanged': True}))


if __name__ == '__main__':
    run(None)

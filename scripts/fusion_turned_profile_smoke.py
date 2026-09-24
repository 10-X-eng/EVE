"""Development-only stepped/grooved shaft fixture in the named DFM test document.

Expected geometry is specified independently as an axisymmetric radial profile.
Verifies paged measurements, missing setup coverage and supplied criterion limits.
Creates one child component; never saves or touches existing model geometry.
"""
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
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    name = 'DFM stepped shaft fixture'
    assert not any(c.name == name for c in design.allComponents), 'Fixture already exists; do not duplicate'
    protected = [(b,b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1]/'addin'/'STEVE'/'steve'
    package = 'steve_turned_profile_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package+'.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package,source/'__init__.py',submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package+'.fusion_tools',fromlist=['FusionTools'])
    component = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = name
    sketch = component.sketches.add(component.xZConstructionPlane)
    # (radius, axial coordinate) in mm. Ø4 through bore; stepped outside
    # Ø20 x 10, Ø15 x 10, Ø12 x 2 groove floor, Ø15 x 18.
    profile = [(2,0),(10,0),(10,10),(7.5,10),(7.5,20),(6,20),(6,22),(7.5,22),(7.5,40),(2,40)]
    points = [sketch.modelToSketchSpace(adsk.core.Point3D.create(r/10,0,z/10)) for r,z in profile]
    for start,end in zip(points,points[1:]+points[:1]):
        sketch.sketchCurves.sketchLines.addByTwoPoints(start,end)
    assert sketch.profiles.count == 1
    rev = component.features.revolveFeatures.createInput(sketch.profiles.item(0),component.zConstructionAxis,
                                                       adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    assert rev.setAngleExtent(False,adsk.core.ValueInput.createByString('360 deg'))
    feature = component.features.revolveFeatures.add(rev)
    assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
    sketch.isVisible = False
    body = component.bRepBodies.item(0)
    body.name = 'DFM stepped grooved through-bored shaft'
    expected_volume_mm3 = math.pi*(10**2*10+7.5**2*10+6**2*2+7.5**2*18-2**2*40)
    assert body.isSolid and abs(body.volume*1000-expected_volume_mm3)<1e-5
    revision = body.revisionId
    measurement = bridge.DfmGeometry(body,app,adsk.core,bridge.adsk.cam,fusion=adsk.fusion)
    bands, surfaces = [], []
    offset = 0
    while offset is not None:
        page = measurement.cylindrical_walls(offset=offset,limit=2)
        assert not page['unsupported'], page
        bands.extend(page['items'])
        offset = page['nextOffset']
    expected = [('external',12,2),('external',15,10),('external',15,18),('external',20,10),('internal',4,40)]
    actual = sorted((b['side'],round(b['diameter_mm'],6),round(b['axial_span_mm'],6)) for b in bands)
    assert actual == expected, actual
    offset = 0
    while offset is not None:
        page = measurement.rotational_surfaces([0,0,0],[0,0,1],offset=offset,limit=3)
        surfaces.extend(page['items'])
        offset = page['nextOffset']
    assert len(surfaces) == body.faces.count and all(s['status']=='compatible' for s in surfaces), surfaces
    wrong_axis = measurement.rotational_surfaces([1,0,0],[0,0,1],limit=20)
    assert any(s['status']=='nonrotational' for s in wrong_axis['items']), wrong_axis
    with tempfile.TemporaryDirectory(prefix='steve-turned-profile-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument,'turned-profile-probe',False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        arguments = {'document_id':tools.document_id,'part_token':body.entityToken}
        results = []
        for limit in (19,20,21):
            tools.dfm_plan({**arguments,'stages':[{'process':'turning','criteria':{
                'diameter':{'value':limit,'units':'mm','source':'Explicit fixture finished-diameter limit; not a chucking claim','basis':'profile'}}}]})
            result = tools.run_script({'tool':'fusion_dfm_check','arguments':{**arguments,'stage':0,
                'title':'Check finished outside diameter', 'code':'''def run(context):
    d = context['dfm']
    outside = []
    offset = 0
    while offset is not None:
        page = d.measurements.cylindrical_walls(offset=offset,limit=2)
        if page['unsupported']:
            d.unknown('Outside diameter coverage','An unsupported cylindrical wall remains')
        outside.extend(w['diameter_mm'] for w in page['items'] if w['side']=='external')
        offset = page['nextOffset']
    d.compare('Largest measured outside cylindrical band',max(outside),'diameter','<=','mm','All verified external cylindrical bands, not stock diameter or chuck clearance')
    d.unknown('Setup and tools','Workholding, stock, groove-tool fit, boring/drilling reach and approach are not specified')
    return {'largest_mm':max(outside)}
'''},'cancelled':lambda:False})
            assert result['ok'], result
            assert result['dfm']['findings'][-1]['status'] == 'unknown'
            results.append(result['dfm']['findings'][0]['status'])
        assert results == ['concern','pass','pass'], results
    assert body.revisionId == revision
    assert all(b.isValid and b.revisionId==old for b,old in protected), 'Existing body changed'
    print(json.dumps({'fusionVersion':app.version,'bands':actual,'compatibleFaces':len(surfaces),
        'wrongAxisRejected':True,'volume_mm3':body.volume*1000,'expectedVolume_mm3':expected_volume_mm3,
        'limits_mm':[19,20,21],'criterionResults':results,'unspecifiedSetupRemainsUnknown':True,
        'preExistingBodiesUnchanged':True}))


if __name__ == '__main__':
    run(None)

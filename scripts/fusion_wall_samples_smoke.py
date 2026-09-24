"""Development-only stepped-wall fixture; sample evidence is never a global wall pass.

Creates one disposable component with known 0.8/1.2/2 mm regions and an overlapping
independent body along one test ray. Synthetic profiles exercise comparison rules;
their values are not manufacturing recommendations for FDM, resin or powder.
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
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong document'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command'
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    assert root.bRepBodies.count == 1 and root.bRepBodies.item(0).name == 'DFM fixture block'
    name = 'DFM stepped wall fixture'
    assert not any(c.name == name for c in design.allComponents), 'Fixture exists; do not duplicate it'
    protected = [(b,b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1]/'addin'/'STEVE'/'steve'
    package = 'steve_wall_samples_probe'
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
    profile = [(0,0),(30,0),(30,2),(20,2),(20,1.2),(10,1.2),(10,.8),(0,.8)]
    points = [sketch.modelToSketchSpace(adsk.core.Point3D.create(x/10,0,z/10)) for x,z in profile]
    for start,end in zip(points,points[1:]+points[:1]):
        sketch.sketchCurves.sketchLines.addByTwoPoints(start,end)
    component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),adsk.core.ValueInput.createByString('10 mm'),
                                                adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    sketch.isVisible = False
    body = component.bRepBodies.item(0)
    body.name = 'DFM three wall thicknesses'
    assert body.isSolid and abs(body.volume*1000-(10*10*.8+10*10*1.2+10*10*2))<1e-6
    samples = []
    for i in range(body.faces.count):
        face = body.faces.item(i)
        point = face.pointOnFace
        ok,normal = face.evaluator.getNormalAtPoint(point)
        if ok and normal.z>.999:
            expected = .8 if point.x<1 else 1.2 if point.x<2 else 2
            samples.append((i,expected,point))
    assert sorted(expected for i,expected,p in samples) == [.8,1.2,2]
    thick = next(point for i,expected,point in samples if expected == 2)
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(component.xYConstructionPlane,adsk.core.ValueInput.createByString('1.6 mm'))
    plane = component.constructionPlanes.add(plane_input)
    neighbor_sketch = component.sketches.add(plane)
    a=neighbor_sketch.modelToSketchSpace(adsk.core.Point3D.create(thick.x-.1,thick.y-.1,.16))
    b=neighbor_sketch.modelToSketchSpace(adsk.core.Point3D.create(thick.x+.1,thick.y+.1,.16))
    neighbor_sketch.sketchCurves.sketchLines.addTwoPointRectangle(a,b)
    component.features.extrudeFeatures.addSimple(neighbor_sketch.profiles.item(0),adsk.core.ValueInput.createByString('.1 mm'),
                                                adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    neighbor_sketch.isVisible = False
    assert component.bRepBodies.count == 2
    neighbor = component.bRepBodies.item(1)
    neighbor.name = 'DFM deliberate overlapping ray neighbor'
    revisions = [(b,b.revisionId) for b in component.bRepBodies]
    measured = bridge.DfmGeometry(body,app,adsk.core,bridge.adsk.cam,fusion=adsk.fusion)
    evidence=[]
    for index,expected,point in samples:
        result=measured.normal_thickness(index)
        assert result['status']=='measured' and abs(result['thickness_mm']-expected)<1e-6, result
        assert abs(result['exitPoint_mm'][2])<1e-6, result
        evidence.append({'faceIndex':index,'expected_mm':expected,'actual_mm':result['thickness_mm']})
    # Prove the neighbor actually participates in the native ray result. A test
    # with an off-ray neighbor would not establish that same-body filtering works.
    hits=adsk.core.ObjectCollection.create()
    entities=component.findBRepUsingRay(adsk.core.Point3D.create(thick.x,thick.y,.19),
        adsk.core.Vector3D.create(0,0,-1),adsk.fusion.BRepEntityTypes.BRepFaceEntityType,app.pointTolerance,False,hits)
    hit_bodies=[adsk.fusion.BRepFace.cast(entity).body for entity in entities]
    assert neighbor in hit_bodies and body in hit_bodies
    assert hit_bodies.index(neighbor)<hit_bodies.index(body), 'Neighbor must precede the intended exit'
    results=[]
    with tempfile.TemporaryDirectory(prefix='steve-wall-samples-') as folder:
        tools=bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app,tools.task,tools.debug=app,None,None
        tools.document,tools.document_id,tools.closed=app.activeDocument,'wall-samples-probe',False
        tools.dfm=bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        arguments={'document_id':tools.document_id,'part_token':body.entityToken}
        for process,limit in [('fdm',1.2),('resin',.8),('powder',1.5)]:
            tools.dfm_plan({**arguments,'stages':[{'process':process,'criteria':{
                'wall':{'value':limit,'units':'mm','source':'Synthetic test profile only; not a process recommendation','basis':'profile'}}}]})
            code='''def run(context):
    dfm=context['dfm']
    for index in INDICES:
        measurement=dfm.measurements.normal_thickness(index)
        if measurement['status']=='measured':
            dfm.compare('Local face sample '+str(index),measurement['thickness_mm'],'wall','>=','mm','Single same-body normal ray; not a global minimum')
        else:
            dfm.unknown('Local face sample '+str(index),measurement['reason'])
    dfm.unknown('Whole-part wall coverage','Unsampled points, edges and thin features are not assessed by these three face samples')
    return {'sampleCount':len(INDICES)}
'''.replace('INDICES',repr([i for i,expected,p in sorted(samples,key=lambda item:item[1])]))
            report=tools.run_script({'tool':'fusion_dfm_check','arguments':{**arguments,'stage':0,
                'title':'Check individual additive wall samples','code':code},'cancelled':lambda:False})
            assert report['ok'], report
            expected_status=['concern' if value<limit-1e-12 else 'pass' for value in (.8,1.2,2)]
            statuses=[f['status'] for f in report['dfm']['findings']]
            assert statuses==expected_status+['unknown'], report
            assert report['dfm']['status']!='checked', report
            results.append({'process':process,'syntheticLimit_mm':limit,'sampleStatuses':statuses,'reportStatus':report['dfm']['status']})
    assert all(b.isValid and b.revisionId==old for b,old in protected+revisions), 'Inspection changed a body'
    print(json.dumps({'fusionVersion':app.version,'samples':evidence,'onRayNeighborIgnored':True,
        'syntheticProfiles':results,'globalMinimumClaimed':False,'preExistingBodiesUnchanged':True}))


if __name__ == '__main__':
    run(None)

"""Development-only rounded pocket fixture, including partial cylindrical corners."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

import adsk.core
import adsk.fusion


def run(_context):
    app=adsk.core.Application.get()
    assert app.activeDocument.name=='STEVE DFM development tests', 'Wrong document'
    assert app.userInterface.activeCommand=='SelectCommand', 'Finish the active command'
    design=adsk.fusion.Design.cast(app.activeProduct)
    root=design.rootComponent
    assert root.bRepBodies.count==1 and root.bRepBodies.item(0).name=='DFM fixture block'
    name='DFM rounded pocket fixture'
    assert not any(c.name==name for c in design.allComponents), 'Fixture exists; do not duplicate'
    protected=[(b,b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source=Path(__file__).resolve().parents[1]/'addin'/'STEVE'/'steve'
    package='steve_pocket_radius_probe'
    for key in list(sys.modules):
        if key==package or key.startswith(package+'.'):
            del sys.modules[key]
    spec=importlib.util.spec_from_file_location(package,source/'__init__.py',submodule_search_locations=[str(source)])
    module=importlib.util.module_from_spec(spec)
    sys.modules[package]=module
    spec.loader.exec_module(module)
    bridge=__import__(package+'.fusion_tools',fromlist=['FusionTools'])
    component=root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name=name
    sketch=component.sketches.add(component.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0),adsk.core.Point3D.create(4,3,0))
    component.features.extrudeFeatures.addSimple(sketch.profiles.item(0),adsk.core.ValueInput.createByString('10 mm'),adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    sketch.isVisible=False
    plane_input=component.constructionPlanes.createInput()
    plane_input.setByOffset(component.xYConstructionPlane,adsk.core.ValueInput.createByString('5 mm'))
    plane=component.constructionPlanes.add(plane_input)
    pocket=component.sketches.add(plane)
    def point(x,y):
        return pocket.modelToSketchSpace(adsk.core.Point3D.create(x/10,y/10,.5))
    for a,b in [((11,10),(29,10)),((30,11),(30,19)),((29,20),(11,20)),((10,19),(10,11))]:
        pocket.sketchCurves.sketchLines.addByTwoPoints(point(*a),point(*b))
    for center,start in [((29,11),(29,10)),((29,19),(30,19)),((11,19),(11,20)),((11,11),(10,11))]:
        pocket.sketchCurves.sketchArcs.addByCenterStartSweep(point(*center),point(*start),math.pi/2)
    assert pocket.profiles.count==1
    cut=component.features.extrudeFeatures.createInput(pocket.profiles.item(0),adsk.fusion.FeatureOperations.CutFeatureOperation)
    cut.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString('5 mm')),adsk.fusion.ExtentDirections.PositiveExtentDirection)
    cut.participantBodies=[component.bRepBodies.item(0)]
    feature=component.features.extrudeFeatures.add(cut)
    assert feature.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
    pocket.isVisible=False
    body=component.bRepBodies.item(0)
    body.name='DFM four R1 pocket corners'
    expected_volume=40*30*10-(20*10-(4-math.pi)*1**2)*5
    assert abs(body.volume*1000-expected_volume)<1e-5
    revision=body.revisionId
    measurement=bridge.DfmGeometry(body,app,adsk.core,bridge.adsk.cam,fusion=adsk.fusion)
    corners=[]
    offset=0
    while offset is not None:
        page=measurement.cylindrical_surfaces(offset=offset,limit=2)
        corners.extend(page['items'])
        offset=page['nextOffset']
    assert len(corners)==4
    for corner in corners:
        assert corner['side']=='internal' and abs(corner['radius_mm']-1)<1e-6, corner
        assert abs(abs(corner['axis'][2])-1)<1e-7, corner
        face=body.faces.item(corner['faceIndex'])
        assert abs(face.area*100-(math.pi*1/2)*5)<1e-6
        assert abs(face.boundingBox.minPoint.z-.5)<1e-7 and abs(face.boundingBox.maxPoint.z-1)<1e-7
    bands=measurement.cylindrical_walls(limit=20)
    assert not bands['items'] and len(bands['unsupported'])==4 and bands['nextOffset'] is None, bands
    outcomes=[]
    with tempfile.TemporaryDirectory(prefix='steve-pocket-radius-') as folder:
        tools=bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app,tools.task,tools.debug=app,None,None
        tools.document,tools.document_id,tools.closed=app.activeDocument,'pocket-radius-probe',False
        tools.dfm=bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        arguments={'document_id':tools.document_id,'part_token':body.entityToken}
        for radius in (.5,1,3):
            tools.dfm_plan({**arguments,'stages':[{'process':'milling','criteria':{
                'cutter_radius':{'value':radius,'units':'mm','source':'Explicit fixture tool radius, axial approach along pocket Z','basis':'profile'}}}]})
            code='''def run(context):
    d=context['dfm']
    corner_indices=INDICES
    offset=0
    while offset is not None:
        page=d.measurements.cylindrical_surfaces(offset=offset,limit=2)
        for face in page['items']:
            if face['faceIndex'] not in corner_indices:
                continue
            if face['status']!='measured' or face.get('side')!='internal':
                d.unknown('Corner '+str(face['faceIndex']),'Radius/side was not verified')
            else:
                d.compare('Corner '+str(face['faceIndex']),face['radius_mm'],'cutter_radius','>=','mm','Independently identified vertical quarter-cylinder pocket corner; radius comparison only')
        offset=page['nextOffset']
    d.unknown('Machining strategy','Equality does not establish a suitable toolpath. Reach, holder clearance, engagement, rigidity and other geometry remain unassessed')
'''.replace('INDICES',repr([c['faceIndex'] for c in corners]))
            result=tools.run_script({'tool':'fusion_dfm_check','arguments':{**arguments,'stage':0,'title':'Check known pocket-corner radii','code':code},'cancelled':lambda:False})
            assert result['ok'],result
            expected='pass' if radius<=1 else 'concern'
            assert [f['status'] for f in result['dfm']['findings']]==[expected]*4+['unknown'],result
            outcomes.append({'cutterRadius_mm':radius,'cornerResults':[expected]*4,'overall':result['dfm']['status']})
    assert body.revisionId==revision
    assert all(b.isValid and b.revisionId==old for b,old in protected), 'Existing geometry changed'
    print(json.dumps({'fusionVersion':app.version,'cornerRadii_mm':[c['radius_mm'] for c in corners],
        'partialFacesRemainUnsupportedAsFullBands':True,'volume_mm3':body.volume*1000,'expectedVolume_mm3':expected_volume,
        'profileComparisons':outcomes,'preExistingBodiesUnchanged':True}))


if __name__=='__main__':
    run(None)

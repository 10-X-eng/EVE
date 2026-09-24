"""Development-only assembly fixtures in the named disposable DFM document.

Creates imperial-sized mixed-process bodies and repeated/nested occurrences.
Checks native plan identity, explicit build-frame conversion and unchanged
pre-existing bodies. Does not save, export, switch documents or upload anything.
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
    name = 'DFM assembly fixture'
    assert not any(c.name == name for c in design.allComponents), 'Fixture exists; inspect instead of recreating'
    protected = [(b,b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    source = Path(__file__).resolve().parents[1] / 'addin' / 'STEVE' / 'steve'
    package = 'steve_assembly_dfm_probe'
    for key in list(sys.modules):
        if key == package or key.startswith(package+'.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(package, source/'__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    bridge = __import__(package+'.fusion_tools',fromlist=['FusionTools'])

    def transform(degrees, x_mm, y_mm):
        matrix = adsk.core.Matrix3D.create()
        matrix.setToRotation(math.radians(degrees), adsk.core.Vector3D.create(0,0,1), adsk.core.Point3D.create(0,0,0))
        matrix.translation = adsk.core.Vector3D.create(x_mm/10,y_mm/10,0)
        return matrix

    first = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    component = first.component
    component.name = name
    sketch = component.sketches.add(component.xYConstructionPlane)
    width = design.unitsManager.evaluateExpression('2 in','cm')
    length = design.unitsManager.evaluateExpression('1 in','cm')
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(width,length,0))
    component.features.extrudeFeatures.addSimple(sketch.profiles.item(0), adsk.core.ValueInput.createByString('0.125 in'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    plate = component.bRepBodies.item(0)
    plate.name = 'DFM imperial plate'
    sketch.isVisible = False
    shaft_sketch = component.sketches.add(component.xYConstructionPlane)
    shaft_sketch.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(10,0,0), .5)
    component.features.extrudeFeatures.addSimple(shaft_sketch.profiles.item(0), adsk.core.ValueInput.createByString('20 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    shaft = component.bRepBodies.item(1)
    shaft.name = 'DFM assembly shaft'
    shaft_sketch.isVisible = False
    repeated = root.occurrences.addExistingComponent(component, transform(90,100,20))
    parent = root.occurrences.addNewComponent(transform(90,200,0))
    parent.component.name = 'DFM nested assembly fixture'
    parent.component.occurrences.addExistingComponent(component, transform(90,30,0))
    nested = parent.childOccurrences.item(0)
    body_revision = plate.revisionId
    outputs = []
    with tempfile.TemporaryDirectory(prefix='steve-assembly-dfm-') as folder:
        tools = bridge.FusionTools.__new__(bridge.FusionTools)
        tools.app, tools.task, tools.debug = app, None, None
        tools.document, tools.document_id, tools.closed = app.activeDocument, 'assembly-dfm-probe', False
        tools.dfm = bridge.DfmStore(folder)
        tools.dfm.set_enabled(True)
        def args(body):
            return {'document_id':tools.document_id,'part_token':body.entityToken}
        criteria = {key:{'value':limit,'units':'mm','source':'Explicit fixture printer profile','basis':'profile'}
                    for key,limit in zip(('x','y','z'),(60,30,5))}
        plate_plan = [{'process':'milling','notes':'First stage, user-chosen fixture process'},
                      {'process':'fdm','criteria':criteria}]
        tools.dfm_plan({**args(first.bRepBodies.item(0)), 'stages':plate_plan})
        tools.dfm_plan({**args(shaft), 'stages':[{'process':'turning','notes':'Independent second body'}]})
        assert len(tools.dfm_plan(args(shaft))['plan']['stages']) == 1
        for occurrence, expected_bounds, expected_status in (
                (first, ([0,0,0],[50.8,25.4,3.175]), 'checked'),
                (repeated, ([74.6,20,0],[100,70.8,3.175]), 'concerns'),
                (nested, ([149.2,4.6,0],[200,30,3.175]), 'checked')):
            proxy = occurrence.bRepBodies.item(0)
            assert tools.dfm_plan(args(proxy))['plan']['stages'] == plate_plan, 'Repeated instance lost shared plan'
            box = proxy.boundingBox
            bounds = [[10*getattr(point,k) for k in ('x','y','z')] for point in (box.minPoint,box.maxPoint)]
            assert all(abs(a-b)<1e-6 for actual,expected in zip(bounds,expected_bounds) for a,b in zip(actual,expected)), (occurrence.fullPathName,bounds)
            inverse = occurrence.transform2.copy()
            assert inverse.invert()
            axes = []
            for values in ((1,0,0),(0,1,0)):
                vector = adsk.core.Vector3D.create(*values)
                assert vector.transformBy(inverse)
                axes.append([vector.x,vector.y,vector.z])
            code = '''def run(context):
    dfm = context['dfm']
    measurement = dfm.measurements.envelope(X_AXIS,Y_AXIS)
    for key,value in zip(('x','y','z'),measurement['dimensions_mm']):
        dfm.compare(key,value,key,'<=','mm','Assembly build axes explicitly transformed into native part coordinates')
    return measurement
'''.replace('X_AXIS',repr(axes[0])).replace('Y_AXIS',repr(axes[1]))
            result = tools.run_script({'tool':'fusion_dfm_check','arguments':{**args(proxy),'stage':1,
                'title':'Check repeated plate in assembly build frame','code':code},'cancelled':lambda:False})
            assert result['ok'] and result['dfm']['status'] == expected_status, result
            assert all(abs(value-(hi-lo))<1e-6 for value,lo,hi in zip(result['result']['dimensions_mm'],bounds[0],bounds[1])), result
            outputs.append({'occurrence':occurrence.fullPathName,'assemblyBounds_mm':bounds,
                'nativeBuildAxes':axes,'envelope_mm':result['result']['dimensions_mm'],'status':result['dfm']['status']})
        assert plate.revisionId == body_revision, 'Read-only checks changed plate geometry'
        # Reading shared process metadata through rotated instances must not modify
        # the independent second body's turning plan.
        assert tools.dfm_plan(args(shaft))['plan']['stages'][0]['process'] == 'turning'
        assert all(b.isValid and b.revisionId==revision for b,revision in protected), 'Pre-existing fixture changed'
        print(json.dumps({'fusionVersion':app.version,'sharedPlanAcrossThreeInstances':True,
            'independentBodyPlan':True,'orderedStages':['milling','fdm'],'imperialConversionVerified':True,
            'preExistingBodiesUnchanged':True,'instances':outputs}))


if __name__ == '__main__':
    run(None)

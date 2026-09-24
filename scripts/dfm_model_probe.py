"""Opt-in paired model inspection/repair probe in the named disposable Fusion fixture.

Uses STEVE's existing ChatGPT sign-in and app-server, with ephemeral conversations.
No credentials are copied. The development MCP is a test adapter only, never a
STEVE product dependency. Default trials are read-only. --repair explicitly creates
two disposable child fixtures and allows model edits confined to those trials.
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'addin' / 'STEVE'))
from steve.controller import thread_start_params, message_input
from steve.transport import Transport
from steve.tool_protocol import validate_call, tool_failure, tool_response, ToolError


class FusionProbe:
    def __init__(self, url, repair=False):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('Use the explicitly supplied loopback development MCP endpoint.')
        self.url, self.session, self.counter = url, None, 0
        self.lock = threading.Lock()
        self.rpc('initialize', {'protocolVersion':'2024-11-05','capabilities':{},
            'clientInfo':{'name':'steve-dfm-probe','version':'1'}})
        self.rpc('notifications/initialized', {}, notification=True)
        self.package = 'steve_model_probe_' + uuid4().hex
        self.repair = repair

    def rpc(self, method, params, notification=False):
        with self.lock:
            self.counter += 1
            payload = {'jsonrpc':'2.0','method':method,'params':params}
            if not notification:
                payload['id'] = self.counter
            headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream',
                       'MCP-Protocol-Version':'2024-11-05'}
            if self.session:
                headers['Mcp-Session-Id'] = self.session
            with urlopen(Request(self.url,json.dumps(payload).encode(),headers),timeout=45) as response:
                self.session = response.headers.get('Mcp-Session-Id',self.session)
                raw = response.read(2*1024*1024)
                value = json.loads(raw) if raw else {}
            if value.get('error'):
                raise RuntimeError('Development MCP rejected the request: '+str(value['error']))
            return value.get('result',{})

    def script(self, source, read_only=True):
        result = self.rpc('tools/call',{'name':'fusion_mcp_execute',
            'arguments':{'featureType':'script','object':{'script':source,'readOnly':read_only}}})
        envelope = json.loads(result['content'][0]['text'])
        if not envelope.get('success'):
            raise RuntimeError(envelope.get('error','Fusion development probe failed'))
        return json.loads(envelope['message'])

    def setup(self, enabled):
        package = self.package
        source = str(ROOT / 'addin' / 'STEVE' / 'steve')
        return self.script(f'''def run(_context):
    import importlib.util, sys, tempfile, json
    from pathlib import Path
    import adsk.core, adsk.fusion
    app = adsk.core.Application.get()
    assert app.activeDocument.name == 'STEVE DFM development tests', 'Wrong test document; nothing inspected'
    assert app.userInterface.activeCommand == 'SelectCommand', 'Finish the active command before the probe'
    design = adsk.fusion.Design.cast(app.activeProduct)
    assert design.rootComponent.bRepBodies.count == 1
    body = design.rootComponent.bRepBodies.item(0)
    assert body.name == 'DFM fixture block'
    package = {package!r}
    source = Path({source!r})
    spec = importlib.util.spec_from_file_location(package, source / '__init__.py', submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    module.protected = [(b, b.revisionId) for c in design.allComponents for b in c.bRepBodies]
    if {self.repair!r}:
        component = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        component.name = 'DFM repair ' + ('on' if {enabled!r} else 'off') + ' ' + package[-8:]
        sketch = component.sketches.add(component.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(0,0,0), adsk.core.Point3D.create(6,4,0))
        component.features.extrudeFeatures.addSimple(sketch.profiles.item(0), adsk.core.ValueInput.createByString('8 mm'), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        body = component.bRepBodies.item(0)
        body.name = 'DFM repair trial block'
        hole = component.sketches.add(component.xYConstructionPlane)
        hole.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(2,2,0), .2)
        cut = component.features.extrudeFeatures.createInput(hole.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
        cut.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString('5 mm')), adsk.fusion.ExtentDirections.PositiveExtentDirection)
        cut.participantBodies = [body]
        feature = component.features.extrudeFeatures.add(cut)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        sketch.isVisible = hole.isVisible = False
        body = component.bRepBodies.item(0)
        module.component = component
    bridge = __import__(package + '.fusion_tools', fromlist=['FusionTools'])
    tools = bridge.FusionTools.__new__(bridge.FusionTools)
    tools.app, tools.debug, tools.closed = app, None, False
    tools.document, tools.document_id = app.activeDocument, package
    snapshot = {{'document_id':package,'name':app.activeDocument.name,'activeProduct':'DesignProductType',
        'targetPinned':True,'selectionCount':1,'selection':[{{'index':0,'name':body.name,'entityToken':body.entityToken,'objectType':body.objectType}}],
        'dataPanel':{{}},'dfmEnabled':{enabled!r}}}
    tools.task = {{'snapshot':snapshot,'product':app.activeProduct,'selection':[body]}}
    module.temp = tempfile.TemporaryDirectory(prefix='steve-model-probe-')
    tools.dfm = bridge.DfmStore(module.temp.name)
    tools.dfm.set_enabled({enabled!r})
    module.tools, module.originalBody, module.originalRevision = tools, body, body.revisionId
    print(json.dumps(snapshot))
''', read_only=not self.repair)

    def call(self, tool, arguments):
        validate_call(tool, arguments)
        allowed = ('fusion_inspect_document','fusion_query_python','fusion_api_help','fusion_dfm_plan','fusion_dfm_check','fusion_search_docs')
        if self.repair:
            allowed += ('fusion_execute_python',)
        if tool not in allowed:
            raise ToolError('invalid_arguments','Use the available geometry/documentation tools. This benchmark does not provide viewport images, network tools, exports or uploads; edits require --repair.')
        if arguments.get('execution_mode') == 'application':
            raise ToolError('invalid_arguments','This fixture benchmark allows command edits only; keep the current document.')
        if tool == 'fusion_search_docs' and arguments.get('scope','installed') != 'installed':
            raise ToolError('invalid_arguments','This benchmark uses installed documentation only.')
        return self.script(f'''def run(_context):
    import sys, json
    module = sys.modules[{self.package!r}]
    tools = module.tools
    assert tools.app.activeDocument == tools.document and tools.document.isValid, 'Test document changed'
    assert tools.app.userInterface.activeCommand == 'SelectCommand', 'Fusion command became active'
    name, args = {tool!r}, {arguments!r}
    job = {{'tool':name,'arguments':args,'cancelled':lambda:False}}
    tools.check_target(job)
    if name == 'fusion_inspect_document':
        result = {{'ok':True,**tools.inspect_document()}}
    elif name == 'fusion_api_help':
        result = tools.api_help(args['path'])
    elif name == 'fusion_search_docs':
        result = tools.search_docs(args['query'],args.get('offset',0))
    elif name == 'fusion_dfm_plan':
        result = tools.dfm_plan(args)
    else:
        result = tools.run_script(job)
        tools.verify(job, result)
    assert all(b.isValid and b.revisionId == revision for b,revision in module.protected), 'A protected fixture changed'
    if not {self.repair!r}:
        assert module.originalBody.revisionId == module.originalRevision, 'Inspection changed the fixture'
    print(json.dumps(result))
''', read_only=tool != 'fusion_execute_python')

    def verify_repair(self):
        """Independent geometry assertions, not the generating model's self-grade."""
        return self.script(f'''def run(_context):
    import sys, json, math
    import adsk.core
    module = sys.modules[{self.package!r}]
    assert all(b.isValid and b.revisionId == rev for b,rev in module.protected), 'Protected geometry changed'
    component = module.component
    assert component.bRepBodies.count == 1, 'Repair must keep one solid'
    body = component.bRepBodies.item(0)
    box = body.boundingBox
    dimensions = [10*(getattr(box.maxPoint,k)-getattr(box.minPoint,k)) for k in ('x','y','z')]
    origin = [10*getattr(box.minPoint,k) for k in ('x','y','z')]
    assert all(abs(a-b)<1e-6 for a,b in zip(dimensions,[60,40,9])), dimensions
    assert all(abs(v)<1e-6 for v in origin), origin
    cylinders = [adsk.core.Cylinder.cast(face.geometry) for face in body.faces]
    cylinders = [c for c in cylinders if c is not None]
    assert len(cylinders) == 1 and abs(cylinders[0].radius-.2)<1e-7, 'Hole diameter changed'
    cylinder = cylinders[0]
    assert abs(cylinder.origin.x-2)<1e-7 and abs(cylinder.origin.y-2)<1e-7, 'Hole center changed'
    hole_faces = [face for face in body.faces if adsk.core.Cylinder.cast(face.geometry)]
    wall = hole_faces[0]
    span = 10*(wall.boundingBox.maxPoint.z-wall.boundingBox.minPoint.z)
    assert abs(span-5)<1e-6 and abs(wall.boundingBox.minPoint.z)<1e-7, 'Hole depth/opening changed'
    assert abs(body.volume-(6*4*.9-math.pi*.2**2*.5))<1e-7, 'Unexpected material change'
    assert body.isSolid and body.revisionId != module.originalRevision, 'No verified repair'
    print(json.dumps({{'passed':True,'dimensions_mm':dimensions,'holeDiameter_mm':20*cylinder.radius,'holeDepth_mm':span,
        'ceiling_mm':dimensions[2]-span,'protectedBodiesUnchanged':True,'independentGeometryChecks':'passed'}}))
''')

    def close(self):
        self.script(f'''def run(_context):
    import sys, json
    module = sys.modules.get({self.package!r})
    if module and hasattr(module, 'temp'):
        module.temp.cleanup()
    for name in list(sys.modules):
        if name == {self.package!r} or name.startswith({self.package!r}+'.'):
            del sys.modules[name]
    print(json.dumps({{'cleaned':True}}))
''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mcp-url')
    parser.add_argument('--account-only',action='store_true')
    parser.add_argument('--repair',action='store_true',help='Allow edits on two new disposable child fixtures in the named test document.')
    parser.add_argument('--output',type=Path,default=ROOT/'.cache'/'dfm-model-probe.json')
    args = parser.parse_args()
    done = threading.Event()
    records, text, outcomes = [], [], []
    probe = None
    def event(method, params):
        if method == 'item/agentMessage/delta':
            text.append(params.get('delta',''))
        if method == 'turn/completed':
            outcomes.append(params.get('turn',{}).get('status'))
            done.set()
    client = Transport(event)
    try:
        client.start()
        account = client.request('account/read',{'refreshToken':False}).get('account')
        print('Existing STEVE ChatGPT connection:',bool(account),flush=True)
        if args.account_only or not account:
            return
        if account.get('type') != 'chatgpt':
            raise ValueError('This probe requires an existing ChatGPT subscription connection; it does not use API-key billing.')
        if not args.mcp_url:
            raise ValueError('Supply --mcp-url explicitly for live model tests.')
        models = client.request('model/list',{'limit':100})['data']
        model = next((item for item in models if item.get('isDefault')),models[0])
        model_id = model['model']
        effort = 'medium' if any(e['reasoningEffort']=='medium' for e in model['supportedReasoningEfforts']) else model['defaultReasoningEffort']
        probe = FusionProbe(args.mcp_url, repair=args.repair)
        def request(request_id, method, params):
            if method != 'item/tool/call':
                client.reply(request_id,error={'code':-32601,'message':'Unsupported benchmark request'})
                return
            entry = {'tool':params.get('tool'),'arguments':params.get('arguments')}
            try:
                if len(records)>=24:
                    raise ToolError('cancelled','Benchmark tool-call limit reached. Summarize only measured evidence.')
                result = probe.call(entry['tool'],entry['arguments'])
            except Exception as error:
                result = tool_failure(error)
            entry['result'] = result
            records.append(entry)
            print('Tool:',entry['tool'],'ok:',result.get('ok'),flush=True)
            client.reply(request_id,tool_response(result))
        client.on_request = request
        trials = []
        for enabled in (False,True):
            done.clear(); records.clear(); text.clear(); outcomes.clear()
            context = probe.setup(enabled)
            params = thread_start_params(client.home)
            params['ephemeral'] = True
            params['config']['web_search'] = 'disabled'
            thread = client.request('thread/start',params)['thread']['id']
            prompt = ("Inspect the selected block for milling. Our shop's confirmed requirement is at least 4 mm of remaining material above the blind hole. "
                      "Keep all geometry unchanged. Report the measured value, whether it meets that requirement, and important unchecked manufacturing concerns. "
                      "The required process and 4 mm requirement are confirmed; no further setup questions are needed for this inspection.")
            if args.repair:
                prompt = ("Inspect and repair ONLY the selected disposable block for milling. Our confirmed shop requirement is at least 4 mm of material above its blind hole. "
                          "Preserve its 60 x 40 mm XY footprint, bottom Z=0, hole diameter 4 mm, blind depth 5 mm from the bottom, and hole center X=20,Y=20 mm. "
                          "You may grow the top of the block, using the smallest whole-millimeter total height that satisfies that requirement. "
                          "Inspect before editing, make the authorized repair, then remeasure actual geometry and report the requirement and preserved interfaces. "
                          "Only edit the selected body's component; leave all other components and documents untouched. No exports, uploads, saves or document switching. "
                          "The manufacturing requirement and repair permission are confirmed; no setup questions are needed.")
            print('Starting DFM',enabled,'model',model_id,'effort',effort,flush=True)
            turn = client.request('turn/start',{'threadId':thread,'model':model_id,'effort':effort,'input':message_input(prompt,context)})['turn']['id']
            deadline = time.monotonic()+300
            while not done.wait(1):
                if time.monotonic()>=deadline:
                    client.request('turn/interrupt',{'threadId':thread,'turnId':turn})
                    raise RuntimeError('The bounded model probe timed out; no benchmark conclusion recorded.')
            trials.append({'dfmEnabled':enabled,'model':model_id,'effort':effort,'outcome':outcomes[-1],
                           'tools':list(records),'answer':''.join(text)})
            if args.repair:
                try:
                    trials[-1]['independentVerification'] = probe.verify_repair()
                except Exception as error:
                    trials[-1]['independentVerification'] = {'passed':False,'error':str(error)}
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(trials,ensure_ascii=False,indent=2),encoding='utf-8')
            probe.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(trials,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Paired probe recorded:',args.output,flush=True)
        if any(trial['outcome'] != 'completed' or
               (args.repair and trial['independentVerification'].get('passed') is not True)
               for trial in trials):
            raise RuntimeError('A trial did not complete or failed independent geometry checks; inspect the recorded evidence.')
    finally:
        if probe:
            try:
                probe.close()
            except Exception:
                pass
        client.close()


if __name__ == '__main__':
    main()

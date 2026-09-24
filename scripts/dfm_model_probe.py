"""Opt-in real-model inspection probe against the named disposable Fusion fixture.

Uses STEVE's existing ChatGPT sign-in and app-server, with ephemeral conversations.
No credentials are copied. The development MCP is a test adapter only, never a
STEVE product dependency. Every Fusion invocation is readOnly and rejects writes.
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
    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('Use the explicitly supplied loopback development MCP endpoint.')
        self.url, self.session, self.counter = url, None, 0
        self.lock = threading.Lock()
        self.rpc('initialize', {'protocolVersion':'2024-11-05','capabilities':{},
            'clientInfo':{'name':'steve-dfm-probe','version':'1'}})
        self.rpc('notifications/initialized', {}, notification=True)
        self.package = 'steve_model_probe_' + uuid4().hex

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

    def script(self, source):
        result = self.rpc('tools/call',{'name':'fusion_mcp_execute',
            'arguments':{'featureType':'script','object':{'script':source,'readOnly':True}}})
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
''')

    def call(self, tool, arguments):
        validate_call(tool, arguments)
        if tool not in ('fusion_inspect_document','fusion_query_python','fusion_api_help','fusion_dfm_plan','fusion_dfm_check','fusion_search_docs'):
            raise ToolError('invalid_arguments','This inspection-only benchmark does not allow edits, network tools, exports or uploads.')
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
    assert module.originalBody.revisionId == module.originalRevision, 'Inspection changed the fixture'
    print(json.dumps(result))
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
        probe = FusionProbe(args.mcp_url)
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
            print('Starting DFM',enabled,'model',model_id,'effort',effort,flush=True)
            turn = client.request('turn/start',{'threadId':thread,'model':model_id,'effort':effort,'input':message_input(prompt,context)})['turn']['id']
            deadline = time.monotonic()+180
            while not done.wait(1):
                if time.monotonic()>=deadline:
                    client.request('turn/interrupt',{'threadId':thread,'turnId':turn})
                    raise RuntimeError('The bounded model probe timed out; no benchmark conclusion recorded.')
            trials.append({'dfmEnabled':enabled,'model':model_id,'effort':effort,'outcome':outcomes[-1],
                           'tools':list(records),'answer':''.join(text)})
            probe.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(trials,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Paired probe recorded:',args.output,flush=True)
    finally:
        if probe:
            try:
                probe.close()
            except Exception:
                pass
        client.close()


if __name__ == '__main__':
    main()

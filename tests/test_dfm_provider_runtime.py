"""Real Codex/provider adapters and DFM runner; scripted inference and fake CAD.

No provider credentials, paid inference, external service calls or live Fusion.
These tests verify delivery/gating, not a model's manufacturing judgment.
"""
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch

import test_fusion_bridge as cad
from test_claude import completion, FixtureStream
from steve.claude_responses import ClaudeGateway
from steve.claude_transport import ClaudeTransport
from steve.controller import Controller, CONTEXT_PREFIX
from steve.debug_log import DebugLog
from steve.grok_transport import GrokGateway, GrokTransport
from steve.ollama_transport import OllamaTransport
from steve.preferences import ProviderChoice
from steve.transport import runtime_command, RuntimeUnavailable

try:
    runtime_command()
    HAS_RUNTIME = True
except RuntimeUnavailable:
    HAS_RUNTIME = False


class Stream(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'text/event-stream'}


@unittest.skipUnless(HAS_RUNTIME, 'Fetch the bundled runtime first')
class DfmProviderRuntimeTests(unittest.TestCase):
    def test_claude_toggle_preserves_plan_and_blocks_disabled_tools(self):
        self.conversation('claude')

    def test_grok_toggle_preserves_plan_and_blocks_disabled_tools(self):
        self.conversation('grok')

    def test_ollama_toggle_preserves_plan_and_blocks_disabled_tools(self):
        self.conversation('ollama')

    def conversation(self, provider):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            home = Path(folder)
            host = cad.Host()
            tools = cad.bridge.FusionTools(host, home)
            stack.callback(tools.close)
            tools.message_context('send')
            body = Obj(entityToken='body', revisionId='r1', nativeObject=None, isValid=True, name='Fixture')
            design = Obj(findEntityByToken=lambda token: [body] if token == 'body' else [])
            tools.context = lambda: {'design': design, 'document': host.activeDocument}
            stack.enter_context(patch.object(cad.bridge.adsk.fusion, 'BRepBody', Obj(cast=lambda value: value), create=True))
            target = {'document_id': tools.document_id, 'part_token': 'body'}
            stages = [{'process': 'fdm', 'material': 'Fixture material', 'criteria': {
                'wall': {'value': 1.2, 'units': 'mm', 'basis': 'requirement', 'source': 'Explicit fixture requirement'}}}]
            check = {**target, 'stage': 0, 'title': 'Compare fixture wall', 'code':
                "def run(context):\n context['dfm'].compare('Fixture wall', 0.8, 'wall', '>=', 'mm', 'Scripted adapter fixture, not live geometry')\n context['dfm'].unknown('Manufacturing coverage', 'No printer or slicer validation')"}
            # A deliberately noncompliant model attempts all four gated tools
            # while off, then reads the original plan after re-enabling.
            schedule = [
                ('fusion_dfm_plan', {**target, 'stages': stages}), ('fusion_dfm_check', check), None,
                ('fusion_dfm_plan', target), ('fusion_dfm_check', check),
                ('rmfg_materials', {}), ('fusion_rmfg', {**target, 'action': 'prepare'}), None,
                ('fusion_dfm_plan', target), ('fusion_dfm_check', check), None,
            ]
            calls, delivered = [], []

            def next_call(params):
                index = len(calls)
                calls.append(params)
                if index >= len(schedule):
                    raise AssertionError('Unexpected inference retry or extra turn')
                entry = schedule[index]
                if entry is None:
                    return None
                name, arguments = entry
                return {'id': f'fixture_{index}', 'type': 'function',
                        'function': {'name': name, 'arguments': json.dumps(arguments)}}

            class Model:
                def create(self, **params):
                    call = next_call(params)
                    return FixtureStream([completion('Fixture response.', [call] if call else None)])
                def cancel(self):
                    pass
                def close(self):
                    pass

            def upstream(request, timeout):
                call = next_call(json.loads(request.data))
                identifier = f'response_{len(calls)}'
                item = ({'id': call['id'], 'type': 'function_call', 'call_id': call['id'],
                         **call['function'], 'status': 'completed'} if call else
                        {'id': identifier + '_message', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                         'content': [{'type': 'output_text', 'text': 'Fixture response.', 'annotations': []}]})
                response = {'id': identifier, 'object': 'response', 'status': 'completed', 'model': 'fixture',
                            'output': [item], 'usage': {'input_tokens': 20, 'output_tokens': 5, 'total_tokens': 25}}
                packets = [
                    {'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': []}},
                    {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    {'type': 'response.completed', 'response': response},
                ]
                return Stream(''.join('data: ' + json.dumps(packet) + '\n\n' for packet in packets).encode())

            catalog = {'data': [{'id': 'fixture', 'isDefault': True}], 'nextCursor': None}
            if provider == 'claude':
                stack.enter_context(patch('steve.claude_transport.ClaudeGateway', side_effect=lambda path: ClaudeGateway(path, Model)))
                stack.enter_context(patch('steve.claude_transport.account_status', return_value={'account': {'type': 'claude', 'email': 'fixture@example.com'}}))
                stack.enter_context(patch('steve.claude_transport.cli_version', return_value='fixture'))
                stack.enter_context(patch('steve.claude_transport.discover_models', return_value=catalog))
                factory = lambda notify: ClaudeTransport(notify, home=home)
            elif provider == 'grok':
                stack.enter_context(patch('steve.grok_transport.GrokGateway', side_effect=lambda auth: GrokGateway(auth, opener=upstream)))
                def factory(notify):
                    client = GrokTransport(notify, home=home)
                    client.auth.account = lambda **_: {'type': 'grok', 'email': 'fixture@example.com'}
                    client.auth.models = lambda: catalog
                    client.auth.access_token = lambda **_: 'fixture-token'
                    return client
            else:
                gateway = GrokGateway(Obj(access_token=lambda **_: 'fixture-token'), opener=upstream)
                stack.callback(gateway.close)
                # Ollama uses /v1/responses; only redirect its endpoint, preserving
                # the actual transport's model/context preparation and RPC path.
                gateway.path += '/v1'
                stack.enter_context(patch('steve.ollama_transport.BASE_URL', gateway.base_url))
                api = Mock()
                api.request.return_value = {'version': '0.13.3'}
                api.models.return_value = catalog
                api.prepare.return_value = {'model': 'fixture', 'context': 32768, 'vision': False}
                factory = lambda notify: OllamaTransport(notify, home=home, api=api)

            ProviderChoice(home).save(provider)
            controller = Controller(lambda _: None, debug_log=DebugLog(home), fusion_tools=tools,
                                    **{provider + '_factory': factory})
            stack.callback(controller._worker.join, 5)
            stack.callback(controller.close)
            # Spy on actual controller replies, after runner execution/gating.
            def wait_for(predicate, timeout=25):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    host.pump()
                    self.assertFalse(controller.state['error'], controller.state['error'])
                    if predicate():
                        return
                    time.sleep(.01)
                self.fail(f'Workflow did not complete; {len(calls)} inference calls; {controller.state["status"]}')

            controller.dispatch('connect')
            wait_for(lambda: bool(controller.state['models']))
            reply = controller.client.reply
            def record_reply(request_id, result=None, error=None):
                if result and 'contentItems' in result:
                    delivered.append(json.loads(result['contentItems'][0]['text']))
                return reply(request_id, result, error)
            controller.client.reply = record_reply
            supplier = stack.enter_context(patch.object(controller.rmfg_service, 'submit'))
            submit = stack.enter_context(patch.object(tools, 'submit', wraps=tools.submit))
            thread = None
            for enabled, end in ((True, 3), (False, 8), (True, 11)):
                controller.dispatch('dfm', {'enabled': enabled})
                wait_for(lambda: controller.state['dfmEnabled'] == enabled)
                controller.dispatch('send', {'text': 'Inspect the fixture without edits', 'fusionContext': {
                    'document_id': tools.document_id, 'name': 'Fixture', 'task_key': 'private-fixture-key'}})
                wait_for(lambda: len(calls) == end and not controller.state['busy'] and not controller._send_queued)
                thread = thread or controller.thread_id
                self.assertEqual(controller.thread_id, thread)
                self.assertEqual(controller.state['taskDocument']['id'], tools.document_id)

            self.assertEqual(len(delivered), 8)
            self.assertEqual([row.get('errorCode') for row in delivered[2:6]], ['dfm_disabled'] * 4)
            self.assertTrue(all(not row['executionStarted'] for row in delivered[2:6]))
            self.assertTrue(all('ordinary Fusion tools' in row['recovery'] for row in delivered[2:6]))
            supplier.assert_not_called()
            self.assertEqual(submit.call_count, 4)
            self.assertEqual(delivered[0]['plan'], delivered[6]['plan'])
            for row in (delivered[1], delivered[7]):
                self.assertTrue(row['ok'])
                self.assertEqual(row['executionMode'], 'query')
                self.assertEqual(row['dfm']['status'], 'concerns')
                self.assertEqual([f['status'] for f in row['dfm']['findings']], ['concern', 'unknown'])
                self.assertEqual(row['dfm']['planHash'], delivered[0]['reportBinding']['planHash'])
            self.assertEqual(host.executions, 0)
            self.assertEqual(body.revisionId, 'r1')
            for index, enabled in ((0, True), (3, False), (8, True)):
                request = calls[index]
                messages = request.get('messages', request.get('input', []))
                latest = next(m for m in reversed(messages) if m.get('role') == 'user')
                content = latest['content']
                text = content if isinstance(content, str) else '\n'.join(p.get('text', '') for p in content)
                public = json.JSONDecoder().raw_decode(text.split(CONTEXT_PREFIX)[-1])[0]
                self.assertEqual(public['dfmEnabled'], enabled)
                self.assertEqual(public['document_id'], tools.document_id)
                self.assertNotIn('task_key', public)
                names = {t.get('name') or t.get('function', {}).get('name') for t in request['tools']}
                self.assertTrue({'fusion_dfm_plan', 'fusion_dfm_check', 'rmfg_materials', 'fusion_rmfg'} <= names)


if __name__ == '__main__':
    unittest.main()

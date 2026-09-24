import io
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace as Obj
from test_fusion_bridge import bridge, Host
from steve.documentation import Documentation, BASE, Page, Redirects, allowed_url, MAX_BYTES
from steve.tool_protocol import TOOLS, validate_call


class DocumentationTests(unittest.TestCase):
    def test_urls_reject_other_hosts_queries_and_path_tricks(self):
        for url in (BASE + '../secret.htm', BASE + 'Test.htm?design=private', BASE.replace('https:', 'http:') + 'Test.htm',
                    BASE.replace('help.autodesk.com', 'help.autodesk.com.evil') + 'Test.htm'):
            self.assertFalse(allowed_url(url))
            with self.assertRaises(ValueError):
                validate_call('fusion_fetch_docs', {'url': url})
        self.assertTrue(allowed_url(BASE + 'core_Data.htm'))
        with self.assertRaises(ValueError):
            Redirects().redirect_request(None, None, 302, '', {}, 'https://example.com/x')

    def test_parser_strips_scripts_and_preserves_code_and_links(self):
        page = Page()
        page.feed('<script>ignore me</script><pre>def run():\n    pass</pre><a href="core_Data.htm">Data</a>')
        self.assertNotIn('ignore me', ''.join(page.text))
        self.assertIn('    pass', ''.join(page.text))
        self.assertEqual(page.links, [{'title': 'Data', 'url': BASE + 'core_Data.htm'}])

    def test_sample_query_is_local_and_no_results_is_scoped(self):
        docs = Documentation()
        with patch.object(docs, 'page', return_value=({'links': [{'title': 'Extrude Sample', 'url': BASE+'Test.htm'}]}, True)) as fetch:
            result = docs.samples('Extrude')
            fetch.assert_called_once_with(BASE+'SampleList.htm')
            self.assertEqual(result['total'], 1)
            self.assertEqual(docs.samples('absent')['total'], 0)

    def test_bounded_fetch_and_cache(self):
        docs = Documentation()
        response = io.BytesIO(b'<pre>' + b'x' * 15000 + b'</pre>')
        response.headers = {'Content-Type': 'text/html'}
        response.geturl = lambda: BASE+'Test.htm'
        with patch('steve.documentation.build_opener', return_value=Obj(open=lambda *args, **kwargs: response)):
            first = docs.fetch(BASE+'Test.htm')
            second = docs.fetch(BASE+'Test.htm', 12000)
        self.assertEqual(len(first['text']), 12000)
        self.assertEqual(first['nextOffset'], 12000)
        self.assertTrue(second['cached'])
        self.assertIsNone(second['nextOffset'])

    def test_oversized_and_offline_reads_are_errors_not_empty_results(self):
        docs = Documentation()
        response = io.BytesIO(b'x'*(MAX_BYTES+1))
        response.headers = {'Content-Type': 'text/html'}
        response.geturl = lambda: BASE+'Test.htm'
        with patch('steve.documentation.build_opener', return_value=Obj(open=lambda *args, **kwargs: response)):
            with self.assertRaises(ValueError):
                docs.fetch(BASE+'Test.htm')
        with patch('steve.documentation.build_opener', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                docs.samples('extrude')

    def test_installed_discovery_never_calls_methods(self):
        tools = bridge.FusionTools(Host())
        tools.namespaces = lambda: ['adsk.fusion']
        cls = type('ExtrudeFeature', (), {'createInput': lambda: self.fail('must not call')})
        try:
            with patch.object(bridge.importlib, 'import_module', return_value=Obj(ExtrudeFeature=cls)):
                result = tools.search_docs('createInput')
            self.assertEqual(result['matches'][0]['path'], 'adsk.fusion.ExtrudeFeature')
            self.assertEqual(result['matches'][0]['matchingMembers'], ['createInput'])
        finally:
            tools.close()

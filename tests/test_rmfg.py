import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve.rmfg import RMFGAuth, RMFGClient, RMFGError
from steve.secure_store import SecureStore


class Store:
    value = None
    @contextmanager
    def locked(self):
        yield
    def read(self):
        return copy.deepcopy(self.value)
    def write(self, value):
        self.value = copy.deepcopy(value)


class RMFGTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.now = 100
        self.calls = []
        self.responses = []
        def transport(method, path, body=None, token=None, content_type=None, key=None):
            self.calls.append((method,path,body,token,content_type,key))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        self.transport = transport
        self.auth = RMFGAuth(self.store, transport=transport, clock=lambda: self.now)

    def token(self):
        return {'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh',
                'token_type': 'Bearer', 'expires_in': 900, 'scope': 'designs dfm'}

    def connected(self):
        self.store.write({'state':'connected','tokens':{**self.token(),'expires_at':self.now+100}})

    def test_device_flow_requests_dfm_and_checkout_without_payments_and_respects_poll_interval(self):
        self.responses.append({'device_code':'private-code','user_code':'PUBLIC-CODE',
            'verification_uri_complete':'https://www.rmfg.com/connect?code=PUBLIC-CODE',
            'interval':5,'expires_in':600})
        attempt = self.auth.begin()
        self.assertEqual(self.calls[0][2]['scope'], 'designs dfm quotes carts')
        self.assertEqual(self.auth.poll(attempt), 'pending')
        self.assertEqual(len(self.calls), 1)
        self.now += 5
        self.responses.append(RMFGError('Pending', code='authorization_pending', status=400))
        self.assertEqual(self.auth.poll(attempt), 'pending')
        self.now += 5
        self.responses.append(self.token())
        self.assertEqual(self.auth.poll(attempt), 'connected')
        self.assertEqual(self.auth.access_token(), 'fixture-access')
        self.assertNotIn('token', json.dumps(self.auth.status()))
        self.assertNotIn('private-code', repr(attempt))

    def test_refresh_persists_consumption_before_network_and_rotates(self):
        self.connected()
        self.now += 100
        def transport(*args, **kwargs):
            self.assertEqual(self.store.value['state'], 'refreshing')
            return {**self.token(), 'refresh_token':'replacement'}
        self.auth.transport = transport
        self.auth.access_token()
        self.assertEqual(self.store.value['tokens']['refresh_token'], 'replacement')

    def test_ambiguous_refresh_requires_reconnect_without_replaying_token(self):
        self.connected()
        self.now += 100
        self.responses.append(RMFGError('Network unavailable'))
        with self.assertRaises(RMFGError):
            self.auth.access_token()
        with self.assertRaises(RMFGError):
            self.auth.access_token()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.value['state'], 'refreshing')

    def test_cancel_cannot_erase_a_newer_login_and_slow_down_is_respected(self):
        self.responses.append({'device_code':'private-code','user_code':'CODE',
            'verification_uri_complete':'https://www.rmfg.com/connect?code=CODE','interval':5,'expires_in':600})
        attempt=self.auth.begin()
        self.now+=5
        self.responses.append(RMFGError('Pending',code='slow_down',status=400))
        self.assertEqual(self.auth.poll(attempt),'pending')
        self.assertEqual(attempt.interval,10)
        self.assertEqual(attempt.next_poll,self.now+10)
        self.store.write({'state':'authorizing','generation':'newer'})
        self.auth.cancel(attempt)
        self.assertEqual(self.store.value['generation'],'newer')

    @unittest.skipUnless(sys.platform == 'darwin', 'Native macOS Keychain')
    def test_native_macos_keychain_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SecureStore(folder,'rmfg-test')
            with store.locked():
                self.assertIsNone(store.read())
                store.write({'fixture':'private-fixture-token'})
                self.assertEqual(store.read(),{'fixture':'private-fixture-token'})
                store.write({'state':'disconnected'})
            self.assertFalse(list(Path(folder).glob('*.json')))

    @unittest.skipUnless(os.name == 'nt', 'Native Windows lock')
    def test_native_lock_blocks_other_store_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second=SecureStore(folder,'rmfg-test'), SecureStore(folder,'rmfg-test')
            with first.locked():
                with self.assertRaises(RuntimeError):
                    with second.locked():
                        self.fail('Second instance entered the credential lock')
            with second.locked():
                pass

    def test_denied_and_untrusted_login_links_never_become_connected(self):
        self.responses.append({'device_code':'x','user_code':'CODE','verification_uri_complete':'https://example.com/login','interval':5,'expires_in':600})
        with self.assertRaises(RMFGError):
            self.auth.begin()
        self.assertNotEqual(self.auth.status()['state'], 'connected')

    def test_inadequate_scopes_and_invalid_lifetimes_are_rejected(self):
        for payload in ({**self.token(),'scope':'designs'}, {**self.token(),'expires_in':float('nan')}):
            with self.assertRaises(RMFGError):
                self.auth.validate_tokens(payload)

    def test_old_dfm_connection_remains_usable_and_checkout_requires_new_scopes(self):
        self.connected()
        self.assertEqual(self.auth.access_token(), 'fixture-access')
        self.assertFalse(self.auth.checkout_available())
        with self.assertRaisesRegex(RMFGError, 'enable quotes and checkout'):
            self.auth.access_token({'quotes', 'carts'})
        self.store.value['tokens']['scope'] = 'designs dfm quotes carts'
        self.assertTrue(self.auth.checkout_available())
        self.assertEqual(self.auth.access_token({'quotes', 'carts'}), 'fixture-access')

    def test_checkout_transport_uses_exact_items_and_keys_without_payment(self):
        client = RMFGClient(lambda: 'fixture', self.transport)
        items = [{'design_id': 'design-1', 'quantity': 3, 'configuration': {'parts': [{'part_id': 'p', 'material_id': 'm'}]}}]
        self.responses.extend([{'id': 'q'}, {'id': 'q'}, {'id': 'c'}, {'id': 'c'}])
        client.create_quote(items, 'quote-key')
        client.quote('q')
        client.create_cart(items, 'cart-key')
        client.cart('c')
        self.assertEqual([call[1] for call in self.calls], ['/v1/quotes', '/v1/quotes/q', '/v1/carts', '/v1/carts/c'])
        self.assertEqual(self.calls[0][2], self.calls[2][2])
        self.assertEqual(self.calls[2][-1], 'cart-key')

    def test_dfm_request_cannot_accept_risks_or_order_parts(self):
        client = RMFGClient(lambda:'token', self.transport)
        self.responses.append({'id':'report-1','status':'requires_input'})
        result = client.create_dfm('design-1', [{'part_id':'part-1','material_id':'stock-1'}], 'operation-1')
        self.assertEqual(result['status'], 'requires_input')
        payload = self.calls[0][2]
        self.assertFalse(payload['generate_production_files'])
        self.assertNotIn('accepted_risks', payload['configuration'])
        with self.assertRaises(ValueError):
            client.create_dfm('design-1', [{'part_id':'part-1','accepted_risks':['risk']}], 'operation-2')

    def test_identical_upload_retries_use_identical_body_and_key(self):
        client = RMFGClient(lambda:'token', self.transport)
        self.responses.extend([{'id':'d1'}, {'id':'d1'}])
        for _ in range(2):
            client.analyze(b'ISO-10303-21; fixture', 'operation-1')
        self.assertEqual(self.calls[0], self.calls[1])

    def test_native_windows_store_is_encrypted_and_roundtrips(self):
        if os.name != 'nt':
            self.skipTest('Native Windows secure storage test')
        with tempfile.TemporaryDirectory() as folder:
            store = SecureStore(folder, 'test-rmfg')
            with store.locked():
                store.write({'private': 'fixture-token'})
                self.assertEqual(store.read(), {'private':'fixture-token'})
            self.assertNotIn(b'fixture-token', (Path(folder)/'test-rmfg.dpapi').read_bytes())


if __name__ == '__main__':
    unittest.main()

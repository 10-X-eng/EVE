"""Supplier quote/cart contracts with fake HTTP results; never creates a live cart."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as Obj
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve.rmfg import RMFGError
from steve.rmfg_checkout import RMFGCheckout
from steve.rmfg_jobs import RMFGJobs
from steve.rmfg_service import RMFGService
from steve.tool_protocol import validate_call


class Supplier:
    def __init__(self):
        self.writes = []
        self.fail_quote = self.fail_cart = False
        self.quote_result = self.cart_result = None

    def create_quote(self, items, key):
        self.writes.append(('quote', copy.deepcopy(items), key))
        self.quote_result = {'id': 'quote-1', 'status': 'ready', 'currency': 'usd',
            'amount_subtotal_cents': 4500, 'requirements': [],
            'expires_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'items': [{**copy.deepcopy(item), 'status': 'ready', 'dfm': {
                'design_id': item['design_id'], 'status': 'ready',
                'configuration': copy.deepcopy(item['configuration']), 'requirements': []}}
                for item in items]}
        if self.fail_quote:
            raise RMFGError('Interrupted quote')
        return copy.deepcopy(self.quote_result)

    def quote(self, identifier):
        return copy.deepcopy(self.quote_result)

    def create_cart(self, items, key):
        self.writes.append(('cart', copy.deepcopy(items), key))
        self.cart_result = {'id': 'cart-1', 'status': 'open', 'items': copy.deepcopy(items),
            'cart_url': 'https://www.rmfg.com/checkout/private-fixture-token',
            'quote': copy.deepcopy(self.quote_result)}
        if self.fail_cart:
            raise RMFGError('Interrupted checkout')
        return copy.deepcopy(self.cart_result)

    def cart(self, identifier):
        return copy.deepcopy(self.cart_result)


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = Obj(connection_id=lambda: 'account-1', access_token=lambda *args: 'fixture-token')
        self.jobs = RMFGJobs(self.temp.name, self.auth)
        self.supplier = Supplier()
        self.checkout = RMFGCheckout(self.jobs, self.supplier)
        self.entries = []
        for index, quantity in enumerate((2, 7)):
            job = self.jobs.prepare({'step': b'ISO-10303-21; fixture', 'body': 'Bracket',
                'documentKey': 'doc', 'partToken': 'body-'+str(index), 'revision': 'r1'})
            job.update(designId='design-'+str(index), configuration=json.dumps([
                {'part_id': 'part-'+str(index), 'material_id': 'aluminum-2mm'}]))
            self.jobs._write(job)
            self.entries.append({'job_id': job['id'], 'quantity': quantity})

    def prepare(self):
        return self.checkout.prepare(self.entries)['id']

    def test_multiple_parts_quote_checkout_reopen_without_duplicate_write_or_private_link(self):
        receipt = self.prepare()
        self.assertEqual(receipt, self.checkout.prepare(list(reversed(self.entries)))['id'])
        result = self.checkout.quote(receipt)
        self.assertTrue(result['canCheckout'])
        self.assertEqual(sorted(row['quantity'] for row in result['items']), [2, 7])
        result = self.checkout.create(receipt)
        self.assertTrue(result['checkoutAvailable'])
        reloaded = RMFGCheckout(RMFGJobs(self.temp.name, self.auth), self.supplier)
        self.assertEqual(reloaded.create(receipt), result)
        self.assertEqual(len(self.supplier.writes), 2)
        self.assertEqual(self.supplier.writes[0][1], self.supplier.writes[1][1])
        self.assertEqual(reloaded.open_url(receipt), self.supplier.cart_result['cart_url'])
        self.assertNotIn('private-fixture-token', json.dumps(reloaded.status(receipt)))
        self.assertNotIn('private-fixture-token', (self.jobs.folder/(receipt+'.json')).read_text())

    def test_interrupted_writes_reuse_receipt_exact_payload_and_key(self):
        receipt = self.prepare()
        self.supplier.fail_quote = True
        with self.assertRaises(RMFGError):
            self.checkout.quote(receipt)
        self.assertEqual(self.checkout.status(receipt)['status'], 'unconfirmed')
        self.supplier.fail_quote = False
        self.checkout.quote(receipt)
        self.assertEqual(self.supplier.writes[0], self.supplier.writes[1])
        self.supplier.fail_cart = True
        with self.assertRaises(RMFGError):
            self.checkout.create(receipt)
        self.supplier.fail_cart = False
        self.supplier.quote_result['expires_at'] = '2001-01-01T00:00:00Z'
        self.checkout.create(receipt)
        self.assertEqual(self.supplier.writes[-2], self.supplier.writes[-1])

    def test_pending_blocked_and_expired_quotes_never_create_cart(self):
        receipt = self.prepare()
        self.checkout.quote(receipt)
        for status in ('processing', 'requires_input', 'blocked', 'failed', 'expired'):
            self.supplier.quote_result['status'] = status
            self.assertFalse(self.checkout.create(receipt)['canCheckout'])
        self.supplier.quote_result['status'] = 'ready'
        self.supplier.quote_result['expires_at'] = '2001-01-01T00:00:00Z'
        self.assertFalse(self.checkout.create(receipt)['canCheckout'])
        self.assertTrue(all(row[0] != 'cart' for row in self.supplier.writes))
        self.checkout.quote(receipt)
        self.assertNotEqual(self.supplier.writes[0][2], self.supplier.writes[-1][2])

    def test_foreign_quote_material_quantity_and_unrequested_operations_block_checkout(self):
        receipt = self.prepare()
        self.checkout.quote(receipt)
        original = copy.deepcopy(self.supplier.quote_result)
        for mutation in ('id', 'quantity', 'material', 'risk', 'operation'):
            self.supplier.quote_result = copy.deepcopy(original)
            row = self.supplier.quote_result['items'][0]
            if mutation == 'id':
                self.supplier.quote_result['id'] = 'foreign-quote'
            elif mutation == 'quantity':
                row['quantity'] = 999
            elif mutation == 'material':
                row['dfm']['configuration']['parts'][0]['material_id'] = 'steel'
            elif mutation == 'risk':
                row['dfm']['configuration']['accepted_risks'] = ['sharp-edge']
            else:
                row['dfm']['configuration']['parts'][0]['taps'] = [{'id': 'tap'}]
            with self.subTest(mutation=mutation), self.assertRaises(RMFGError):
                self.checkout.create(receipt)
        self.assertEqual(len(self.supplier.writes), 1)

    def test_supplier_default_fields_are_compared_and_wrong_cart_or_url_rejected(self):
        receipt = self.prepare()
        self.checkout.quote(receipt)
        for row in self.supplier.quote_result['items']:
            row['dfm']['configuration'].update(defaults={'material_id': 'aluminum-2mm', 'finish_id': None}, accepted_risks=[], assembly_operations=[])
            row['dfm']['configuration']['parts'][0].update(taps=[], finish_id=None)
            row['dfm']['configuration']['parts'][0].pop('material_id')
        self.checkout.create(receipt)
        for url in ('http://rmfg.com/cart', 'https://rmfg.com.attacker.test/cart',
                    'https://user:password@rmfg.com/cart', 'https://api.rmfg.com/cart'):
            self.supplier.cart_result['cart_url'] = url
            with self.assertRaises(RMFGError):
                self.checkout.open_url(receipt)
        self.supplier.cart_result['items'][0]['quantity'] = 500
        with self.assertRaises(RMFGError):
            self.checkout.status(receipt)

    def test_changed_quantity_uses_new_quote_and_foreign_account_cannot_read(self):
        receipt = self.prepare()
        self.entries[0]['quantity'] += 1
        self.assertNotEqual(self.prepare(), receipt)
        self.auth.connection_id = lambda: 'other-account'
        with self.assertRaises(RMFGError):
            self.checkout.read(receipt)

    def test_findings_pagination_filters_private_fields(self):
        receipt = self.prepare()
        self.checkout.quote(receipt)
        self.supplier.quote_result.update(status='requires_input', requirements=[
            {'code': 'required', 'message': str(index), 'allowed_values_url': 'https://private.invalid'} for index in range(23)])
        self.supplier.quote_result['requirements'].append({'code': 'internal', 'customer_visible': False})
        first = self.checkout.status(receipt)
        self.assertEqual(first['nextOffset'], 20)
        self.assertEqual(len(first['findings']), 20)
        self.assertEqual(len(self.checkout.status(receipt, 20)['findings']), 3)
        self.assertNotIn('private.invalid', json.dumps(first))

    def test_service_checks_every_part_before_quote_and_stale_parts_never_checkout(self):
        observed = []
        fresh = [True]
        def inspect(tool, args, done, cancelled):
            observed.append(args)
            done({'ok': True, 'snapshotMatches': fresh[0]})
        service = RMFGService(self.temp.name, self.auth, lambda state: None, Obj(submit=inspect))
        self.addCleanup(service.close)
        service.checkout = self.checkout
        def run(arguments):
            done = threading.Event(); results = []
            service.submit('rmfg_checkout', arguments, lambda result: (results.append(result), done.set()), lambda: False)
            self.assertTrue(done.wait(3))
            return results[0]
        result = run({'action': 'quote', 'document_id': 'doc', 'items': self.entries})
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(observed), 2)
        self.assertEqual({row['_binding']['partToken'] for row in observed}, {'body-0', 'body-1'})
        fresh[0] = False
        result = run({'action': 'create', 'document_id': 'doc', 'checkout_id': result['checkoutId']})
        self.assertFalse(result['ok'])
        self.assertTrue(all(row[0] != 'cart' for row in self.supplier.writes))

    def test_tool_contract_requires_saved_jobs_quantities_and_action_specific_fields(self):
        valid = {'document_id': 'doc', 'action': 'quote', 'items': self.entries}
        validate_call('rmfg_checkout', valid)
        for invalid in ({**valid, 'items': self.entries*2}, {**valid, 'checkout_id': 'another'},
                        {**valid, 'items': [{'job_id': 'job', 'quantity': True}]},
                        {**valid, 'items': [{'job_id': 'job', 'quantity': 0}]},
                        {**valid, 'action': 'create'}, {**valid, 'accepted_risks': ['any']},
                        {**valid, 'payment': {}}, {**valid, 'action': 'pay'}):
            with self.assertRaises(ValueError):
                validate_call('rmfg_checkout', invalid)


if __name__ == '__main__':
    unittest.main()

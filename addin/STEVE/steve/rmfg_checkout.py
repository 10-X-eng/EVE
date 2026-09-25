"""Durable quotes and multi-part hosted carts using saved, scoped RMFG jobs."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4
from urllib.parse import urlsplit

from .rmfg import RMFGError, browser_url, identifier
from .rmfg_jobs import fields


def material_configuration(config):
    """Compare effective supplier defaults without accepting extra operations."""
    if not isinstance(config, dict):
        raise RMFGError('RMFG returned invalid manufacturing settings.')
    if any(value for key, value in config.items() if key not in ('parts', 'defaults')):
        raise RMFGError('RMFG returned unrequested manufacturing settings. Review the configuration.')
    defaults = config.get('defaults') or {}
    if not isinstance(defaults, dict) or any(value for key, value in defaults.items() if key != 'material_id'):
        raise RMFGError('RMFG returned unrequested material defaults.')
    result = []
    for part in config.get('parts', []):
        if any(value for key, value in part.items() if key not in ('part_id', 'material_id')):
            raise RMFGError('RMFG returned unrequested part operations. Review the configuration.')
        result.append({'part_id': identifier(part.get('part_id')), 'material_id': identifier(part.get('material_id', defaults.get('material_id')))})
    return {'parts': sorted(result, key=lambda row: row['part_id'])}


def validate_quote(quote, items):
    actual = quote.get('items', [])
    if len(actual) != len(items):
        raise RMFGError('RMFG quote does not match the requested parts.')
    for row, expected in zip(actual, items):
        report = row.get('dfm', {})
        if (row.get('design_id') != expected['design_id'] or row.get('quantity') != expected['quantity']
                or report.get('design_id') != expected['design_id']
                or material_configuration(report.get('configuration')) != expected['configuration']):
            raise RMFGError('RMFG quote does not match the selected parts, quantities or materials.')


def expired(quote):
    expiry = quote.get('expires_at')
    if quote.get('status') == 'expired':
        return True
    if not expiry:
        return False
    try:
        value = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
        return value.tzinfo is None or value <= datetime.now(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise RMFGError('RMFG returned an invalid quote expiry.') from None


def ready(quote):
    return (quote.get('status') == 'ready' and not expired(quote) and not quote.get('requirements')
            and all(row.get('status') == 'ready' and not row.get('requirements')
                    and row.get('dfm', {}).get('status') == 'ready'
                    and not row.get('dfm', {}).get('requirements') for row in quote.get('items', [])))


class RMFGCheckout:
    def __init__(self, jobs, client):
        self.jobs, self.client = jobs, client

    def prepare(self, entries):
        items, references = [], []
        for entry in sorted(entries, key=lambda row: row['job_id']):
            job = self.jobs.read(entry['job_id'])
            if not job.get('designId') or not job.get('configuration'):
                raise RMFGError('Check each saved part with its intended material before requesting a quote.')
            items.append({'design_id': job['designId'], 'quantity': entry['quantity'],
                          'configuration': material_configuration({'parts': json.loads(job['configuration'])})})
            references.append({'job_id': job['id'], 'binding': job['binding']})
        if len({item['design_id'] for item in items}) != len(items):
            raise RMFGError('Include each design once; use quantity for repeated parts.')
        connection = self.jobs.auth.connection_id()
        fingerprint = json.dumps([connection, references, items], sort_keys=True, separators=(',', ':'))
        checkout_id = 'checkout_' + hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
        with self.jobs.guard.locked():
            if (self.jobs.folder / (checkout_id+'.json')).exists():
                return self.read(checkout_id)
            record = {'id': checkout_id, 'kind': 'checkout', 'connection': connection,
                      'items': items, 'references': references, 'quoteKey': uuid4().hex}
            self.jobs._write(record)
            return record

    def read(self, checkout_id):
        record = self.jobs.read(checkout_id)
        if record.get('kind') != 'checkout':
            raise RMFGError('Use the checkoutId returned by rmfg_checkout.')
        return record

    def quote(self, checkout_id):
        with self.jobs.guard.locked():
            record = self.read(checkout_id)
            quote = self.client.quote(record['quoteId']) if record.get('quoteId') else None
            if quote is not None and quote.get('id') != record['quoteId']:
                raise RMFGError('RMFG returned a different quote.')
            if quote is not None and expired(quote) and not record.get('cartId'):
                record.pop('quoteId')
                record['quoteKey'] = uuid4().hex
                self.jobs._write(record)
                quote = None
            if quote is None:
                quote = self.client.create_quote(record['items'], record['quoteKey'])
                record['quoteId'] = identifier(quote.get('id'))
                self.jobs._write(record)
            return self.summary(record, quote)

    def status(self, checkout_id, offset=0):
        with self.jobs.guard.locked():
            record = self.read(checkout_id)
            if not record.get('quoteId'):
                return {'ok': True, 'checkoutId': checkout_id, 'status': 'unconfirmed',
                        'recovery': 'Retry quote with this checkout_id to reuse the saved request.'}
            quote = self.client.quote(record['quoteId'])
            if quote.get('id') != record['quoteId']:
                raise RMFGError('RMFG returned a different quote.')
            result = self.summary(record, quote, offset)
            if record.get('cartId'):
                cart = self._cart(record)
                result.update(cartStatus=cart['status'], checkoutAvailable=cart['status'] == 'open',
                              cartQuoteStatus=cart.get('quote', {}).get('status'))
            elif record.get('cartKey'):
                result['recovery'] = 'Checkout outcome is uncertain. Retry create with this checkout_id; the exact cart request and key are saved.'
            return result

    def create(self, checkout_id):
        with self.jobs.guard.locked():
            record = self.read(checkout_id)
            if record.get('cartId'):
                cart = self._cart(record)
            else:
                if not record.get('quoteId'):
                    raise RMFGError('Request a quote before creating checkout.')
                if not record.get('cartKey'):
                    quote = self.client.quote(record['quoteId'])
                    if quote.get('id') != record['quoteId']:
                        raise RMFGError('RMFG returned a different quote.')
                    validate_quote(quote, record['items'])
                    if not ready(quote):
                        return self.summary(record, quote)
                # An uncertain create retries its original request, even if its
                # source quote expired after the supplier accepted the cart.
                record['cartKey'] = record.get('cartKey') or uuid4().hex
                self.jobs._write(record)
                cart = self.client.create_cart(record['items'], record['cartKey'])
                record['cartId'] = identifier(cart.get('id'))
                self.jobs._write(record)
                self._validate_cart(record, cart)
            return {'ok': True, 'checkoutId': checkout_id, 'cartStatus': cart['status'],
                    'checkoutAvailable': cart['status'] == 'open',
                    'cartQuoteStatus': cart.get('quote', {}).get('status'),
                    'note': 'The RMFG checkout button lets the customer review delivery, final pricing and pay. No payment was submitted.'}

    def _validate_cart(self, record, cart):
        if cart.get('id') != record['cartId'] or cart.get('status') not in ('open', 'checked_out', 'expired'):
            raise RMFGError('RMFG returned an unexpected cart.')
        items = cart.get('items', [])
        if len(items) != len(record['items']):
            raise RMFGError('RMFG checkout contains different parts.')
        for row, expected in zip(items, record['items']):
            if (row.get('design_id') != expected['design_id'] or row.get('quantity') != expected['quantity']
                    or material_configuration(row.get('configuration')) != expected['configuration']):
                raise RMFGError('RMFG checkout contains different quantities or manufacturing settings.')

    def _cart(self, record):
        cart = self.client.cart(record['cartId'])
        self._validate_cart(record, cart)
        return cart

    def open_url(self, checkout_id):
        with self.jobs.guard.locked():
            record = self.read(checkout_id)
            if not record.get('cartId'):
                raise RMFGError('Ask STEVE to create checkout for the quoted parts first.')
            cart = self._cart(record)
            if cart['status'] != 'open':
                raise RMFGError('This checkout is already paid or expired. Ask STEVE to check its status.')
            url = browser_url(cart.get('cart_url'))
            if urlsplit(url).hostname not in ('rmfg.com', 'www.rmfg.com'):
                raise RMFGError('RMFG returned an invalid checkout website.')
            return url

    @staticmethod
    def summary(record, quote, offset=0):
        # Persist only IDs and request payloads. Private checkout links never enter tools or logs.
        if quote.get('status') == 'ready':
            validate_quote(quote, record['items'])
        findings = []
        def collect(rows):
            for row in rows:
                if row.get('customer_visible', True):
                    findings.append(fields(row, 'code message severity part_id field'))
        collect(quote.get('requirements', []))
        for item in quote.get('items', []):
            collect(item.get('requirements', []))
            dfm = item.get('dfm', {})
            collect(dfm.get('requirements', []))
            collect(dfm.get('assembly_issues', []))
            for part in dfm.get('parts', []):
                collect(part.get('issues', []))
        return {'ok': True, 'checkoutId': record['id'], 'status': 'expired' if expired(quote) else quote.get('status'),
                **fields(quote, 'currency amount_subtotal_cents amount_shipping_cents amount_tax_cents expires_at'),
                'canCheckout': ready(quote), 'findings': findings[offset:offset+20],
                'nextOffset': offset+20 if len(findings)>offset+20 else None,
                'items': [{'jobId': ref['job_id'], 'quantity': item['quantity']} for ref, item in zip(record['references'], record['items'])],
                'note': 'Prices are in USD cents. Shipping, tax and final pricing are reviewed on RMFG checkout.'}

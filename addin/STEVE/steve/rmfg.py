"""RMFG device OAuth and DFM-only REST transport. Call from workers, not Fusion UI."""
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

ORIGIN = 'https://api.rmfg.com'
CLIENT_ID = 'rmfg-agent'
SCOPES = 'designs dfm'
MAX_STEP_BYTES = 50*1024*1024


class RMFGError(RuntimeError):
    def __init__(self, message, *, code='', status=None, retry_after=None):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(method, path, body=None, token=None, content_type=None, key=None):
    headers = {'Accept': 'application/json'}
    if not path.startswith('/v1/') or path.startswith('//'):
        raise ValueError('Use an RMFG API path.')
    if isinstance(body, dict):
        body = (urlencode(body).encode('ascii') if content_type == 'application/x-www-form-urlencoded'
                else json.dumps(body, sort_keys=True, allow_nan=False, separators=(',',':')).encode('utf-8'))
        content_type = content_type or 'application/json'
    if content_type:
        headers['Content-Type'] = content_type
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if key:
        headers['Idempotency-Key'] = identifier(key)
    try:
        try:
            response = build_opener(NoRedirects()).open(Request(ORIGIN+path, data=body, headers=headers, method=method), timeout=30)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(2*1024*1024+1)
            if len(raw) > 2*1024*1024:
                raise ValueError('Response too large')
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError('Invalid response')
            if not 200 <= response.status < 300:
                code = payload.get('error')
                code = code if isinstance(code,str) and re.fullmatch(r'[a-z_]{1,60}',code) else ''
                guidance = {400:'Check the observed part/material IDs and supported request fields.',
                    401:'Reconnect RMFG in STEVE.', 403:'Check the connection permissions in RMFG, then reconnect.',
                    404:'This supplier resource is unavailable. Check the saved job ID and account.',
                    409:'This write conflicts with an earlier request. Keep the existing job; do not change its retry payload.',
                    429:'RMFG is rate-limiting requests. Wait before checking this same job again.'}.get(response.status,
                    'The outcome may be uncertain. Keep the same job and operation key for an identical retry.')
                raise RMFGError('RMFG request failed (HTTP ' + str(response.status) + '). ' + guidance,
                                code=code, status=response.status, retry_after=response.headers.get('Retry-After'))
            return payload
    except RMFGError:
        raise
    except (OSError, ValueError):
        raise RMFGError('RMFG did not return a valid response. Keep the same operation key for an identical retry.') from None


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,255}',value):
        raise ValueError('Use an identifier returned by RMFG, not a URL or local path.')
    return value


def browser_url(value):
    try:
        parsed = urlsplit(value)
        if (not isinstance(value,str) or len(value)>8192 or any(ord(c)<32 or ord(c)==127 for c in value) or parsed.scheme!='https'
                or parsed.hostname not in ('rmfg.com','www.rmfg.com','api.rmfg.com')
                or parsed.username or parsed.password or parsed.port not in (None,443)):
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise RMFGError('RMFG returned an invalid approval link.') from None


def secret(value):
    if not isinstance(value,str) or not value or len(value)>16384 or any(c.isspace() for c in value):
        raise RMFGError('RMFG returned incomplete credentials. Reconnect.')
    return value


@dataclass
class Attempt:
    generation: str
    device_code: str = field(repr=False)
    user_code: str = field(repr=False)
    url: str = field(repr=False)
    expires: float
    interval: int
    next_poll: float


class RMFGAuth:
    def __init__(self, store, transport=request, clock=time.time):
        self.store, self.transport, self.clock = store, transport, clock

    def _post(self, path, fields):
        return self.transport('POST',path,{'client_id':CLIENT_ID,**fields},content_type='application/x-www-form-urlencoded')

    def validate_tokens(self, value):
        lifetime = value.get('expires_in')
        if (str(value.get('token_type','')).lower()!='bearer' or not isinstance(value.get('scope'),str)
                or not set(SCOPES.split()) <= set(value['scope'].split())
                or type(lifetime) not in (int,float) or not math.isfinite(lifetime) or not 0<lifetime<=900):
            raise RMFGError('RMFG connection needs designs and DFM permissions and a valid expiry. Reconnect.')
        return {'access_token':secret(value.get('access_token')), 'refresh_token':secret(value.get('refresh_token')),
                'expires_at':self.clock()+lifetime, 'scope':value['scope']}

    def begin(self):
        with self.store.locked():
            result = self._post('/v1/oauth/device/code',{'scope':SCOPES})
            interval, duration = result.get('interval',5), result.get('expires_in')
            if type(interval) is not int or not 1<=interval<=3600 or type(duration) is not int or not 1<=duration<=86400:
                raise RMFGError('RMFG returned invalid sign-in timing.')
            attempt = Attempt(uuid4().hex,secret(result.get('device_code')),secret(result.get('user_code')),
                browser_url(result.get('verification_uri_complete')),self.clock()+duration,interval,self.clock()+interval)
            self.store.write({'state':'authorizing','generation':attempt.generation})
            return attempt

    def poll(self, attempt):
        with self.store.locked():
            record = self.store.read() or {}
            if record.get('state')!='authorizing' or record.get('generation')!=attempt.generation:
                raise RMFGError('That RMFG sign-in attempt ended. Start a new connection.')
            if self.clock()>=attempt.expires:
                self.store.write({'state':'disconnected'})
                raise RMFGError('RMFG sign-in expired. Connect again.')
            if self.clock()<attempt.next_poll:
                return 'pending'
            self.store.write({'state':'exchanging','generation':attempt.generation})
            try:
                payload = self._post('/v1/oauth/token',{'grant_type':'urn:ietf:params:oauth:grant-type:device_code','device_code':attempt.device_code})
            except RMFGError as error:
                if error.status==400 and error.code in ('authorization_pending','slow_down'):
                    attempt.interval += 5 if error.code=='slow_down' else 0
                    attempt.next_poll = self.clock()+attempt.interval
                    self.store.write({'state':'authorizing','generation':attempt.generation})
                    return 'pending'
                # A lost response may have consumed the device code. Never replay
                # an uncertain successful exchange or a consumed refresh token.
                raise RMFGError('RMFG sign-in was declined, interrupted or expired. Connect again.') from None
            self.store.write({'state':'connected','connection':uuid4().hex,'tokens':self.validate_tokens(payload)})
            return 'connected'

    def status(self):
        with self.store.locked():
            record = self.store.read() or {}
            state = record.get('state','disconnected')
            return {'state':state if state in ('connected','disconnected','authorizing') else 'reconnect'}

    def cancel(self, attempt):
        with self.store.locked():
            record = self.store.read() or {}
            if record.get('generation') == attempt.generation:
                self.store.write({'state':'disconnected'})

    def connection_id(self):
        with self.store.locked():
            record = self.store.read() or {}
            if record.get('state') != 'connected' or not record.get('connection'):
                raise RMFGError('Connect RMFG in STEVE before using supplier jobs.')
            return identifier(record['connection'])

    def access_token(self):
        with self.store.locked():
            record = self.store.read() or {}
            if record.get('state')!='connected':
                raise RMFGError('Connect RMFG in STEVE before requesting an external DFM check.')
            tokens = record.get('tokens',{})
            expiry = tokens.get('expires_at')
            if (type(expiry) not in (int,float) or not math.isfinite(expiry)
                    or not set(SCOPES.split()) <= set(str(tokens.get('scope','')).split())):
                raise RMFGError('The RMFG connection is invalid. Reconnect.')
            if self.clock()+30<expiry:
                return secret(tokens.get('access_token'))
            refresh = secret(tokens.get('refresh_token'))
            self.store.write({'state':'refreshing'})
            try:
                result = self._post('/v1/oauth/token',{'grant_type':'refresh_token','refresh_token':refresh})
                replacement = self.validate_tokens(result)
                self.store.write({'state':'connected','connection':record.get('connection'),'tokens':replacement})
            except Exception:
                raise RMFGError('RMFG refresh could not be confirmed. Reconnect instead of retrying the old credential.') from None
            return replacement['access_token']

    def disconnect(self):
        with self.store.locked():
            record = self.store.read() or {}
            refresh = record.get('tokens',{}).get('refresh_token')
            self.store.write({'state':'disconnected'})
            if refresh:
                self._post('/v1/oauth/revoke',{'token':refresh})


class RMFGClient:
    def __init__(self, access_token, transport=request):
        self.access_token, self.transport = access_token, transport

    def materials(self, cursor=None):
        query = {'limit':20}
        if cursor is not None:
            if not isinstance(cursor,str) or not 0<len(cursor)<=1000:
                raise ValueError('Use the returned catalog cursor.')
            query['cursor']=cursor
        return self.transport('GET','/v1/materials?'+urlencode(query),token=self.access_token())

    def analyze(self, step_bytes, operation_key):
        if not isinstance(step_bytes,bytes) or not 0<len(step_bytes)<=MAX_STEP_BYTES:
            raise ValueError('Provide a nonempty STEP snapshot no larger than 50 MiB.')
        boundary='steve-'+hashlib.sha256(step_bytes).hexdigest()
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="part.step"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
              +step_bytes+f'\r\n--{boundary}--\r\n'.encode())
        return self.transport('POST','/v1/analyze',body,token=self.access_token(),
            content_type='multipart/form-data; boundary='+boundary,key=identifier(operation_key))

    def design(self, design_id):
        return self.transport('GET','/v1/designs/'+identifier(design_id),token=self.access_token())

    def create_dfm(self, design_id, parts, operation_key):
        if not isinstance(parts,list) or not 1<=len(parts)<=20:
            raise ValueError('Configure 1 to 20 analyzed parts.')
        for part in parts:
            if not isinstance(part,dict) or set(part)!={'part_id','material_id'}:
                raise ValueError('Initial DFM supports observed part_id and material_id only; no accepted risks or manufacturing operations.')
            identifier(part['part_id'])
            identifier(part['material_id'])
        return self.transport('POST','/v1/dfm',{'design_id':identifier(design_id),
            'configuration':{'parts':parts},'generate_production_files':False},token=self.access_token(),key=identifier(operation_key))

    def dfm(self, dfm_id):
        return self.transport('GET','/v1/dfm/'+identifier(dfm_id),token=self.access_token())

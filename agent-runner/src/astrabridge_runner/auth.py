"""Sign in with ChatGPT for a public OSS client, independent of Codex."""
import base64
import copy
import hashlib
import json
import math
import os
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt

from .journal import atomic_json, json_text
from .locking import FileLock
from .types import ProviderError

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
DIRECT = 'chatgpt.tokens.use.direct'
TOKENS = ('access_token', 'refresh_token', 'id_token')


def default_auth_directory():
    if os.name == 'nt': return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'AstraBridgeRunner'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'astrabridge-runner'


def dpapi(data, decrypt=False):
    """Windows credentials are bound to this OS user; no machine-wide key."""
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))); destination = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise OSError('Windows credential protection failed.')
    try: return ctypes.string_at(destination.data, destination.length)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(destination.data)


class Callback:
    def __init__(self, state, port=None):
        self.state, self.result, self.ready = state, None, threading.Event()
        self.accept_lock=threading.Lock()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                parsed = urlparse(self.path); query = parse_qs(parsed.query)
                valid = parsed.path == '/auth/callback' and all(len(v) == 1 for v in query.values())
                valid = valid and secrets.compare_digest(query.get('state', [''])[0], owner.state)
                valid = valid and bool(query.get('code') or query.get('error'))
                if valid and owner.accept(query):
                    status, text = 200, 'You may return to AstraBridge Runner.'
                else: status, text = 400, 'Invalid or expired authorization callback.'
                data = text.encode(); self.send_response(status)
                self.send_header('Content-Type', 'text/plain; charset=utf-8'); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
        try: self.server = ThreadingHTTPServer(('127.0.0.1', 1455 if port is None else port), Handler)
        except OSError:
            if port is not None: raise ProviderError('The requested callback port is unavailable.')
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.uri = f'http://127.0.0.1:{self.server.server_port}/auth/callback'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def accept(self,query):
        with self.accept_lock:
            if self.ready.is_set():return False
            self.result={k:v[0] for k,v in query.items()};self.ready.set();return True

    def submit(self,url):
        parsed=urlparse(url.strip());query=parse_qs(parsed.query)
        if url.split('?',1)[0]!=self.uri or any(len(value)!=1 for value in query.values()):return False
        if not secrets.compare_digest(query.get('state',[''])[0],self.state) or not (query.get('code') or query.get('error')):return False
        return self.accept(query)

    def wait(self, timeout=600, *, manual=False, output=print):
        deadline = time.monotonic() + timeout
        manual=manual and sys.stdin.isatty();saved_terminal=None;buffer=''
        if manual:
            output('Without a tunnel, the final browser page may fail to connect. Paste its full callback URL here; input is hidden.')
            if os.name=='posix':
                import termios
                saved_terminal=termios.tcgetattr(sys.stdin.fileno());settings=list(saved_terminal);settings[3]&=~termios.ECHO
                termios.tcsetattr(sys.stdin.fileno(),termios.TCSANOW,settings)
        try:
            while not self.ready.wait(.1):
                if time.monotonic() >= deadline: raise ProviderError('ChatGPT sign-in timed out. Start a fresh sign-in.')
                value=None
                if manual and os.name=='posix':
                    import select
                    if select.select([sys.stdin],[],[],0)[0]:
                        line=sys.stdin.readline()
                        if not line:raise ProviderError('Authorization input closed. Start a fresh sign-in.')
                        value=line.strip()
                elif manual and os.name=='nt':
                    import msvcrt
                    while msvcrt.kbhit():
                        char=msvcrt.getwch()
                        if char=='\x03':raise KeyboardInterrupt
                        if char=='\r':value=buffer;buffer='';break
                        if char=='\b':buffer=buffer[:-1]
                        else:buffer+=char
                if value is not None and not self.submit(value):output('Invalid callback URL. Paste the full address from this sign-in attempt.')
            return self.result
        finally:
            if saved_terminal is not None:
                import termios
                termios.tcsetattr(sys.stdin.fileno(),termios.TCSANOW,saved_terminal)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()


class AuthStore:
    def __init__(self, directory=None, *, journal=None, issuer=ISSUER, client=None):
        self.directory = Path(directory or default_auth_directory()).resolve()
        self.file = self.directory / 'chatgpt-auth.json'; self.journal = journal
        self.issuer = issuer.rstrip('/'); self.secrets = set(); self.metadata = None
        self.client = client or httpx.Client(timeout=30)

    def remember(self, value):
        if isinstance(value,str) and value:
            self.secrets.add(value)
            if self.journal: self.journal.add_secret(value)

    def clean_error(self, value):
        text = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True): text = text.replace(secret, '[REDACTED]')
        return text

    def lock(self):
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if os.name != 'nt': self.directory.chmod(0o700)
        return FileLock(self.directory / '.auth.lock')

    def read(self):
        if not self.file.exists(): return {'schema': 1, 'host_id': None, 'active': None, 'accounts': {}}
        if self.file.is_symlink(): raise ProviderError('Credential storage must not be a symlink.')
        value = json.loads(self.file.read_text(encoding='utf-8'))
        if value.get('schema') != 1: raise ProviderError('Unsupported credential storage format.')
        for row in value['accounts'].values():
            if 'protected_credentials' in row:
                if os.name != 'nt': raise ProviderError('These credentials belong to a Windows host.')
                row['credentials'] = json.loads(dpapi(base64.b64decode(row.pop('protected_credentials')), True))
            for name in TOKENS: self.remember(row.get('credentials', {}).get(name))
        return value

    def write(self, value):
        stored = copy.deepcopy(value)
        if os.name == 'nt':
            for row in stored['accounts'].values():
                if row.get('credentials'):
                    row['protected_credentials'] = base64.b64encode(dpapi(json_text(row.pop('credentials')).encode())).decode()
        atomic_json(self.file, stored)

    def resolve(self, account=None, state=None):
        state = state or self.read(); account = account or state['active']
        if not account or account not in state['accounts']: raise ProviderError('No ChatGPT account selected. Run auth login.')
        return state['accounts'][account]

    def public(self, row):
        credentials = row.get('credentials', {})
        return {k: row.get(k) for k in ('id', 'label', 'client_id', 'email')} | {
            'signed_in': bool(credentials.get('access_token')), 'plan_usage_enabled': DIRECT in credentials.get('scopes', []),
            'expires_at': credentials.get('expires_at'), 'requires_login': row.get('requires_login', False)}

    def status(self):
        state = self.read()
        return {'active': state['active'], 'accounts': [self.public(row) for row in state['accounts'].values()]}

    def use(self, account):
        with self.lock():
            state = self.read(); self.resolve(account, state); state['active'] = account; self.write(state)
        return self.status()

    def discovery(self):
        if self.metadata is None:
            response = self.client.get(self.issuer + '/.well-known/openid-configuration'); response.raise_for_status()
            data = response.json()
            if data.get('issuer') != self.issuer: raise ProviderError('Unexpected OpenAI OAuth issuer.')
            for field in ('authorization_endpoint', 'token_endpoint', 'jwks_uri', 'revocation_endpoint'):
                endpoint = urlparse(data.get(field, ''))
                expected = urlparse(self.issuer)
                if endpoint.scheme != expected.scheme or endpoint.netloc != expected.netloc or endpoint.username or endpoint.password:
                    raise ProviderError('OAuth discovery returned an untrusted endpoint.')
            self.metadata = data
        return self.metadata

    def form(self, endpoint, values):
        for name in ('code', 'code_verifier', 'refresh_token', 'token'): self.remember(values.get(name))
        for attempt in range(3):
            try: response = self.client.post(endpoint, data=values)
            except httpx.TransportError as exc:
                if attempt < 2: time.sleep(2 ** attempt); continue
                raise ProviderError('OAuth connection failed. Saved registrations were retained.') from exc
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2: time.sleep(2 ** attempt); continue
            try: body = response.json() if response.content else {}
            except ValueError: body = {'error': 'invalid_oauth_response'}
            if not response.is_success:
                raise ProviderError('OAuth failed: ' + self.clean_error(json_text(body)), code=body.get('error'), status=response.status_code)
            for name in TOKENS: self.remember(body.get(name))
            return body

    def identity(self, token, client_id, nonce):
        self.remember(token)
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') not in ('RS256', 'ES256'): raise ValueError('Unsupported signing algorithm')
            response = self.client.get(self.discovery()['jwks_uri']); response.raise_for_status()
            keys = response.json()['keys']
            key = next(key for key in keys if key.get('kid') == header.get('kid'))
            verified = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=[header['alg']],
                                  audience=client_id, issuer=self.issuer, options={'require': ['exp', 'iss', 'aud', 'sub']})
            if nonce is not None and not secrets.compare_digest(str(verified.get('nonce', '')), nonce): raise ValueError('Nonce mismatch')
            return verified
        except (jwt.PyJWTError, ValueError, KeyError, StopIteration) as exc:
            raise ProviderError('OpenAI ID token validation failed.') from exc

    def credentials(self, data, previous=None):
        previous = previous or {}
        if not isinstance(data.get('access_token'), str) or not isinstance(data.get('refresh_token'), str):
            raise ProviderError('OAuth did not issue renewable credentials.')
        expires = data.get('expires_in')
        if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= 0: raise ProviderError('OAuth returned an invalid token lifetime.')
        scope = data.get('scope')
        return {**{name: data.get(name, previous.get(name)) for name in TOKENS},
                'scopes': scope.split() if isinstance(scope, str) else previous.get('scopes', []),
                'expires_at': time.time() + expires, 'earliest_refresh_at': data.get('earliest_refresh_at'), 'saved_at': time.time()}

    def login(self, *, no_browser=False, port=None, account=None, new=False, output=print, timeout=600):
        with self.lock():
            state = self.read()
            if not state['host_id']: state['host_id'] = 'urn:uuid:' + str(uuid.uuid4()); self.write(state)
            selected = None
            if not new:
                if account or state['active']: selected = self.resolve(account, state)
                elif len(state['accounts']) == 1: selected = next(iter(state['accounts'].values()))
            host_id = state['host_id']
        metadata = self.discovery(); attempt_state = secrets.token_urlsafe(32); nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64); self.remember(verifier)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        listener = Callback(attempt_state, port)
        params = {'client_id': selected['client_id'] if selected else 'dynamic_agent_client', 'ext_agent_host_id': host_id,
                  'response_type': 'code', 'redirect_uri': listener.uri, 'scope': SCOPES, 'resource': RESOURCE,
                  'state': attempt_state, 'nonce': nonce, 'code_challenge_method': 'S256', 'code_challenge': challenge}
        if not selected: params['agent_name_hint'] = 'AstraBridge Runner'
        elif selected.get('email'): params['login_hint'] = selected['email']
        if selected and not no_browser and selected.get('credentials', {}).get('id_token'):
            params['id_token_hint'] = selected['credentials']['id_token']
        url = metadata['authorization_endpoint'] + '?' + urlencode(params)
        try:
            output('Continue with ChatGPT')
            if no_browser:
                output(url); actual_port = listener.server.server_port
                output(f'Optional SSH forwarding: ssh -L {actual_port}:127.0.0.1:{actual_port} USER@HOST')
            elif not webbrowser.open(url): raise ProviderError('Unable to open a browser. Use auth login --no-browser.')
            result = listener.wait(timeout,manual=no_browser,output=output)
            if result.get('error'): raise ProviderError('ChatGPT sign-in was declined or failed: ' + result['error'])
            issued = result.get('client_id') or (selected['client_id'] if selected else None)
            if not issued or issued == 'dynamic_agent_client': raise ProviderError('Dynamic registration did not return an issued client ID.')
            if selected and issued != selected['client_id']: raise ProviderError('Callback changed the selected registration.')
            identifier = selected['id'] if selected else uuid.uuid4().hex
            # Retain the issued registration even if the one-use code expires.
            with self.lock():
                current = self.read()
                current['accounts'].setdefault(identifier, {'id': identifier, 'client_id': issued, 'label': 'Pending ' + identifier[:8]})
                self.write(current)
            data = self.form(metadata['token_endpoint'], {'grant_type': 'authorization_code', 'client_id': issued,
                             'code': result['code'], 'code_verifier': verifier, 'redirect_uri': listener.uri, 'resource': RESOURCE})
            identity = self.identity(data.get('id_token', ''), issued, nonce)
            if selected and selected.get('subject') and identity['sub'] != selected['subject']:
                raise ProviderError('Signed-in identity differs from the selected ChatGPT account.')
            credentials = self.credentials(data)
            row = {'id': identifier, 'client_id': issued, 'issuer': self.issuer, 'subject': identity['sub'],
                   'email': identity.get('email'), 'label': (identity.get('email') or 'ChatGPT') + ' [' + identifier[:8] + ']',
                   'credentials': credentials, 'requires_login': False}
            with self.lock():
                current = self.read(); current['accounts'][identifier] = row; current['active'] = identifier; self.write(current)
            if self.journal: self.journal.event('oauth_login', account=identifier, plan_usage_enabled=DIRECT in credentials['scopes'])
            return self.public(row)
        finally: listener.close()

    def access(self, account=None, *, force=False):
        # Refresh rotation is serialized across both threads and processes.
        with self.lock():
            state = self.read(); row = self.resolve(account, state); credentials = row.get('credentials', {})
            if not credentials.get('access_token'): raise ProviderError('ChatGPT sign-in required. Run auth login.')
            if DIRECT not in credentials.get('scopes', []): raise ProviderError('ChatGPT plan usage was not granted. Run auth login to authorize it.')
            now = time.time()
            if not force and credentials['expires_at'] - now > 60: return credentials['access_token']
            earliest = credentials.get('earliest_refresh_at')
            if isinstance(earliest, str):
                from datetime import datetime
                try: earliest = datetime.fromisoformat(earliest.replace('Z', '+00:00')).timestamp()
                except ValueError: raise ProviderError('Invalid earliest refresh time.')
            if isinstance(earliest, (int, float)) and now < earliest:
                if credentials['expires_at'] > now and not force: return credentials['access_token']
                raise ProviderError('Token renewal is not available yet; retry after the advertised refresh time.')
            try:
                data = self.form(self.discovery()['token_endpoint'], {'grant_type': 'refresh_token', 'client_id': row['client_id'],
                                 'refresh_token': credentials['refresh_token'], 'resource': RESOURCE})
                if data.get('id_token'):
                    identity=self.identity(data['id_token'],row['client_id'],None)
                    if identity['sub']!=row['subject']:raise ProviderError('Refreshed identity differs from the registration.')
                row['credentials'] = self.credentials(data, credentials); row['requires_login'] = False; self.write(state)
                if self.journal: self.journal.event('oauth_refresh', account=row['id'], expires_at=row['credentials']['expires_at'])
                if DIRECT not in row['credentials']['scopes']:raise ProviderError('ChatGPT plan usage was removed from the renewed grant.')
                return row['credentials']['access_token']
            except ProviderError as exc:
                if exc.code in ('invalid_grant', 'invalid_token'):
                    row.pop('credentials', None); row['requires_login'] = True; self.write(state)
                raise

    def logout(self, account=None):
        with self.lock():
            state = self.read(); row = self.resolve(account, state); confirmed = True
            token = row.get('credentials', {}).get('refresh_token')
            if token:
                try: self.form(self.discovery()['revocation_endpoint'], {'token': token, 'token_type_hint': 'refresh_token', 'client_id': row['client_id']})
                except (ProviderError, httpx.HTTPError): confirmed = False
            row.pop('credentials', None); row['requires_login'] = True; self.write(state)
        return {'account': row['id'], 'signed_out': True, 'remote_revocation_confirmed': confirmed,
                'message': None if confirmed else 'Remote revocation was not confirmed. You can disconnect the app in ChatGPT Settings.'}

    def close(self): self.client.close()

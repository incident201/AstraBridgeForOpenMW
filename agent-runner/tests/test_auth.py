import json
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlencode

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from astrabridge_runner.auth import AuthStore, Callback, DIRECT, SCOPES
from astrabridge_runner.journal import Journal
from astrabridge_runner.types import ProviderError


class OAuthFixture:
    issuer = 'https://auth.fixture.test'
    def __init__(self):
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key())); self.jwk['kid'] = 'fixture'
        self.nonce = ''; self.subject = 'subscriber'; self.scope = SCOPES; self.token_number = 0
        self.requests = []; self.refresh_error = None; self.exchange_error = None; self.revocation_error = False
        self.bad_nonce = False; self.bad_audience = False
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request):
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
        self.requests.append((request.url.path, body))
        path = request.url.path
        if path == '/.well-known/openid-configuration':
            return httpx.Response(200, json={'issuer': self.issuer, 'authorization_endpoint': self.issuer + '/authorize',
                'token_endpoint': self.issuer + '/token', 'jwks_uri': self.issuer + '/jwks', 'revocation_endpoint': self.issuer + '/revoke'})
        if path == '/jwks': return httpx.Response(200, json={'keys': [self.jwk]})
        if path == '/revoke': return httpx.Response(400 if self.revocation_error else 200, json={'error': 'unconfirmed'} if self.revocation_error else {})
        assert path == '/token'
        if body['grant_type'] == 'refresh_token' and self.refresh_error: return httpx.Response(400, json={'error': self.refresh_error})
        if body['grant_type'] == 'authorization_code' and self.exchange_error: return httpx.Response(400, json={'error': self.exchange_error})
        if body['grant_type'] == 'authorization_code':
            assert body['code'] == 'fixture-one-use-code' and 'code_verifier' in body
            assert body['redirect_uri'].startswith('http://127.0.0.1:') and body['redirect_uri'].endswith('/auth/callback')
            assert body['resource'] == 'https://api.openai.com/v1'
        self.token_number += 1
        data = {'access_token': 'fixture-access-' + str(self.token_number), 'refresh_token': 'fixture-refresh-' + str(self.token_number),
                'expires_in': 3600, 'scope': self.scope}
        if body['grant_type'] == 'authorization_code':
            data['id_token'] = jwt.encode({'iss': self.issuer, 'aud': 'wrong' if self.bad_audience else body['client_id'],
                'sub': self.subject, 'email': 'subscriber@example.test', 'nonce': 'wrong' if self.bad_nonce else self.nonce,
                'exp': time.time() + 600}, self.private, algorithm='RS256', headers={'kid': 'fixture'})
        return httpx.Response(200, json=data)

    def sign_in(self, store, *, new=False, account=None, error=None, changed_client=None):
        urls = []
        def output(text):
            if not text.startswith(self.issuer + '/authorize'): return
            query = {k: v[0] for k, v in parse_qs(text.split('?', 1)[1]).items()}; urls.append(query)
            self.nonce = query['nonce']
            values = {'state': query['state']}
            if error: values['error'] = error
            else: values.update(code='fixture-one-use-code', client_id=changed_client or ('oaiapp_fixture_' + str(self.token_number) if query['client_id'] == 'dynamic_agent_client' else query['client_id']))
            url = query['redirect_uri'] + '?' + urlencode(values)
            def callback():
                with urllib.request.urlopen(url) as response: assert response.status == 200
            thread = threading.Thread(target=callback); thread.start(); thread.join()
        result = store.login(no_browser=True, port=0, new=new, account=account, output=output, timeout=5)
        return result, urls[0]


@pytest.fixture
def oauth(tmp_path):
    fake = OAuthFixture(); journal = Journal(tmp_path / 'logs')
    store = AuthStore(tmp_path / 'auth', journal=journal, issuer=fake.issuer, client=fake.client)
    yield fake, store, journal
    store.close(); journal.close()


def test_sign_in_pkce_host_identity_and_account_isolation(oauth):
    fake, store, journal = oauth
    first, query = fake.sign_in(store)
    assert query['client_id'] == 'dynamic_agent_client' and query['agent_name_hint'] == 'AstraBridge Runner'
    assert query['code_challenge_method'] == 'S256' and 'id_token_hint' not in query
    host = query['ext_agent_host_id']
    same, returning = fake.sign_in(store)
    assert same['id'] == first['id'] and returning['client_id'] == first['client_id']
    assert returning['ext_agent_host_id'] == host and 'agent_name_hint' not in returning
    fake.subject = 'second-subscriber'
    second, other = fake.sign_in(store, new=True)
    assert second['id'] != first['id'] and other['ext_agent_host_id'] == host
    assert len(store.status()['accounts']) == 2
    store.use(first['id']); assert store.status()['active'] == first['id']
    tokens = store.read()['accounts'][first['id']]['credentials']
    for value in tokens.values():
        if isinstance(value, str) and ('fixture-' in value or value.count('.') == 2):
            assert value not in (journal.root / 'events.jsonl').read_text()
    assert store.file.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('field', ['bad_nonce', 'bad_audience'])
def test_id_token_validation_does_not_replace_active_account(oauth, field):
    fake, store, _ = oauth
    first, _ = fake.sign_in(store)
    setattr(fake, field, True)
    with pytest.raises(ProviderError, match='validation'): fake.sign_in(store, new=True)
    assert store.status()['active'] == first['id']


def test_decline_scope_and_different_callback_client(oauth):
    fake, store, _ = oauth
    with pytest.raises(ProviderError, match='declined'): fake.sign_in(store, error='access_denied')
    assert not store.status()['accounts']
    fake.scope = 'openid profile email offline_access resource.invoke'
    row, _ = fake.sign_in(store); assert not row['plan_usage_enabled']
    with pytest.raises(ProviderError, match='not granted'): store.access()
    with pytest.raises(ProviderError, match='registration'): fake.sign_in(store, changed_client='oaiapp_other')


def test_expired_code_retains_issued_registration(oauth):
    fake, store, _ = oauth; fake.exchange_error = 'invalid_grant'
    with pytest.raises(ProviderError): fake.sign_in(store)
    row = store.status()['accounts'][0]
    assert row['client_id'].startswith('oaiapp_') and not row['signed_in']
    fake.exchange_error = None
    _, returning = fake.sign_in(store)
    assert returning['client_id'] == row['client_id']


def test_refresh_serialization_rotation_and_terminal_revocation(oauth):
    fake, store, _ = oauth; row, _ = fake.sign_in(store)
    with store.lock():
        state = store.read(); state['accounts'][row['id']]['credentials']['expires_at'] = 0; store.write(state)
    values = []
    threads = [threading.Thread(target=lambda: values.append(store.access())) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(values) == 4 and len(set(values)) == 1
    refreshes = [body for path, body in fake.requests if path == '/token' and body['grant_type'] == 'refresh_token']
    assert len(refreshes) == 1 and refreshes[0]['refresh_token'] == 'fixture-refresh-1'
    assert 'scope' not in refreshes[0]
    assert store.read()['accounts'][row['id']]['credentials']['refresh_token'] == 'fixture-refresh-2'
    fake.refresh_error = 'invalid_grant'
    with pytest.raises(ProviderError): store.access(force=True)
    assert store.status()['accounts'][0]['requires_login'] and not store.status()['accounts'][0]['signed_in']


def test_logout_retain_registration_and_report_failed_revoke(oauth):
    fake, store, _ = oauth; row, _ = fake.sign_in(store)
    host = store.read()['host_id']; fake.revocation_error = True
    result = store.logout(); assert result['signed_out'] and not result['remote_revocation_confirmed']
    assert store.read()['host_id'] == host and store.status()['accounts'][0]['client_id'] == row['client_id']
    _, returning = fake.sign_in(store)
    assert returning['client_id'] == row['client_id']


def test_callback_rejects_wrong_state_before_accepting_real_callback():
    callback = Callback('expected-state', 0)
    try:
        with pytest.raises(urllib.error.HTTPError): urllib.request.urlopen(callback.uri + '?state=wrong&code=bad')
        assert not callback.ready.is_set()
        with urllib.request.urlopen(callback.uri + '?state=expected-state&code=ok'): pass
        assert callback.wait(1)['code'] == 'ok'
    finally: callback.close()


def test_refresh_removed_permission_stops_inference(oauth):
    fake, store, _ = oauth; fake.sign_in(store)
    fake.scope = 'openid profile email offline_access resource.invoke'
    with pytest.raises(ProviderError, match='removed'): store.access(force=True)
    assert store.status()['accounts'][0]['signed_in'] and not store.status()['accounts'][0]['plan_usage_enabled']


def test_successful_logout_revokes_latest_refresh_token(oauth):
    fake, store, _ = oauth; row, _ = fake.sign_in(store)
    store.access(force=True); result = store.logout()
    assert result['remote_revocation_confirmed']
    revoke = [body for path, body in fake.requests if path == '/revoke'][-1]
    assert revoke['token'] == 'fixture-refresh-2' and revoke['client_id'] == row['client_id']
    assert not store.status()['accounts'][0]['signed_in']


def test_returning_login_rejects_another_verified_identity(oauth):
    fake, store, _ = oauth; first, _ = fake.sign_in(store)
    fake.subject = 'another-subscriber'
    with pytest.raises(ProviderError, match='identity differs'): fake.sign_in(store)
    assert store.read()['accounts'][first['id']]['subject'] == 'subscriber'


def test_manual_callback_validates_uri_state_and_is_one_use():
    callback = Callback('expected-state', 0)
    try:
        assert not callback.submit('http://localhost:1234/auth/callback?state=expected-state&code=bad')
        assert not callback.submit(callback.uri + '?state=wrong&code=bad')
        assert not callback.submit(callback.uri + '?state=expected-state&state=other&code=bad')
        assert callback.submit(callback.uri + '?state=expected-state&code=one-use-code&client_id=oaiapp_fixture')
        assert callback.wait(1)['code'] == 'one-use-code'
        assert not callback.submit(callback.uri + '?state=expected-state&code=another-code')
    finally: callback.close()

import json

import httpx
import pytest

from astrabridge_runner.journal import Journal
from astrabridge_runner.providers.http import Transport, retry_delay
from astrabridge_runner.providers.openai import OpenAI
from astrabridge_runner.types import ProviderError
from test_openai import Auth, response


@pytest.mark.parametrize('header,expected', [
    ('7', 7), ('0', 1), ('60', 60), ('61', None), ('invalid', 1),
    ('-1', 1), ('1.5', 1), ('', 1),
])
def test_retry_after_seconds_are_bounded(header, expected):
    assert retry_delay(0, {'retry-after': header}) == expected


def test_retry_after_http_date_and_past_date(monkeypatch):
    monkeypatch.setattr('astrabridge_runner.providers.http.time.time', lambda: 1000)
    assert retry_delay(0, {'retry-after': 'Thu, 01 Jan 1970 00:16:50 GMT'}) == 10
    assert retry_delay(1, {'retry-after': 'Thu, 01 Jan 1970 00:00:00 GMT'}) == 2
    assert retry_delay(0, {'retry-after': 'Thu, 01 Jan 1970 01:00:00 GMT'}) is None


@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
def test_transport_waits_before_retrying_response(tmp_path, monkeypatch, status):
    waits = []
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, headers={'Retry-After': '8'}, json={'error': {'message': 'Try later'}})
        return httpx.Response(200, json={'ok': True})

    monkeypatch.setattr('astrabridge_runner.providers.http.time.sleep', waits.append)
    journal = Journal(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = Transport(journal, 'https://example.test', client)
    try:
        assert transport.request('POST', 'https://example.test/test', payload={}) == {'ok': True}
        assert waits == [8] and len(requests) == 2
        assert next(row for row in journal.records() if row['kind'] == 'api_retry')['delay_seconds'] == 8
    finally:
        transport.close()
        journal.close()


@pytest.mark.parametrize('status,code,header', [
    (404, None, '8'), (401, None, '8'), (429, 'subscription_sharing_usage_limit_exceeded', '8'),
    (429, 'subscription_sharing_usage_unavailable', '8'), (503, None, '120'),
])
def test_permanent_or_long_wait_response_is_not_retried(tmp_path, monkeypatch, status, code, header):
    requests = []
    waits = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={'Retry-After': header}, json={'error': {'code': code}})

    monkeypatch.setattr('astrabridge_runner.providers.http.time.sleep', waits.append)
    journal = Journal(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = Transport(journal, 'https://example.test', client)
    try:
        with pytest.raises(ProviderError) as error:
            transport.request('GET', 'https://example.test/test')
        assert error.value.status == status and error.value.code == code
        assert len(requests) == 1 and waits == []
    finally:
        transport.close()
        journal.close()


def test_openai_stream_retry_honors_same_retry_after(tmp_path, monkeypatch):
    requests = []
    waits = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, headers={'Retry-After': '9'}, json={'error': {'message': 'Try later'}})
        event = {'type': 'response.completed', 'response': response(0, text='Done')}
        return httpx.Response(200, content='data: ' + json.dumps(event) + '\n\n')

    monkeypatch.setattr('astrabridge_runner.providers.http.time.sleep', waits.append)
    journal = Journal(tmp_path)
    client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    api = OpenAI(Auth(), journal, 'fixture', 'xhigh', client=client)
    try:
        assert api.complete('Rules', [], []).text == 'Done'
        assert waits == [9] and len(requests) == 2
    finally:
        api.close()
        journal.close()


def test_transient_retries_stop_after_three_attempts(tmp_path, monkeypatch):
    waits = []
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, json={'error': {'message': 'Still unavailable'}})

    monkeypatch.setattr('astrabridge_runner.providers.http.time.sleep', waits.append)
    journal = Journal(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = Transport(journal, 'https://example.test', client)
    try:
        with pytest.raises(ProviderError, match='HTTP 503'):
            transport.request('GET', 'https://example.test/test')
        assert len(requests) == 3 and waits == [1, 2]
        assert len(list((journal.root / 'api').glob('*request*'))) == 3
        assert len(list((journal.root / 'api').glob('*response*'))) == 3
    finally:
        transport.close()
        journal.close()

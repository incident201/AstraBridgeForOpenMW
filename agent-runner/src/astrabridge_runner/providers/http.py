import time
import httpx

from ..journal import json_text
from ..types import ProviderError


class Transport:
    def __init__(self, journal, base_url, client=None):
        self.journal = journal
        self.client = client or httpx.Client(base_url=base_url.rstrip('/') + '/', timeout=httpx.Timeout(600, connect=10, write=60, pool=30))

    def begin(self, method, path, payload, attempt):
        if payload is not None and len(json_text(payload).encode()) > 48 * 1024 * 1024: raise ProviderError('API body exceeds 48 MiB. History was retained.')
        index = self.journal.next_api(); start = time.monotonic()
        record = self.journal.api_record(index, 'request', {'method': method, 'path': path, 'body': payload})
        self.journal.event('api_request', index=index, attempt=attempt + 1, record=record)
        return index, start

    def finish(self, index, start, status, headers, body):
        diagnostic = {k: v for k, v in headers.items() if k in ('x-request-id', 'request-id', 'retry-after') or k.startswith('x-ratelimit')}
        record = self.journal.api_record(index, 'response', {'status': status, 'headers': diagnostic, 'body': body, 'elapsed': time.monotonic() - start})
        usage = body.get('usage') if isinstance(body, dict) else None
        self.journal.event('api_response', index=index, status=status, record=record, usage=usage)

    def request(self, method, path, *, payload=None, headers=None):
        for attempt in range(3):
            index, start = self.begin(method, path, payload, attempt)
            try: response = self.client.request(method, path, json=payload, headers=headers)
            except httpx.TransportError as exc:
                self.finish(index, start, None, {}, {'transport_error': str(exc)})
                if attempt < 2: time.sleep(2 ** attempt); continue
                raise ProviderError('API transport failed. Session history was retained.') from exc
            try: body = response.json()
            except ValueError: body = {'invalid_json_response': response.text}
            self.finish(index, start, response.status_code, response.headers, body)
            error = body.get('error', {}) if isinstance(body, dict) else {}
            code = error.get('code') if isinstance(error, dict) else None
            if not isinstance(code,str):code=None
            if response.status_code in (429, 500, 502, 503, 504) and not (code or '').startswith('subscription_sharing_usage_limit') and attempt < 2:
                time.sleep(2 ** attempt); continue
            if not response.is_success: raise ProviderError(f'API returned HTTP {response.status_code}: ' + json_text(body), code=code, status=response.status_code)
            if not isinstance(body, dict) or 'invalid_json_response' in body: raise ProviderError('API returned invalid JSON.')
            return body

    def close(self): self.client.close()

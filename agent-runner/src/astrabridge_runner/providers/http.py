import time
from datetime import timezone
from email.utils import parsedate_to_datetime

import httpx

from ..journal import json_text
from ..types import ProviderError


RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRY_DELAY_SECONDS = 60


def retry_delay(attempt, headers):
    """Respect Retry-After without an unbounded blocking sleep."""
    delay = 2 ** attempt
    value = headers.get('retry-after')
    if value:
        value = value.strip()
        try:
            if value.isascii() and value.isdigit():
                requested = int(value)
            else:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                requested = max(0, date.timestamp() - time.time())
            # Stop instead of retrying earlier than the server permits.
            if requested > MAX_RETRY_DELAY_SECONDS:
                return None
            delay = max(delay, requested)
        except (ValueError, TypeError, OverflowError):
            pass
    return delay


class Transport:
    def __init__(self, journal, base_url, client=None):
        self.journal = journal
        self.client = client or httpx.Client(
            base_url=base_url.rstrip('/') + '/',
            timeout=httpx.Timeout(600, connect=10, write=60, pool=30),
        )

    def begin(self, method, path, payload, attempt):
        if payload is not None and len(json_text(payload).encode()) > 48 * 1024 * 1024:
            raise ProviderError('API body exceeds 48 MiB. History was retained.')
        index = self.journal.next_api()
        start = time.monotonic()
        record = self.journal.api_record(index, 'request', {'method': method, 'path': path, 'body': payload})
        self.journal.event('api_request', index=index, attempt=attempt + 1, record=record)
        return index, start

    def finish(self, index, start, status, headers, body):
        diagnostic = {k: v for k, v in headers.items() if k in ('x-request-id', 'request-id', 'retry-after') or k.startswith('x-ratelimit')}
        record = self.journal.api_record(index, 'response', {'status': status, 'headers': diagnostic, 'body': body, 'elapsed': time.monotonic() - start})
        usage = body.get('usage') if isinstance(body, dict) else None
        self.journal.event('api_response', index=index, status=status, record=record, usage=usage)

    def wait_to_retry(self, attempt, headers):
        delay = retry_delay(attempt, headers)
        if delay is None:
            return False
        self.journal.event('api_retry', attempt=attempt + 2, delay_seconds=delay)
        time.sleep(delay)
        return True

    def request(self, method, path, *, payload=None, headers=None):
        for attempt in range(3):
            index, start = self.begin(method, path, payload, attempt)
            try:
                response = self.client.request(method, path, json=payload, headers=headers)
            except httpx.TransportError as exc:
                self.finish(index, start, None, {}, {'transport_error': str(exc)})
                if attempt < 2:
                    self.wait_to_retry(attempt, {})
                    continue
                raise ProviderError('API transport failed. Session history was retained.') from exc
            try:
                body = response.json()
            except ValueError:
                body = {'invalid_json_response': response.text}
            self.finish(index, start, response.status_code, response.headers, body)
            error = body.get('error', {}) if isinstance(body, dict) else {}
            code = error.get('code') if isinstance(error, dict) else None
            if not isinstance(code, str):
                code = None
            retryable = response.status_code in RETRY_STATUSES and not (
                code or ''
            ).startswith('subscription_sharing_')
            if retryable and attempt < 2 and self.wait_to_retry(attempt, response.headers):
                continue
            if not response.is_success:
                raise ProviderError(
                    f'API returned HTTP {response.status_code}: ' + json_text(body),
                    code=code, status=response.status_code,
                )
            if not isinstance(body, dict) or 'invalid_json_response' in body:
                raise ProviderError('API returned invalid JSON.')
            return body

    def close(self):
        self.client.close()

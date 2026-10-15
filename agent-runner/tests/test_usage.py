import json

import httpx
import pytest

from astrabridge_runner.journal import Journal
from astrabridge_runner.main import main
from astrabridge_runner.providers.deepseek import DeepSeek
from astrabridge_runner.providers.http import Transport
from astrabridge_runner.types import ProviderError
from astrabridge_runner.usage import normalize, read_usage, format_usage


@pytest.mark.parametrize('raw', [
    {'input_tokens':100, 'output_tokens':30, 'input_tokens_details':{'cached_tokens':60},
     'output_tokens_details':{'reasoning_tokens':20}},
    {'total_input_tokens':100, 'total_output_tokens':10, 'total_thought_tokens':20, 'total_cached_tokens':60},
    {'prompt_tokens':100, 'completion_tokens':10, 'reasoning_tokens':20,
     'prompt_tokens_details':{'cached_tokens':60}, 'total_tokens':130},
    {'prompt_tokens':100, 'completion_tokens':30, 'completion_tokens_details':{'reasoning_tokens':20},
     'prompt_cache_hit_tokens':60},
])
def test_usage_normalizes_without_double_counting_subsets(raw):
    assert normalize(raw) == {'input_tokens':100, 'output_tokens':30, 'cached_input_tokens':60,
                              'uncached_input_tokens':40, 'reasoning_tokens':20, 'total_tokens':130}


def test_unknown_and_malformed_usage_are_not_zero():
    assert all(v is None for v in normalize(None).values())
    value = normalize({'input_tokens':False, 'output_tokens':-1, 'total_tokens':'123'})
    assert all(v is None for v in value.values())
    assert normalize({'input_tokens':10})['cached_input_tokens'] is None
    assert normalize({'input_tokens':10, 'input_tokens_details':{'cached_tokens':11}})['cached_input_tokens'] is None
    assert normalize({'total_output_tokens':10})['output_tokens'] is None


def test_totals_resume_checkpoint_retries_unknowns_and_cli(tmp_path, capsys):
    journal = Journal(tmp_path)
    # First attempt has no usage. Its retry and the checkpoint both cost tokens.
    journal.event('api_response', index=1, purpose='inference', status=503, outcome='failed', usage=None)
    journal.event('api_response', index=2, purpose='inference', status=200, outcome='completed',
                  usage={'input_tokens':100, 'output_tokens':20, 'input_tokens_details':{'cached_tokens':80}})
    journal.event('api_response', index=3, purpose='checkpoint', status=200, outcome='completed',
                  usage={'input_tokens':50, 'output_tokens':10})
    root = journal.root
    before = journal.usage.snapshot()
    assert before['total']['requests'] == 3
    assert before['total']['requests_without_usage'] == 1
    assert before['total']['tokens']['input_tokens'] == 150
    assert before['total']['tokens']['total_tokens'] == 180
    assert before['total']['cache_ratio'] == .8  # Unknown cache is not a miss.
    assert before['total']['reported_requests']['cached_input_tokens'] == 1
    assert before['by_purpose']['checkpoint']['tokens']['total_tokens'] == 60
    assert json.loads((root/'usage.json').read_text()) == before
    journal.close()
    (root/'usage.json').write_text('{}')  # A crash can leave the sidecar behind its journal.
    journal = Journal(tmp_path, resume=root)
    try:
        assert journal.usage.snapshot() == before
        assert json.loads((root/'usage.json').read_text()) == before
        journal.event('api_response', index=4, purpose='inference', status=200, outcome='completed',
                      usage={'input_tokens':20, 'output_tokens':3, 'input_tokens_details':{'cached_tokens':0}})
        assert journal.usage.snapshot()['total']['cache_ratio'] == pytest.approx(80/120)
        assert read_usage(root) == journal.usage.snapshot()
        assert main(['logs','stats',str(root),'--json']) == 0
        assert json.loads(capsys.readouterr().out) == journal.usage.snapshot()
        assert 'Totals include only reported' in format_usage(journal.usage.snapshot())
    finally:
        journal.close()


def test_incomplete_stream_usage_counted_without_tool_execution(tmp_path):
    data = {'type':'response.incomplete', 'response':{'status':'incomplete','usage':{
        'input_tokens':50, 'output_tokens':40, 'output_tokens_details':{'reasoning_tokens':40}}}}
    journal = Journal(tmp_path)
    api = DeepSeek('test-key', journal, client=httpx.Client(base_url='https://api.deepseek.com/',
        transport=httpx.MockTransport(lambda _:httpx.Response(200, content='data: '+json.dumps(data)+'\n\n'))))
    try:
        with pytest.raises(ProviderError, match='stream failed'):
            api.complete('rules',[api.user_item('task')],[])
        summary = journal.usage.snapshot()
        assert summary['total']['tokens']['total_tokens'] == 90
        assert summary['total']['tokens']['reasoning_tokens'] == 40
        assert summary['total']['failed_requests'] == 1
    finally:
        api.close(); journal.close()


def test_http_non_object_error_keeps_original_error(tmp_path):
    journal = Journal(tmp_path)
    transport = Transport(journal, 'https://test/', httpx.Client(base_url='https://test/',
        transport=httpx.MockTransport(lambda _:httpx.Response(400,json=['bad']))))
    try:
        with pytest.raises(ProviderError, match='HTTP 400'):
            transport.request('POST','interactions',payload={})
    finally:
        transport.close(); journal.close()


def test_legacy_stats_and_incomplete_utf8_tail(tmp_path):
    row={'kind':'api_response','index':1,'status':200,
         'usage':{'prompt_tokens':100,'completion_tokens':30,'prompt_cache_hit_tokens':60}}
    (tmp_path/'events.jsonl').write_bytes(json.dumps(row).encode()+b'\n{"unfinished":"\xd0')
    report=read_usage(tmp_path)
    assert report['total']['requests']==1
    assert report['by_purpose']['unclassified']['tokens']['total_tokens']==130
    assert report['total']['cache_ratio']==.6

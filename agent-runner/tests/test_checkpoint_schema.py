import copy

import httpx
import pytest
from jsonschema import Draft202012Validator

from astrabridge_runner.checkpoint_schema import SCHEMA, output_schema
from astrabridge_runner.providers.deepseek import DeepSeek
from astrabridge_runner.providers.gemini import Gemini
from astrabridge_runner.providers.grok import Grok
from astrabridge_runner.providers.openai import OpenAI
from astrabridge_runner.journal import Journal
from astrabridge_runner.types import ProviderError


@pytest.mark.parametrize('provider',[DeepSeek,Grok,Gemini,OpenAI])
def test_checkpoint_api_formats_share_schema_and_have_no_tools(tmp_path,provider):
    journal=Journal(tmp_path)
    if provider is OpenAI:
        from types import SimpleNamespace
        auth=SimpleNamespace(resolve=lambda _: {'id':'test'},close=lambda:None)
        api=provider(auth,journal,'gpt-6-luna','low')
    else:
        api=provider('test-key',journal)
    try:
        original=copy.deepcopy(SCHEMA)
        ordinary=api.payload('rules',[],[],checkpoint=False)
        payload=api.payload('rules',[],[{'unused':'must not be converted'}],checkpoint=True)
        if provider is Gemini:
            assert 'response_format' not in ordinary
            fmt=payload['response_format']
            assert fmt['mime_type']=='application/json'
        else:
            assert 'text' not in ordinary
            fmt=payload['text']['format']
            assert fmt['type']=='json_schema'
            assert (fmt.get('strict') is True) == (provider is not DeepSeek)
        assert fmt['schema']==output_schema()
        Draft202012Validator.check_schema(fmt['schema'])
        assert SCHEMA==original
        assert 'tools' not in payload
        assert payload.get('tool_choice',payload.get('generation_config',{}).get('tool_choice')) in (None,'none')
    finally:
        api.close();journal.close()


def test_old_deepseek_session_rejected_explicitly(tmp_path):
    journal=Journal(tmp_path)
    api=DeepSeek('test-key',journal,client=httpx.Client())
    try:
        with pytest.raises(ProviderError,match='Start a new runner session'):
            api.restore_session_state({})
        api.restore_session_state(api.session_state())
    finally:
        api.close();journal.close()


def test_openai_checkpoint_uses_final_answer_and_keeps_commentary(tmp_path):
    import json
    from astrabridge_runner.compaction import Compactor
    from types import SimpleNamespace
    from test_openai import Auth
    checkpoint={'goal':'test','plan':[],'facts':[],'uncertainties':[],
                'failed_attempts':[],'pending_actions':[],'references':[]}
    commentary={'type':'message','role':'assistant','phase':'commentary',
                'content':[{'type':'output_text','text':'Let me summarize.'}]}
    final={'type':'message','role':'assistant','phase':'final_answer',
           'content':[{'type':'output_text','text':json.dumps(checkpoint)}]}
    event={'type':'response.completed','response':{'status':'completed','output':[commentary,final],
                                                'usage':{'input_tokens':100,'output_tokens':50}}}
    journal=Journal(tmp_path)
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,content='data: '+json.dumps(event)+'\n\n')
    api=OpenAI(Auth(),journal,'gpt-6-luna','low',client=httpx.Client(base_url='https://api.openai.com/v1/',
                                                               transport=httpx.MockTransport(handler)))
    try:
        assert Compactor(api,journal).create(SimpleNamespace(instructions='rules',payload=lambda:[]))==checkpoint
        assert len(calls)==1
        record=next(r for r in journal.records() if r['kind']=='checkpoint_response')
        assert record['native']==[commentary,final]
        assert journal.usage.snapshot()['by_purpose']['checkpoint']['requests']==1
    finally:
        api.close();journal.close()

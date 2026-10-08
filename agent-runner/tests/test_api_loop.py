import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from astrabridge_runner.providers.deepseek import DeepSeek
from astrabridge_runner.types import ProviderError as APIError
from astrabridge_runner.runner import Runner


def call(name,args,identifier='call'):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


def reply(number,calls=None,content=None):
    message={'role':'assistant','content':content,'reasoning_content':f'Full reasoning {number}'}
    if calls is not None:message['tool_calls']=calls
    return {'model':'deepseek-flash','choices':[{'message':message,'finish_reason':'tool_calls' if calls else 'stop'}],
        'usage':{'prompt_tokens':100+number,'completion_tokens':20,'prompt_cache_hit_tokens':50},
        'debug_echo':'secret-test-key'}


class FakeDeepSeek:
    def __init__(self,replies):
        self.replies=list(replies);self.requests=[];self.headers=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                assert self.path=='/models'
                self.send({'data':[{'id':'deepseek-flash','name':'DeepSeek-V4.1-Flash',
                    'context_window':1048576,'input_modalities':['text','image'],'effort':{'supported_levels':['low','high','max']}}]})
            def do_POST(self):
                assert self.path=='/chat/completions'
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(payload);owner.headers.append(dict(self.headers))
                self.send(owner.replies.pop(0))
            def send(self,value):
                data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('x-request-id','available-request-id');self.end_headers();self.wfile.write(data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()


def image_parts(request):
    return [part for m in request['messages'] if isinstance(m['content'],list) for part in m['content'] if part['type']=='image_url']


def test_complete_native_loop_preserves_text_reasoning_and_only_one_image(fixture):
    f=fixture
    responses=[
        reply(0,[call('read_skill_reference',{'reference':'navigation'},'doc')]),
        reply(1,[call('astra_observe',{},'frame')]),
        reply(2,[call('astra_act',{'move':1,'seconds':.2},'move')]),
        reply(3,[call('astra_act',{'move':1},'batch1'),call('astra_look',{'heading_deg':90},'batch2')]),
        reply(4,[call('astra_observe',{},'frame')]), # Providers may reuse call IDs across separate responses.
        reply(5,[call('view_saved_image',{'image_ref':'image_000001'},'old')]),
        reply(6,content='First goal done.'),reply(7,[call('astra_status',{'player':True},'status')]),
        reply(8,content='Second goal done.'),
    ]
    server=FakeDeepSeek(responses);api=DeepSeek('secret-test-key',f['journal'],server.url)
    output=[];runner=Runner(f['skill'],f['journal'],api,output=output.append,image_limit=1)
    try:
        runner.prepare();runner.turn('First goal');runner.turn('Second goal')
        assert output==['First goal done.','Second goal done.']
        assert len(server.requests)==9
        for i,request in enumerate(server.requests):
            assert request['model']=='deepseek-flash' and request['reasoning_effort']=='max'
            assert request['thinking']=={'type':'enabled'} and request['tool_choice']=='auto'
            assert not request['stream'] and len(image_parts(request))<=1
            previous=[m['reasoning_content'] for m in request['messages'] if m['role']=='assistant']
            assert previous==[f'Full reasoning {j}' for j in range(i)]
            assert all('invocation' not in t['function'] for t in request['tools'])
        assert image_parts(server.requests[3])[0]==image_parts(server.requests[2])[0]
        assert image_parts(server.requests[5])[0]!=image_parts(server.requests[2])[0]
        assert image_parts(server.requests[6])[0]==image_parts(server.requests[2])[0]
        assert any('Second goal' in m['content'] for m in server.requests[-1]['messages'] if isinstance(m['content'],str))
        text=json.dumps(server.requests[-1]['messages'])
        assert 'do not cut' in text and 'summary' in text and 'motion' in text and 'feedback' in text
        assert 'multiple_tool_calls_not_supported' in text and 'Historical' in text
        executed=[json.loads(x) for x in (f['root']/'calls.jsonl').read_text().splitlines()]
        assert sum(c['args'][:2]==['game','act'] for c in executed)==1
        assert not any(c['args'][:2]==['game','look'] for c in executed)
        assert all(not c['has_key'] for c in executed)
    finally:runner.close();server.close()
    for path in f['journal'].root.rglob('*'):
        if path.suffix=='.gz':content=gzip.open(path,'rt').read()
        elif path.is_file() and path.suffix in ('.json','.jsonl'):content=path.read_text()
        else:continue
        assert 'secret-test-key' not in content
    records=[json.loads(gzip.open(p,'rt').read()) for p in sorted((f['journal'].root/'api').glob('*response*'))]
    assert records[-1]['body']['usage']['prompt_tokens']==108


def test_unknown_tools_and_invalid_arguments_are_returned_as_native_results(fixture):
    f=fixture;server=FakeDeepSeek([reply(0,[call('run_shell',{'command':'bad'})]),
        reply(1,[call('astra_act',{'move':20})]),reply(2,content='Reported tool errors.')])
    runner=Runner(f['skill'],f['journal'],DeepSeek('secret-test-key',f['journal'],server.url))
    try:
        runner.prepare();runner.turn('test')
        results=[json.loads(m['content']) for m in server.requests[-1]['messages'] if m['role']=='tool']
        assert [r['error'] for r in results]==['unknown_tool','invalid_tool_arguments']
        assert not any(json.loads(x)['args'][0]=='game' for x in (f['root']/'calls.jsonl').read_text().splitlines())
    finally:runner.close();server.close()


def test_context_error_keeps_history_without_compaction(fixture):
    f=fixture;api=DeepSeek('secret-test-key',f['journal'])
    def handler(request):
        return httpx.Response(400,json={'error':{'message':'context length exceeded'}})
    api.client.close();api.http.client=httpx.Client(transport=httpx.MockTransport(handler),base_url='https://api.deepseek.com/')
    try:
        history=[{'role':'user','content':'The full goal and observations.'}]
        with pytest.raises(APIError,match='HTTP 400'):api.complete('Rules',history,[])
        assert history==[{'role':'user','content':'The full goal and observations.'}]
        data=json.loads(gzip.open(next((f['journal'].root/'api').glob('*request*')),'rt').read())
        assert data['body']['messages'][1:]==history
    finally:api.close()


def test_another_owner_ends_runner_without_using_the_other_connection(fixture):
    f=fixture;server=FakeDeepSeek([reply(0,[call('astra_act',{'move':1,'seconds':.2})])])
    runner=Runner(f['skill'],f['journal'],DeepSeek('secret-test-key',f['journal'],server.url),output=lambda _:None)
    try:
        runner.prepare()
        state_file=f['root']/'state.json';state=json.loads(state_file.read_text())
        state['owner']={'mode':'agent','name':'Another agent'};state_file.write_text(json.dumps(state))
        original=(f['skill']/'installation.json').read_text()
        runner.turn('test')
        assert runner.stopped and not runner.bridge.owned
        assert not any(json.loads(x)['args'][:2]==['game','act'] for x in (f['root']/'calls.jsonl').read_text().splitlines())
        assert (f['skill']/'installation.json').read_text()==original
        assert runner.bridge.prefix[2]!=runner.bridge.original_prefix[2]
    finally:runner.close();server.close()
    assert json.loads(state_file.read_text())['owner']['name']=='Another agent'


def test_a_failed_owner_query_still_releases_the_confirmed_private_connection(fixture):
    f=fixture;server=FakeDeepSeek([reply(0,[call('astra_observe',{})])])
    runner=Runner(f['skill'],f['journal'],DeepSeek('secret-test-key',f['journal'],server.url),output=lambda _:None)
    try:
        runner.prepare()
        runner.bridge.check_connection=lambda:{'ok':False,'error':'connection_unavailable','result_unknown':True}
        runner.turn('test')
        assert runner.stopped and runner.bridge.owned
    finally:runner.close();server.close()
    assert json.loads((f['root']/'state.json').read_text())['owner']['mode']=='idle'

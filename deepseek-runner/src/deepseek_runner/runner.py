import hashlib
import json

from jsonschema import Draft202012Validator

from .bridge import Bridge, BridgeFailure, load_json
from .history import History
from .resources import Resources, RESOURCE_TOOLS, ResourceFailure


class Runner:
    def __init__(self,skill,journal,api,executable=None,output=print):
        self.journal=journal;self.api=api;self.output=output;self.stopped=False
        self.bridge=Bridge(skill,journal,executable);self.resources=Resources(skill,journal)
        self.resource_validators={t['function']['name']:Draft202012Validator(t['function']['parameters']) for t in RESOURCE_TOOLS}
        self.history=None;self.definitions=[]

    def prepare(self):
        catalog=self.bridge.load_tools();model=self.api.check_model()
        connected=self.bridge.connect()
        text=(self.bridge.skill/'SKILL.md').read_text(encoding='utf-8')
        if text.startswith('---\n'):text=text.split('---',2)[2].lstrip()
        self.journal.event('skill',sha256=hashlib.sha256(text.encode()).hexdigest(),references=sorted(self.resources.references))
        context={'profile':connected.get('profile'),'working_memory':connected.get('working_memory'),
                 'environment':catalog.get('release'),'model':model.get('name')}
        self.history=History(text+'\n\nSession context:\n'+json.dumps(context,ensure_ascii=False),self.journal,self.resources)
        self.definitions=[{'type':'function','function':{'name':t['name'],'description':t['description'],
                           'parameters':t['input_schema'],'strict':False}} for t in catalog['tools']]+RESOURCE_TOOLS
        return context

    def dispatch(self,call):
        name=call['function']['name'];arguments=call['function']['arguments'];call_id=call['id']
        connection=self.bridge.check_connection()
        if connection:return connection,None
        if name in self.resource_validators:
            try:
                args=load_json(arguments)
                error=next(iter(self.resource_validators[name].iter_errors(args)),None)
                if error:return {'ok':False,'error':'invalid_tool_arguments','message':error.message},None
                if name=='read_skill_reference':return self.resources.read_reference(args['reference']),None
                return self.resources.saved_image(args['image_ref'])
            except (ValueError,OSError,TypeError) as exc:return {'ok':False,'error':'resource_unavailable','message':str(exc)},None
        result=self.bridge.call(name,arguments,call_id)
        return self.resources.collect(result,self.bridge.image_roots,call_id)

    def turn(self,text):
        self.history.user(text);self.journal.event('user',text=text)
        while not self.stopped:
            response=self.api.complete(self.history.payload(),self.definitions)
            choice=response.get('choices',[{}])[0];message=choice.get('message')
            if not isinstance(message,dict):raise BridgeFailure('DeepSeek did not return an assistant message.')
            calls=message.get('tool_calls') or []
            if not isinstance(calls,list) or any(not isinstance(c,dict) or not isinstance(c.get('id'),str)
                or c.get('type')!='function' or not isinstance(c.get('function'),dict)
                or not isinstance(c['function'].get('name'),str) or not isinstance(c['function'].get('arguments'),str) for c in calls):
                raise BridgeFailure('DeepSeek returned malformed native tool calls.')
            self.history.assistant(message)
            self.journal.event('assistant',message=message,usage=response.get('usage'),model=response.get('model'),finish_reason=choice.get('finish_reason'))
            if message.get('content'):self.output(message['content'])
            if not calls:return message
            if len(calls)!=1:
                for call in calls:self.history.tool(call['id'],{'ok':False,'error':'multiple_tool_calls_not_supported',
                    'message':'Make one tool call per response. No tools from this batch were executed.'})
                self.journal.event('batch_rejected',calls=calls);continue
            call=calls[0]
            result,image=self.dispatch(call)
            self.journal.event('model_tool_result',call_id=call['id'],name=call['function']['name'],result=result,image_ref=image)
            self.history.tool(call['id'],result)
            if image:self.history.image(image,call['id'],result.get('historical',False))
            if result.get('error') in ('user_requested_stop','agent_not_connected','connection_unavailable'):
                self.stopped=True
                if result['error']!='connection_unavailable':self.bridge.owned=False
                self.output('The host deliberately stopped this session.' if result['error']=='user_requested_stop' else 'The agent connection ended.');return None

    def close(self):
        self.bridge.disconnect();self.api.close()
        self.journal.event('runner_stopped');self.journal.close()

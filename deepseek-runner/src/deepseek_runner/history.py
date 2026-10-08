import copy

from .journal import json_text


class History:
    """Canonical full text plus image references; only images are projected out."""
    def __init__(self,system,journal,resources):
        self.messages=[{'role':'system','content':system}];self.journal=journal;self.resources=resources
        self.persist()

    def persist(self):self.journal.write('history.json',self.messages)
    def user(self,text):self.messages.append({'role':'user','content':text});self.persist()

    def assistant(self,message):
        value={k:copy.deepcopy(v) for k,v in message.items() if k in ('role','content','reasoning_content','tool_calls')}
        value['role']='assistant';self.messages.append(value);self.persist()

    def tool(self,call_id,result):
        self.messages.append({'role':'tool','tool_call_id':call_id,'content':json_text(result)});self.persist()

    def image(self,ref,call_id,historical=False):
        caption=('Historical image' if historical else 'Image')+f' {ref}, returned with tool call {call_id}.'
        self.messages.append({'role':'user','content':[{'type':'text','text':caption},
                              {'type':'saved_image','image_ref':ref}]});self.persist()

    def payload(self):
        latest=None
        for i,message in enumerate(self.messages):
            if isinstance(message.get('content'),list):
                for j,part in enumerate(message['content']):
                    if part.get('type')=='saved_image':latest=(i,j)
        result=[]
        for i,message in enumerate(self.messages):
            message=copy.deepcopy(message)
            if isinstance(message.get('content'),list):
                parts=[]
                for j,part in enumerate(message['content']):
                    if part.get('type')=='saved_image':
                        if (i,j)==latest:parts.append(self.resources.content(part['image_ref']))
                    else:parts.append(part)
                message['content']=parts
            result.append(message)
        return result

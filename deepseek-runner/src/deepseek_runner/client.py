import time
from urllib.parse import urlparse

import httpx

from .journal import json_text


class APIError(RuntimeError):pass


class DeepSeek:
    def __init__(self,key,journal,base_url='https://api.deepseek.com',model='deepseek-flash'):
        parsed=urlparse(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:raise APIError('API endpoint must not contain credentials, query parameters or fragments.')
        if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise APIError('Use HTTPS for the DeepSeek endpoint.')
        self.journal=journal;self.model=model;self.sequence=0
        self.client=httpx.Client(base_url=base_url.rstrip('/')+'/',headers={'Authorization':'Bearer '+key},
                                 timeout=httpx.Timeout(600,connect=10,write=30,pool=30))

    def request(self,method,path,payload=None):
        if payload is not None and len(json_text(payload).encode())>48*1024*1024:
            raise APIError('The complete API request exceeds the body limit. History was retained; no compaction was performed.')
        for attempt in range(3):
            self.sequence+=1;index=self.sequence;start=time.monotonic()
            record=self.journal.api_record(index,'request',{'method':method,'path':path,'body':payload})
            self.journal.event('api_request',index=index,attempt=attempt+1,record=record)
            try:response=self.client.request(method,path,json=payload)
            except httpx.TransportError as exc:
                self.journal.api_record(index,'response',{'error':str(exc),'elapsed':time.monotonic()-start})
                if attempt<2:time.sleep(2**attempt);continue
                raise APIError('DeepSeek request failed; the session history was retained.') from exc
            try:body=response.json()
            except ValueError:body={'invalid_json_response':response.text}
            headers={k:v for k,v in response.headers.items() if k in ('x-request-id','request-id','retry-after') or k.startswith('x-ratelimit')}
            record=self.journal.api_record(index,'response',{'status':response.status_code,'headers':headers,'body':body,'elapsed':time.monotonic()-start})
            self.journal.event('api_response',index=index,status=response.status_code,record=record,usage=body.get('usage') if isinstance(body,dict) else None)
            if response.status_code in (429,500,502,503,504) and attempt<2:time.sleep(2**attempt);continue
            if not response.is_success:raise APIError(f'DeepSeek returned HTTP {response.status_code}: '+json_text(body))
            if not isinstance(body,dict) or 'invalid_json_response' in body:raise APIError('DeepSeek returned an invalid JSON response.')
            return body
        raise APIError('DeepSeek retries exhausted.')

    def check_model(self):
        models=self.request('GET','models')
        info=next((m for m in models.get('data',[]) if m.get('id')==self.model),None)
        if not info:raise APIError('The requested model is not advertised by this DeepSeek endpoint.')
        if self.model=='deepseek-flash' and info.get('name')!='DeepSeek-V4.1-Flash':
            raise APIError('The default alias is not identified as DeepSeek-V4.1-Flash. Check the model version before running this benchmark.')
        if 'image' not in info.get('input_modalities',[]):raise APIError('The selected model does not advertise image input.')
        if 'max' not in info.get('effort',{}).get('supported_levels',[]):raise APIError('The selected model does not advertise max reasoning effort.')
        self.journal.event('model',requested=self.model,advertised=info,reasoning_effort='max');return info

    def complete(self,messages,tools):
        return self.request('POST','chat/completions',{'model':self.model,'messages':messages,'tools':tools,
            'tool_choice':'auto','stream':False,'thinking':{'type':'enabled'},'reasoning_effort':'max'})

    def close(self):self.client.close()

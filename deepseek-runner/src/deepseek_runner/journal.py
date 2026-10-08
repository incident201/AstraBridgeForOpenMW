import gzip
import json
import os
import time
import uuid
from pathlib import Path


def json_text(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


class Journal:
    """Private, lossless text/HTTP records. Credentials are never log fields."""
    def __init__(self,parent,secret=''):
        self.root=Path(parent)/f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}'
        self.root.mkdir(parents=True,mode=0o700)
        self.secret=secret;self.sequence=0
        for name in ('api','images'): (self.root/name).mkdir(mode=0o700)
        fd=os.open(self.root/'events.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        self.events=os.fdopen(fd,'w',encoding='utf-8')

    def clean(self,value):
        if isinstance(value,str):return value.replace(self.secret,'[REDACTED]') if self.secret else value
        if isinstance(value,list):return [self.clean(v) for v in value]
        if isinstance(value,dict):return {k:self.clean(v) for k,v in value.items() if k.lower() not in {'authorization','api_key','deepseek_api_key'}}
        return value

    def event(self,kind,**data):
        self.sequence+=1
        value={'sequence':self.sequence,'time':time.time(),'kind':kind,**data}
        self.events.write(json_text(self.clean(value))+'\n');self.events.flush();os.fsync(self.events.fileno())

    def write(self,name,value):
        path=self.root/name;temporary=path.with_suffix(path.suffix+'.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(json_text(self.clean(value)));f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)

    def api_record(self,index,side,value):
        path=self.root/'api'/f'{index:06}-{side}.json.gz'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as raw:
            with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as out:out.write(json_text(self.clean(value)).encode())
            raw.flush();os.fsync(raw.fileno())
        return str(path.relative_to(self.root))

    def close(self):self.events.close()

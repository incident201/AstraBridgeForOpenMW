import json
import os
from pathlib import Path

import pytest

from astra_daemon.commands import tools_catalog
from astra_daemon.api_skill import build_api_skill
from deepseek_runner.journal import Journal
from deepseek_runner.bridge import Bridge


@pytest.fixture
def fixture(tmp_path):
    if os.name!='posix':pytest.skip('Executable fake fixture uses a POSIX shebang; the runner itself also supports native Windows executables.')
    source=Path(__file__).resolve().parents[2]/'skill'
    skill=tmp_path/'skill';build_api_skill(source,skill)
    storage=tmp_path/'storage';(storage/'exports/default').mkdir(parents=True)
    cfg=tmp_path/'installation.json';cfg.write_text(json.dumps({'storageDirectory':str(storage)}))
    tools=tools_catalog();tools['release']={'version':'test','digest':'test'}
    (tmp_path/'tools.json').write_text(json.dumps(tools))
    program=tmp_path/'fake bridge';program.write_text('''#!/usr/bin/env python3
import json,os,sys,time,struct,zlib
from pathlib import Path
root=Path(__file__).parent
args=sys.argv[1:];i=args.index('--config');args=args[:i]+args[i+2:]
with (root/'calls.jsonl').open('a') as f:f.write(json.dumps({'args':args,'has_key':'DEEPSEEK_API_KEY' in os.environ})+'\\n')
state_file=root/'state.json';state=json.loads(state_file.read_text()) if state_file.exists() else {'images':0,'moves':0}
def emit(result):print(json.dumps({'ok':True,'result':result}));state_file.write_text(json.dumps(state));sys.exit(0)
if args[:2]==['agent','tools']:emit(json.loads((root/'tools.json').read_text()))
if args==['status']:emit({'storageDirectory':str(root/'storage'),'runtime':{'owner':{'mode':'idle'}}})
if args[:2]==['agent','connect']:
 state['owner']={'mode':'agent','name':args[args.index('--name')+1]};emit({'profile':{'id':'default','name':'Fixture'}})
if args==['agent','status']:emit(state.get('owner',{'mode':'idle','name':None}))
if args==['agent','disconnect']:
 state['owner']={'mode':'idle','name':None};emit({'disconnected':True})
op=args[1]
if op=='observe':
 state['images']+=1
 def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
 pixels=bytes([0,state['images']%256,0,0])
 png=b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
 path=root/'storage/exports/default'/('image-'+str(state['images'])+'.png');path.write_bytes(png)
 emit({'observation':state['images'],'state':'running','screenshot':str(path),'diagnostics':{'keep':'all text'}})
if op=='act':
 state['moves']+=1
 emit({'action':{'reason':'duration','motion':{'forward_m':.2}},'feedback':{'status':'succeeded','events':[]},'summary':{'termination':'duration'},'diagnostics':'do not cut'})
if op=='slow':time.sleep(5)
if op=='bad':print('partial JSON');sys.exit(1)
emit({'operation':op})
''');program.chmod(0o755)
    (skill/'installation.json').write_text(json.dumps({'interface':'tools','executable':str(program),'config':str(cfg)}))
    journal=Journal(tmp_path/'logs','secret-test-key')
    bridge=Bridge(skill,journal)
    yield {'root':tmp_path,'skill':skill,'journal':journal,'bridge':bridge,'storage':storage,'tools':tools}
    if not journal.events.closed:journal.close()

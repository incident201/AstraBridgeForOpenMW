import base64
import json
import os
import subprocess
import time
import uuid
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator


class BridgeFailure(RuntimeError):
    def __init__(self,message,result=None):
        super().__init__(message);self.result=result


def load_json(text):
    def invalid(value):raise ValueError('Non-finite JSON number: '+value)
    return json.loads(text,parse_constant=invalid)


def invocation(tool,args,request_id):
    """Encode only exported bindings. No command names or gameplay schemas here."""
    binding=tool['invocation'];flags=[];positions=[]
    fields=binding['fields'];option_names=set()
    for field in fields:
        name=field['name']
        if name=='request_id':continue
        if field['options']:option_names.add(name)
        if name not in args:continue
        value=args[name]
        if field['options']:
            if field['type']=='boolean':
                if value:flags.append(field['options'][0])
                elif len(field['options'])>1:flags.append(field['options'][1])
            else:
                values=value if field['array'] else [value]
                for item in values:
                    encoded=json.dumps(item,ensure_ascii=False,allow_nan=False,separators=(',',':')) if field['type']=='json' else str(item)
                    flags.append(field['options'][0]+'='+encoded)
        else:
            if field['type']=='json':value=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
            positions.append(str(value))
    if binding['json_payload']:
        positions=[json.dumps({k:v for k,v in args.items() if k not in option_names},ensure_ascii=False,allow_nan=False,separators=(',',':'))]
    if binding['request_id_option']:flags.append(binding['request_id_option']+'='+request_id)
    return [*binding['argv'],*flags,'--',*positions]


def tool_timeout(tool,args):
    policy=tool['invocation']['timeout']
    duration=args.get(policy.get('duration_field'),policy.get('default_duration',0))
    return policy['base_seconds']+policy.get('duration_multiplier',0)*duration


class Bridge:
    def __init__(self,skill,journal,executable=None):
        self.skill=Path(skill).resolve();self.journal=journal;self.owned=False;self.active=None
        meta=load_json((self.skill/'installation.json').read_text(encoding='utf-8'))
        if meta.get('interface')!='tools':raise BridgeFailure('Export the native-tool skill with --interface tools first.')
        self.prefix=[str(executable or meta['executable']),'--config',meta['config']]
        self.original_prefix=list(self.prefix);self.private=None
        self.agent_name='DeepSeek 4.1 Flash '+self.journal.root.name
        self.env={k:v for k,v in os.environ.items() if k!='DEEPSEEK_API_KEY'}
        self.tools={};self.validators={};self.image_roots=[];self.status=None

    def run(self,args,timeout=130,original=False):
        prefix=self.original_prefix if original else self.prefix
        start=time.monotonic();process=subprocess.Popen([*prefix,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,env=self.env,shell=False,**({'start_new_session':True} if os.name!='nt' else {}))
        self.active=process
        try:
            try:stdout,stderr=process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill();stdout,stderr=process.communicate()
                self.journal.event('cli',argv=[*prefix,*args],exit_code=process.returncode,stdout=stdout.decode('utf-8','replace'),stderr=stderr.decode('utf-8','replace'),elapsed=time.monotonic()-start,timed_out=True)
                raise BridgeFailure('Tool response timed out; its game result is unknown.',{'ok':False,'error':'tool_result_unknown','result_unknown':True})
        finally:
            if process.poll() is not None:self.active=None
        try:stdout=stdout.decode('utf-8','strict')
        except UnicodeError as exc:
            self.journal.event('cli',argv=[*prefix,*args],exit_code=process.returncode,
                stdout_base64=base64.b64encode(stdout).decode(),stderr_base64=base64.b64encode(stderr).decode())
            raise BridgeFailure('Tool output was not valid UTF-8.',{'ok':False,'error':'invalid_tool_response','result_unknown':True}) from exc
        stderr=stderr.decode('utf-8','replace')
        self.journal.event('cli',argv=[*prefix,*args],exit_code=process.returncode,stdout=stdout,stderr=stderr,elapsed=time.monotonic()-start)
        try:value=load_json(stdout)
        except (ValueError,UnicodeError) as exc:raise BridgeFailure('The tool did not return valid structured output.',{'ok':False,'error':'invalid_tool_response','result_unknown':True}) from exc
        if not isinstance(value,dict) or type(value.get('ok')) is not bool:
            raise BridgeFailure('Invalid tool response envelope.',{'ok':False,'error':'invalid_tool_response','result_unknown':True})
        if process.returncode!=0 and value['ok']:raise BridgeFailure('Tool transport failed after a reply.',{'ok':False,'error':'tool_result_unknown','result_unknown':True})
        return value

    def require(self,args,timeout=130):
        value=self.run(args,timeout)
        if not value['ok']:raise BridgeFailure(str(value.get('message',value.get('error','Tool failed'))),value)
        return value['result']

    def load_tools(self):
        exported=self.require(['agent','tools','--json'])
        if exported.get('schema_version')!=1:raise BridgeFailure('Unsupported AstraBridge tool schema version.')
        for tool in exported['tools']:
            name=tool['name'];binding=tool['invocation']
            if name in self.tools or len(binding['argv'])!=2 or binding['argv'][0]!='game':raise BridgeFailure('Invalid game-tool catalog.')
            Draft202012Validator.check_schema(tool['input_schema'])
            self.tools[name]=tool;self.validators[name]=Draft202012Validator(tool['input_schema'])
        self.journal.write('tools.json',exported)
        self.status=self.require(['status'])
        self.journal.event('installation',status=self.status)
        self.image_roots=[(Path(self.status['storageDirectory'])/'exports').resolve()]
        if self.status.get('updateRequired') or self.status.get('updatePending'):raise BridgeFailure('Finish the matching runtime update before connecting.')
        return exported

    def connect(self):
        if self.status.get('session_end'):raise BridgeFailure('The host deliberately stopped the session. Start it explicitly before connecting.')
        if (self.status.get('runtime') or {}).get('owner',{}).get('mode') in ('agent','manual'):
            raise BridgeFailure('Another controller already owns this session. Release it before connecting.')
        # The public application config is shared with Desktop and other
        # clients. Keep this connection's token separate so a later agent cannot
        # silently lend its token to an old runner. Credentials are not logs.
        self.private=tempfile.TemporaryDirectory(prefix='.connection-',dir=self.journal.root.parent)
        path=Path(self.private.name)/'installation.json'
        data=Path(self.original_prefix[2]).read_bytes()
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:out.write(data)
        self.prefix=[self.original_prefix[0],'--config',str(path)]
        profile=(self.status.get('profile') or (self.status.get('runtime') or {}).get('profile') or {}).get('id')
        args=['agent','connect','--name',self.agent_name]
        if profile:args+=['--profile',profile]
        connected=self.require(args)
        self.owned=True
        profile=connected.get('profile',{}).get('id')
        if profile:self.image_roots=[self.image_roots[0]/profile]
        self.journal.event('connected',result=connected)
        return connected

    def check_connection(self):
        result=self.run(['agent','status'],30,original=True)
        if not result['ok']:return {'ok':False,'error':'connection_unavailable','result_unknown':True}
        info=result['result']
        if info.get('session_end'):
            self.owned=False
            return {'ok':False,'error':'user_requested_stop','session_end':info['session_end']}
        if info.get('mode')!='agent' or info.get('name')!=self.agent_name:
            self.owned=False
            return {'ok':False,'error':'agent_not_connected','message':'This runner no longer owns the agent connection.'}
        return None

    def call(self,name,arguments,call_id):
        if name not in self.tools:return {'ok':False,'error':'unknown_tool'}
        try:
            args=load_json(arguments)
            error=next(iter(self.validators[name].iter_errors(args)),None)
            if error:return {'ok':False,'error':'invalid_tool_arguments','message':error.message,'path':list(error.path)}
        except (ValueError,TypeError) as exc:return {'ok':False,'error':'invalid_tool_arguments','message':str(exc)}
        request_id=uuid.uuid4().hex
        tool=self.tools[name]
        self.journal.event('tool_start',name=name,call_id=call_id,request_id=request_id,arguments=args)
        try:result=self.run(invocation(tool,args,request_id),tool_timeout(tool,args))
        except BridgeFailure as exc:result={**(exc.result or {'ok':False,'error':'tool_transport_failed'}),'request_id':request_id}
        self.journal.event('tool_result',name=name,call_id=call_id,result=result)
        return result

    def disconnect(self):
        if not self.owned:
            if self.active and self.active.poll() is None:self.active.terminate()
            if self.private:self.private.cleanup();self.private=None
            return
        try:
            if self.active:
                active=self.active
                self.run(['game','stop'],30)
                try:active.communicate(timeout=5)
                except subprocess.TimeoutExpired:active.kill();active.communicate()
            result=self.run(['agent','disconnect'],30)
            self.journal.event('disconnected',result=result)
        except Exception as exc:self.journal.event('disconnect_failed',error=str(exc))
        finally:
            self.owned=False
            if self.private:self.private.cleanup();self.private=None

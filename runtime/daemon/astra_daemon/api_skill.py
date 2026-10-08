"""Build a native-tool presentation of the maintained gameplay skill.

Rules and reference prose come from the existing skill. Transport examples and
host setup belong to the host application, not to the model's interface.
"""
import argparse
import re
import shutil
import shlex
import json
from pathlib import Path

from .commands import catalog, tool_name, tools_catalog


def section(text, heading):
    start=text.index('## '+heading+'\n')
    end=text.find('\n## ',start+3)
    return text[start:] if end<0 else text[start:end]


def tool_prose(text):
    commands=catalog()
    definitions={t['invocation']['argv'][1]:t for t in tools_catalog()['tools']}
    def inline(match):
        value=match[1]
        if value.startswith('astrabridge game '):value=value[len('astrabridge game '):]
        elif value.startswith('astrabridge '):return 'host session management'
        base=value.split()[0] if value.strip() else ''
        if base in commands:
            try:values=shlex.split(value)[1:]
            except ValueError:values=value.split()[1:]
            if definitions[base]['invocation']['json_payload'] and values:
                try:payload=json.loads(values[0])
                except ValueError:payload=None
                if isinstance(payload,dict):return '`'+tool_name(base)+'('+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+')`'
            fields=commands[base]['fields'];positional=[f for f in fields if not f['options']]
            props=definitions[base]['input_schema']['properties'];args=[];position=0;index=0
            while index<len(values):
                token=values[index];index+=1
                if token.startswith('--'):
                    field=next((f for f in fields if token in f['options']),None)
                    if not field or field['name'] not in props:continue
                    if field['type']=='boolean':item='false' if len(field['options'])>1 and token==field['options'][1] else 'true'
                    else:
                        if index>=len(values):continue
                        item=values[index];index+=1
                        if props[field['name']].get('type')=='string' and not re.fullmatch(r'[A-Z][A-Z0-9_]*',item):item=json.dumps(item)
                    args.append(field['name']+'='+item)
                elif position<len(positional):
                    field=positional[position];position+=1;spec=props.get(field['name'])
                    if not spec:continue
                    if token in spec.get('enum',[]):item=json.dumps(token)
                    elif re.fullmatch(r'[A-Z][A-Z0-9_]*',token):item=token
                    elif spec.get('type') in ('number','integer') and re.fullmatch(r'-?\d+(?:\.\d+)?',token):item=token
                    else:continue
                    args.append(field['name']+'='+item)
            return '`'+tool_name(base)+('('+', '.join(args)+')' if args else '')+'`'
        if '--' in value:
            return '`'+re.sub(r'--([a-z][a-z-]*)',lambda m:m[1].replace('-','_'),value)+'`'
        return match[0]
    def block(match):
        if match[1].strip()=='json':return match[0]
        if match[1].strip() not in ('sh','bash'):return ''
        examples=[]
        for line in match[2].replace('\\\n',' ').splitlines():
            line=line.strip()
            if line.startswith('astrabridge game '):examples.append(inline(re.fullmatch(r'(.*)',line)))
        return '\n'.join(examples)+'\n' if examples else ''
    text=re.sub(r'```([^\n]*)\n([\s\S]*?)```',block,text)
    # Keep JSON examples (including sequence op names) verbatim.
    parts=re.split(r'(```json\n[\s\S]*?```)',text)
    for i,part in enumerate(parts):
        if part.startswith('```json'):continue
        lines=[]
        for line in part.splitlines():
            line=re.sub(r'All commands follow `astrabridge game`\.?','',line)
            lower=line.lower()
            if any(word in lower for word in ('stdout','stderr','powershell','--help','installation.json')):continue
            if line.startswith('| Application:'):continue
            if 'commands follow' in lower or 'commands below follow' in lower or 'commands follow `astrabridge' in lower:continue
            if 'all commands' in lower and 'astrabridge' in lower:continue
            if line.startswith('Every gameplay command') or line.startswith('Use this reference for argument syntax'):continue
            line=re.sub(r'`([^`]+)`',inline,line)
            if line.startswith('| Syntax'):line=re.sub(r'\| Syntax[^|]*\|','| Tool |',line,count=1)
            line=line.replace('CLI','tool interface').replace('720p screenshot','ordinary 720p screenshot')
            lines.append(line.rstrip())
        parts[i]='\n'.join(lines)
    text='\n'.join(parts)
    text=text.replace('commands.md#keep-outcome-diagnostics-in-wrappers','commands.md#read-responses-correctly')
    text=text.replace('Open returned screenshots with an image-viewing tool; paths alone show no image.',
                      'New screenshots are provided as images automatically; use view_saved_image for an earlier registered frame.')
    text=text.replace('Open returned screenshots with an image-viewing tool',
                      'Use the automatically supplied screenshot')
    return re.sub(r'\n{3,}','\n\n',text).strip()+'\n'


def build_api_skill(source, target):
    if target.exists():shutil.rmtree(target)
    (target/'references').mkdir(parents=True)
    original=(source/'SKILL.md').read_text(encoding='utf-8')
    rules=tool_prose(section(original,'Mandatory gameplay boundaries'))
    loop=tool_prose(section(original,'Observe → act → verify → remember'))
    # Lifecycle is owned by the host; the shared gameplay loop still describes
    # explicit finish-session and ordinary saves, without a host transport recipe.
    loop=loop.replace('Application stop/restart does not\nsave progress automatically.',
                      'The host manages the connection lifecycle.')
    loop=loop.replace('Application stop attempts a save;\nrestart does not save automatically.',
                      'The host manages the connection lifecycle.')
    intro='''---
name: openmw-play-tools
description: "Play Morrowind through the available AstraBridge native tools: observe, navigate, interact, fight, read and remember verified gameplay information. Use for gameplay, not engine development."
---

# Play Morrowind through AstraBridge tools

The host has connected this session to its selected playthrough profile. Use
the directly available `astra_*` functions and their argument schemas. All game
decisions belong to you. Make one tool call at a time and read its actual result
before deciding on a dependent action. Do not invent handles or hidden knowledge.

Tool results are structured objects. Preserve and read their `summary`,
`feedback`, movement diagnostics, errors and observations. `ok:true` confirms a
returned request, not successful gameplay. New screenshots are displayed
automatically. Only the most recently selected image is present in the model
context; earlier text remains. Use `view_saved_image` with a supplied `image_ref`
to see an earlier frame. Historical frames are not current game state.

If `user_requested_stop` is returned, stop taking game actions and notify the
host. Never restart or reconnect behind the user's back. Host installation,
profile selection and runtime configuration are not gameplay tools.

For detailed procedures, call `read_skill_reference` with an ID from this table:

| ID | Read when |
|---|---|
| commands | Response shapes, handles and diagnostics |
| information | Observation, inspection and object recognition |
| navigation | Movement, jumps, falls and learned routes |
| ui | Dialogue, inventory, books, services and repair |
| onboarding | Character creation and blocking tutorial prompts |
| memory | Grounded notes, evidence and working checkpoints |
| sequences | Predictable action compositions and postconditions |
| combat | Weapons, spells and ordinary combat controls |
| maps | Local/world maps, zoom, pan and visible labels |
| recording | Recording and optional spectator commentary |
| session | Save/load, handoff and restricted recovery |

'''
    (target/'SKILL.md').write_text(intro+rules+'\n'+loop,encoding='utf-8')
    for path in sorted((source/'references').glob('*.md')):
        text=path.read_text(encoding='utf-8')
        if path.stem=='commands':
            text='# Command conventions and responses\n\n'+text[text.index('## Read responses correctly'):]
            text=text.split('## Keep outcome diagnostics in wrappers')[0]
        if path.stem=='session':
            text='# Sessions, saves and recovery\n\n'+text[text.index('## Saves and process lifecycle'):]
            text=text.split('### Host GPU configuration')[0]
            text='\n'.join(line for line in text.splitlines() if not line.startswith('| Application:'))
            text='The host manages the selected profile and agent connection. Each profile has isolated saves, Atlas, notes and knowledge.\n\n'+text
        rendered=tool_prose(text)
        (target/'references'/path.name).write_text(rendered,encoding='utf-8')
    # The model receives tool names/argument help, never execution bindings.
    definitions=tools_catalog()['tools']
    help_text='# Available game tools\n\n'
    for tool in definitions:
        help_text+='## '+tool['name']+'\n\n'+tool['description']+'\n\n'
        for name,spec in tool['input_schema']['properties'].items():
            help_text+=f'- `{name}`: '+spec.get('description',spec.get('type','value'))+'\n'
        help_text+='\n'
    (target/'references/tools.md').write_text(help_text,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('target',type=Path)
    args=parser.parse_args();build_api_skill(args.source,args.target)

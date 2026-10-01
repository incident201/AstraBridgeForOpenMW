from __future__ import annotations

import configparser
import json
import os
import re
from pathlib import Path
import time
import uuid

from astra_bridge.protocol import BridgeError

DEFAULTS = {
    'encoding':'win1251', 'data_relative':'Data Files', 'content':[], 'archives':[],
    'delay_tribunal':True, 'difficulty':-100, 'best_attack':True,
    'recording_encoder':'auto', 'vaapi_device':None, 'viewer_quality':'720p30',
    'sound':True, 'graphics':'gpu', 'graphics_gpu':'auto', 'encoding_gpu':'auto', 'screenshot_keep':128,
}


def write_json(path: Path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    os.replace(temporary, path)


class Storage:
    def __init__(self, root: Path, game: Path, installation: Path):
        self.root, self.game, self.installation = root, game, installation
        root.mkdir(parents=True, exist_ok=True)
        for name in ('runtime/screenshots','profile/base','saves','sessions','atlas','recordings','logs'):
            (root/name).mkdir(parents=True, exist_ok=True)
        state = root/'storage.json'
        if not state.exists():
            write_json(state, {'schema':1,'installation_id':uuid.uuid4().hex,'created':time.time()})
        self.state = json.loads(state.read_text())
        if self.state.get('schema') != 1:
            raise BridgeError('unsupported_storage_schema', schema=self.state.get('schema'))
        self.configuration = root/'configuration.json'
        if not self.configuration.exists(): write_json(self.configuration, DEFAULTS)

    def config(self):
        return {**DEFAULTS, **json.loads(self.configuration.read_text())}

    def update(self, changes):
        allowed = set(DEFAULTS)
        if os.environ.get('ASTRA_MODE') == 'development':
            allowed |= {'ffmpeg_binary','engine_binary','engine_libraries'}
        if not isinstance(changes, dict) or changes.keys()-allowed:
            raise BridgeError('invalid_configuration_fields')
        cfg = {**self.config(), **changes}
        if cfg['encoding'] not in ('win1250','win1251','win1252'): raise BridgeError('invalid_encoding')
        if cfg['viewer_quality'] not in ('720p30','1080p60'): raise BridgeError('invalid_viewer_quality')
        if cfg['recording_encoder'] not in ('auto','cpu','vaapi','nvenc'): raise BridgeError('invalid_recording_encoder')
        if type(cfg['screenshot_keep']) is not int or cfg['screenshot_keep']<8:raise BridgeError('invalid_screenshot_keep')
        if type(cfg['difficulty']) is not int or not -500 <= cfg['difficulty'] <= 500:
            raise BridgeError('invalid_difficulty')
        for key in ('best_attack','sound','delay_tribunal'):
            if type(cfg[key]) is not bool: raise BridgeError('invalid_configuration', field=key)
        if cfg['graphics'] not in ('gpu','software'): raise BridgeError('invalid_graphics')
        for field in ('graphics_gpu','encoding_gpu'):
            value=cfg[field]
            if not isinstance(value,str) or value not in (('auto','nvidia') if field=='graphics_gpu' else ('auto',)) and not re.fullmatch(r'pci:[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]',value):
                raise BridgeError('invalid_gpu_selection',field=field)
        if cfg['encoding_gpu']!='auto' and cfg['vaapi_device']:
            raise BridgeError('choose_encoding_gpu_or_vaapi_override')
        if cfg['graphics']=='software' and os.environ.get('ASTRA_MODE')!='development':
            raise BridgeError('software_graphics_requires_development')
        relative = cfg['data_relative']
        if not isinstance(relative,str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise BridgeError('invalid_data_directory')
        for key in ('content','archives'):
            if not isinstance(cfg[key],list) or len(cfg[key])>1024 or any(
                not isinstance(x,str) or not x or any(c in x for c in '\n\r/\\\x00') for x in cfg[key]):
                raise BridgeError('invalid_content_list', field=key)
        device = cfg['vaapi_device']
        if device is not None and (not isinstance(device,str) or not device or '\x00' in device):
            raise BridgeError('invalid_vaapi_device')
        write_json(self.configuration,cfg)
        game_changes={key:cfg[key] for key in ('difficulty','best_attack') if key in changes}
        if game_changes:write_json(self.root/'profile/apply-game-settings.json',game_changes)
        return cfg

    def import_ini(self, encoding, data_relative='Data Files'):
        self.update({'encoding':encoding,'data_relative':data_relative})
        ini_path = next((p for p in self.game.iterdir() if p.name.lower()=='morrowind.ini'), None)
        if not ini_path: return {'imported':False,'reason':'ini_not_found','configuration':self.config()}
        ini = configparser.ConfigParser(interpolation=None, strict=False, allow_no_value=True)
        ini.read_string(ini_path.read_bytes().decode(encoding.replace('win','cp'), errors='strict'))
        def numbered(section, prefix):
            if not ini.has_section(section): return []
            rows=[]
            for key,value in ini[section].items():
                suffix=key[len(prefix):]
                if key.lower().startswith(prefix) and suffix.isdigit() and value:
                    rows.append((int(suffix),value.strip()))
            return [value for _,value in sorted(rows)]
        content = numbered('Game Files','gamefile')
        archives = numbered('Archives','archive')
        cfg=self.update({'content':content,'archives':archives})
        return {'imported':True,'configuration':cfg}

    def prepare_profile(self):
        cfg = self.config()
        data = (self.game / cfg['data_relative']).resolve()
        if not data.is_relative_to(self.game.resolve()) or not data.is_dir():
            raise BridgeError('game_data_directory_missing', data_relative=cfg['data_relative'])
        if not cfg['content']: raise BridgeError('content_list_empty_configure_game')
        names = {p.name.lower():p.name for p in data.iterdir() if p.is_file()}
        def exact(name):
            if name.lower() not in names: raise BridgeError('content_file_missing', filename=name)
            return names[name.lower()]
        template = self.installation/'runtime/templates/openmw.cfg'
        lines=[line for line in template.read_text().splitlines()
               if not line.startswith(('content=','data=','encoding=','fallback-archive='))]
        # A BSA with the master's basename is OpenMW's normal companion archive,
        # not a content/edition inference. Morrowind.ini lists extra archives.
        archives=list(cfg['archives'])
        for content in cfg['content']:
            candidate=str(Path(content).with_suffix('.bsa'))
            if candidate.lower() in names and candidate.lower() not in {x.lower() for x in archives}:
                archives.insert(0,names[candidate.lower()])
        lines += ['content='+exact(x) for x in cfg['content']]
        lines += ['fallback-archive='+exact(x) for x in archives]
        escaped=str(data).replace('&','&&').replace('"','&"')
        lines += [f'data="{escaped}"', 'encoding='+cfg['encoding']]
        base=self.root/'profile/base'
        (base/'openmw.cfg').write_text('\n'.join(lines)+'\n')
        settings=configparser.ConfigParser(interpolation=None,strict=False)
        profile=self.root/'profile/settings.cfg'
        if profile.exists(): settings.read(profile)
        for section in ('Game','Physics'):
            if not settings.has_section(section):settings.add_section(section)
        pending=self.root/'profile/apply-game-settings.json'
        changes=json.loads(pending.read_text()) if pending.exists() else {}
        for key,option in (('difficulty','difficulty'),('best_attack','best attack')):
            if key in changes or not settings.has_option('Game',option):
                settings.set('Game',option,str(cfg[key]).lower())
        settings.set('Physics','async num threads','0')
        for section,values in {'Video':{'fullscreen':'false','window border':'false','resolution x':'1920',
                              'resolution y':'1080','vsync':'false','framerate limit':'60'},
                              'GUI':{'subtitles':'true'}}.items():
            if not settings.has_section(section):settings.add_section(section)
            for key,value in values.items():
                if not settings.has_option(section,key):settings.set(section,key,value)
        with (base/'settings.cfg').open('w') as stream:settings.write(stream)
        # Explicit configuration updates apply at the next engine launch.
        with profile.open('w') as stream:settings.write(stream)
        pending.unlink(missing_ok=True)
        return cfg

#!/usr/bin/env python3
"""Configure only this exported bundle; never edit a user's global OpenMW profile."""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path


def configure(root: Path,data: Path,recordings: Path,encoding='win1251',checkpoint=None):
    installation=root.parent
    if (root/'runtime/bridge.sock').exists():raise ValueError('Stop AstraBridge before configuring it')
    if (data/'Data Files').is_dir():data=data/'Data Files'
    data=data.resolve();recordings=recordings.resolve()
    if any(c in str(data)+str(recordings) for c in ('\n','\r','"')):raise ValueError('Unsupported character in path')
    files={p.name.lower():p.name for p in data.iterdir()} if data.is_dir() else {}
    if 'morrowind.esm' not in files:raise ValueError('Morrowind.esm is missing in the supplied Data Files directory')
    engines=list(installation.glob('openmw-*/openmw.x86_64'))
    if len(engines)!=1:raise ValueError('Extract the matching OpenMW-Astra binary archive beside this harness first')
    template=root/'templates/openmw.cfg'
    lines=[line for line in template.read_text().splitlines() if not line.startswith(('data=','content=','fallback-archive=','encoding='))]
    for name in ('morrowind.esm','tribunal.esm','bloodmoon.esm'):
        if name in files:lines.append('content='+files[name])
    for name in ('morrowind.bsa','tribunal.bsa','bloodmoon.bsa'):
        if name in files:lines.append('fallback-archive='+files[name])
    lines.extend([f'data="{data}"',f'encoding={encoding}'])
    config=installation/'config';config.mkdir(exist_ok=True)
    (config/'openmw.cfg').write_text('\n'.join(lines)+'\n')
    settings='[General]\npreferred locales = ru,en\n[Game]\ndifficulty = -100\nbest attack = true\n[Physics]\nasync num threads = 0\n'
    (config/'settings.cfg').write_text(settings)
    recordings.mkdir(parents=True,exist_ok=True)
    (root/'local-settings.json').write_text(json.dumps({'recordings_dir':str(recordings)},ensure_ascii=False,indent=2)+'\n')
    if checkpoint:
        source=root/'checkpoints'/checkpoint
        if not source.is_dir():raise ValueError('Unknown packaged checkpoint')
        destination=root/'runtime/userdata/saves/Astra_Test'
        destination.mkdir(parents=True,exist_ok=True)
        for save in source.glob('*.omwsave'):
            target=destination/save.name
            if target.exists() and target.read_bytes()!=save.read_bytes():raise ValueError('Refusing to overwrite an existing save')
            if not target.exists():shutil.copy2(save,target)
    return installation


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',required=True,type=Path,help='Morrowind directory or its Data Files directory')
    p.add_argument('--recordings',required=True,type=Path)
    p.add_argument('--encoding',choices=['win1250','win1251','win1252'],default='win1251')
    p.add_argument('--checkpoint',choices=['after-tutorial','main'],help='Optionally import a clean save; omitted for a new game')
    a=p.parse_args()
    try:installation=configure(Path(__file__).resolve().parent,a.data,a.recordings,a.encoding,a.checkpoint)
    except (OSError,ValueError) as e:p.exit(1,str(e)+'\n')
    print(f'Configured {installation}. Next: python3 bootstrap.py --offline; ./astra start')


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Prepare version files; Git operations and publication belong to the workflow."""
import argparse
import json
from pathlib import Path
import re

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('tag');args=parser.parse_args()
match=re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',args.tag)
if not match:raise SystemExit('Version must be vX.Y.Z')
root=Path(__file__).resolve().parents[1];path=root/'VERSION.json'
version=json.loads(path.read_text());current=version['project_version'].split('-')[0]
if tuple(map(int,match.groups()))<tuple(map(int,current.split('.'))):raise SystemExit('Version cannot go backwards')
version['project_version']=args.tag[1:];path.write_text(json.dumps(version,indent=2)+'\n')
for name in ('package.json','package-lock.json'):
    path=root/'desktop'/name;value=json.loads(path.read_text());value['version']=args.tag[1:]
    if 'packages' in value:value['packages']['']['version']=args.tag[1:]
    path.write_text(json.dumps(value,indent=2)+'\n')

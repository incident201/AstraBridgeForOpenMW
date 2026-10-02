#!/usr/bin/env python3
"""Prepare version files; Git operations and publication belong to the workflow."""
import argparse
import json
from pathlib import Path
import re

VERSION=re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


def version_key(value):
    match=VERSION.fullmatch(value)
    if not match:raise ValueError('Version must be X.Y.Z or X.Y.Z-prerelease')
    identifiers=match[4].split('.') if match[4] else []
    if any(part.isdigit() and len(part)>1 and part.startswith('0') for part in identifiers):
        raise ValueError('Numeric prerelease identifiers cannot have leading zeroes')
    return (*map(int,match.group(1,2,3)),not identifiers,
            tuple((0,int(part)) if part.isdigit() else (1,part) for part in identifiers))


def prepare(root,tag):
    if not tag.startswith('v'):raise ValueError('Release tag must start with v')
    requested=version_key(tag[1:]);path=root/'VERSION.json'
    version=json.loads(path.read_text())
    if requested<version_key(version['project_version']):raise ValueError('Version cannot go backwards')
    version['project_version']=tag[1:]
    outputs={path:version}
    for name in ('package.json','package-lock.json'):
        path=root/'desktop'/name;value=json.loads(path.read_text());value['version']=tag[1:]
        if 'packages' in value:value['packages']['']['version']=tag[1:]
        outputs[path]=value
    for path,value in outputs.items():path.write_text(json.dumps(value,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('tag');args=parser.parse_args()
    try:prepare(Path(__file__).resolve().parents[1],args.tag)
    except ValueError as error:raise SystemExit(str(error)) from error


if __name__=='__main__':main()

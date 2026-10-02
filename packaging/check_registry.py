#!/usr/bin/env python3
"""Verify that a release's exact GHCR manifest can be fetched without credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get(url,headers=None):
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers=headers or {}),timeout=30) as response:return response.read()
        except HTTPError as error:
            if error.code not in (429,500,502,503,504) or attempt==3:raise
        except (URLError,TimeoutError):
            if attempt==3:raise
        time.sleep(2**attempt)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('metadata',type=Path);args=parser.parse_args()
    metadata=json.loads(args.metadata.read_text());image=metadata['image'];digest=metadata['digest']
    match=re.fullmatch(r'ghcr\.io/([a-z0-9_.-]+/[a-z0-9_./-]+):[A-Za-z0-9_.-]+',image)
    if not match or not re.fullmatch('sha256:[0-9a-f]{64}',digest):raise SystemExit('Invalid release registry identity')
    repository=match[1]
    try:
        credentials=json.loads(get('https://ghcr.io/token?'+urlencode({'service':'ghcr.io','scope':'repository:'+repository+':pull'})))
        manifest=get('https://ghcr.io/v2/'+repository+'/manifests/'+digest,{
            'Authorization':'Bearer '+credentials['token'],
            'Accept':'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
    except (HTTPError,URLError) as error:
        raise SystemExit(f'Anonymous GHCR access failed ({error}). Set the runtime package visibility to Public before publishing the release.') from error
    if 'sha256:'+hashlib.sha256(manifest).hexdigest()!=digest:raise SystemExit('Registry manifest digest differs from release.json')
    print('Anonymous access verified:',image+'@'+digest)


if __name__=='__main__':main()

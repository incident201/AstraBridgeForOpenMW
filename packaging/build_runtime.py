#!/usr/bin/env python3
"""Build the OCI runtime locally or in CI; never push an image or a Git ref."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

from source_cache import engine_files
from workspace import check_workspace, environment, podman

ROOT=Path(__file__).resolve().parents[1]
NATIVE='openmw-source/openmw-openmw-0.51.0'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(path):
    result=hashlib.sha256()
    for item in sorted(path.rglob('*')):
        if item.is_file() and '__pycache__' not in item.parts:
            result.update(str(item.relative_to(path)).encode()+b'\0');result.update(item.read_bytes())
    return result.hexdigest()


def sync_source(source,destination,receipt):
    previous=json.loads(receipt.read_text()) if receipt.exists() else []
    current=[]
    for path in source.rglob('*'):
        if not path.is_file():continue
        relative=path.relative_to(source);current.append(relative.as_posix());target=destination/relative
        if target.exists() and target.read_bytes()==path.read_bytes():continue
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    # Keep FetchContent's generated source directories and build timestamps.
    for name in set(previous)-set(current):(destination/name).unlink(missing_ok=True)
    receipt.write_text(json.dumps(current))


def download(descriptor,path):
    if path.exists() and sha(path)==descriptor['sha256']:return
    print(f'Download: {descriptor["url"]} -> {path}',flush=True)
    temporary=path.with_suffix(path.suffix+'.partial')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(descriptor['url'],timeout=60) as source,temporary.open('wb') as target:
                shutil.copyfileobj(source,target)
            if sha(temporary)!=descriptor['sha256']:raise ValueError('Dependency checksum mismatch: '+path.name)
            temporary.replace(path);return
        except (OSError,TimeoutError):
            if attempt==3:raise
            time.sleep(2**attempt)
        finally:temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--image',default='localhost/astrabridge-runtime:dev')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--cache-builder',action='store_true')
    parser.add_argument('--require-loop',action='store_true',help='Require the selected workspace to be mounted from a loop device')
    parser.add_argument('--no-proxy',action='store_true',help='Do not forward HTTP proxy variables to build containers')
    args=parser.parse_args()
    proxy=['--http-proxy=false'] if args.no_proxy else []
    work=check_workspace(args.work,args.require_loop);env=environment(work);runner=podman(work)
    def run(*command,**kw):return subprocess.run([str(x) for x in command],env=env,check=True,**kw)
    def output(*command):return subprocess.check_output([str(x) for x in command],env=env,text=True).strip()
    recipe=ROOT/'runtime/container/Containerfile'
    builder='localhost/astrabridge-builder:'+hashlib.sha256(recipe.read_bytes().split(b'FROM base AS runtime')[0]).hexdigest()[:16]
    cache=work/'builder-image.tar'
    if args.cache_builder and cache.exists():
        run(*runner,'load','-i',cache,stdout=subprocess.DEVNULL)
    exists=subprocess.run([*runner,'image','exists',builder],env=env).returncode==0
    if not exists:run(*runner,'build',*proxy,'--target','builder','-t',builder,'-f',recipe,ROOT)
    else:print('Reusing pinned local builder image',flush=True)
    if args.cache_builder:run(*runner,'save','-o',cache,builder)
    builder_id=output(*runner,'image','inspect',builder,'--format','{{.Id}}')
    versions=json.loads((ROOT/'runtime/container/versions.json').read_text())
    for key,name in {'ffmpeg':'ffmpeg-9.0.2.tar.xz','mediamtx':'mediamtx_v1.21.1_linux_amd64.tar.gz',
                     'nv_codec_headers':'nv-codec-headers-n13.0.19.0.tar.gz'}.items():
        download(versions[key],work/'downloads'/name)
    commit=output('git','-C',ROOT,'rev-parse','HEAD')
    tag=subprocess.run(['git','-C',str(ROOT),'describe','--exact-match','--tags','HEAD'],capture_output=True,text=True)
    dirty=bool(output('git','-C',ROOT,'status','--porcelain'))
    def inside(*command):
        run(*runner,'run','--rm',*proxy,'-v',f'{ROOT}:/src:ro','-v',f'{work}:/work',
            '-e','TMPDIR=/work/tmp','-e',f'ASTRA_GIT_COMMIT={commit}',
            '-e',f'ASTRA_GIT_TAG={tag.stdout.strip() if tag.returncode==0 and not dirty else ""}',
            builder,*command)
    inputs={'source':tree(ROOT/NATIVE),'native':tree(ROOT/'runtime/native'),'builder':builder_id}
    receipt=work/'build/native-receipt.json';prefix=work/'build/native/engine'
    reusable=False
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        try:reusable=saved['inputs']==inputs and saved['files']==engine_files(prefix)
        except (OSError,KeyError,ValueError):pass
    if reusable:print('Reusing verified OpenMW: native sources and build environment unchanged',flush=True)
    else:
        destination=work/'build/native/openmw-openmw-0.51.0'
        sync_source(ROOT/NATIVE,destination,work/'build/native-source-files.json')
        inside('python3','/src/runtime/native/build_engine.py','--work','/work/build/native','--portable-deps','--jobs',args.jobs)
        receipt.write_text(json.dumps({'inputs':inputs,'files':engine_files(prefix)},indent=2)+'\n')
    inside('python3','/src/packaging/build_ffmpeg.py')
    inside('python3','/src/packaging/stage_runtime.py')
    run(*runner,'build',*proxy,'--target','runtime','-t',args.image,'-f',recipe,work/'image')
    digest=output(*runner,'image','inspect',args.image,'--format','{{.Digest}}')
    version=json.loads((ROOT/'VERSION.json').read_text())
    release={'version':version['project_version'],'image':args.image,'digest':digest,'runtime_api':1,'game_api':1,
             'git_commit':commit,'git_tag':tag.stdout.strip() if tag.returncode==0 and not dirty else None,
             'development':dirty or tag.returncode!=0}
    (work/'dist/release.json').write_text(json.dumps(release,indent=2)+'\n')
    print(json.dumps(release,indent=2))


if __name__=='__main__':main()

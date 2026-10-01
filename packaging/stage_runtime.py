#!/usr/bin/env python3
"""Assemble an OCI context in the builder container, after the native builds."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile

root=Path('/src');work=Path('/work');stage=work/'image/stage'
stage.mkdir(parents=True,exist_ok=True)
native=work/'build/native/engine';engine=stage/'engine';engine.mkdir(exist_ok=True)
for name in ('openmw','defaults.bin','gamecontrollerdb.txt','openmw.cfg'):
    if (native/name).exists():shutil.copy2(native/name,engine/name)
shutil.copytree(native/'resources',engine/'resources',dirs_exist_ok=True)
lib=engine/'lib';lib.mkdir(exist_ok=True)
env={**os.environ,'LD_LIBRARY_PATH':str(native/'lib')}
listing=subprocess.check_output(['ldd',str(native/'openmw')],text=True,env=env)
if 'not found' in listing:raise ValueError(listing)
for name,source in re.findall(r'^\s*(\S+) => (/\S+)',listing,re.M):
    if source.startswith('/work/'):shutil.copy2(source,lib/name)
for name in ('daemon','mod','graphics','templates'):
    shutil.rmtree(stage/'runtime'/name,ignore_errors=True)
    shutil.copytree(root/'runtime'/name,stage/'runtime'/name,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
# Weston 13 headless has no seat; supply one without host /dev/input access.
seat=stage/'runtime/graphics/virtual-seat.so'
flags=subprocess.check_output(['pkg-config','--cflags','--libs','libweston-13'],text=True).split()
subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror','-o',str(seat),
                str(root/'runtime/graphics/virtual-seat.c'),*flags],check=True)
bin=stage/'bin';bin.mkdir(exist_ok=True)
for name in ('ffmpeg','ffprobe'):shutil.copy2(work/'build/ffmpeg-prefix/bin'/name,bin/name)
versions=json.loads((root/'runtime/container/versions.json').read_text())
archive=work/'downloads/mediamtx_v1.21.1_linux_amd64.tar.gz'
if hashlib.sha256(archive.read_bytes()).hexdigest()!=versions['mediamtx']['sha256']:raise ValueError('MediaMTX checksum mismatch')
with tarfile.open(archive) as package:
    with package.extractfile('mediamtx') as src,(bin/'mediamtx').open('wb') as dst:shutil.copyfileobj(src,dst)
(bin/'mediamtx').chmod(0o755)
python=stage/'python'
if not python.exists():subprocess.run(['python3','-m','venv',str(python)],check=True)
subprocess.run([str(python/'bin/python'),'-m','pip','install','--cache-dir','/work/cache/pip','--require-hashes',
                '-r',str(root/'runtime/requirements.lock')],check=True)
shutil.copytree(root/'LICENSES',stage/'LICENSES',dirs_exist_ok=True)
shutil.copy2(root/'openmw-source/openmw-openmw-0.51.0/LICENSE',stage/'LICENSES/OpenMW.txt')
shutil.copy2(root/'VERSION.json',stage/'VERSION.json')
packages=subprocess.check_output(['dpkg-query','-W','-f=${Package}=${Version}\n'],text=True)
(stage/'runtime-packages.txt').write_text(packages)
version=json.loads((root/'VERSION.json').read_text())
manifest={**version,'platform':'linux','architecture':'x86_64','engine_sha256':hashlib.sha256((engine/'openmw').read_bytes()).hexdigest(),
          'runtime_api':1,'game_api':1,'ffmpeg':json.loads((work/'build/ffmpeg-prefix/build.json').read_text()),
          'mediamtx':versions['mediamtx'],'base_image':versions['base_image'],
          'packages_sha256':hashlib.sha256(packages.encode()).hexdigest()}
manifest['ffmpeg'].pop('inputs',None)
for kind,width in (('encoders','6'),('filters','2,3')):
    listing=subprocess.check_output([str(bin/'ffmpeg'),'-hide_banner','-'+kind],text=True,stderr=subprocess.DEVNULL)
    manifest['ffmpeg'][kind]=sorted(set(re.findall(r'^\s*[A-Z.]{'+width+r'}\s+(\S+)',listing,re.M)))
required_encoders={'libx264','h264_vaapi','h264_nvenc','aac','libopus'}
required_filters={'vflip','scale','pad','setsar','format','hwupload','scale_vaapi'}
if not required_encoders.issubset(manifest['ffmpeg']['encoders']) or not required_filters.issubset(manifest['ffmpeg']['filters']):
    raise ValueError('Pinned FFmpeg is missing required encoders or filters')
manifest['git_commit']=os.environ.get('ASTRA_GIT_COMMIT')
manifest['git_tag']=os.environ.get('ASTRA_GIT_TAG') or None
(stage/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Runtime stage:',stage)

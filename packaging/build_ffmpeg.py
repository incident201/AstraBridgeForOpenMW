#!/usr/bin/env python3
"""Build the pinned production FFmpeg inside the runtime builder container."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tarfile

root=Path('/src')
work=Path('/work')
versions=json.loads((root/'runtime/container/versions.json').read_text())
prefix=work/'build/ffmpeg-prefix'
build=work/'build/ffmpeg'
build.mkdir(exist_ok=True)

def unpack(key, filename, dirname):
    archive=work/'downloads'/filename
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=versions[key]['sha256']:
        raise ValueError(f'{filename}: checksum mismatch')
    target=build/dirname
    if not target.exists():
        with tarfile.open(archive) as content: content.extractall(build,filter='data')
    return target

headers=unpack('nv_codec_headers','nv-codec-headers-n13.0.19.0.tar.gz','nv-codec-headers-n13.0.19.0')
subprocess.run(['make','install',f'PREFIX={prefix}'],cwd=headers,check=True)
source=unpack('ffmpeg','ffmpeg-9.0.2.tar.xz','ffmpeg-9.0.2')
env={**os.environ,'PKG_CONFIG_PATH':str(prefix/'lib/pkgconfig')}
flags=[f'--prefix={prefix}','--disable-debug','--disable-doc','--disable-ffplay',
       '--enable-gpl','--enable-version3','--enable-libx264','--enable-libopus','--enable-vaapi','--enable-nvenc',
       '--enable-openssl','--enable-pthreads','--disable-autodetect','--enable-zlib',
       '--enable-libdrm','--enable-xlib','--enable-ffnvcodec']
receipt=prefix/'build.json'
expected={'versions':versions,'configure':flags}
if not receipt.exists() or json.loads(receipt.read_text()).get('inputs')!=expected:
    subprocess.run([str(source/'configure'),*flags],cwd=source,env=env,check=True)
    subprocess.run(['make','-j2'],cwd=source,env=env,check=True)
    subprocess.run(['make','install'],cwd=source,env=env,check=True)
    metadata={'inputs':expected,'version':subprocess.check_output([str(prefix/'bin/ffmpeg'),'-version'],text=True),
              'sha256':hashlib.sha256((prefix/'bin/ffmpeg').read_bytes()).hexdigest()}
    receipt.write_text(json.dumps(metadata,indent=2)+'\n')

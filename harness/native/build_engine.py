#!/usr/bin/env python3
"""Build only OpenMW 0.51.0 + Astra UI. Dependencies stay in a user-owned prefix."""
from pathlib import Path
from urllib.request import urlopen, urlretrieve
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, json, shlex, subprocess, tarfile

parser=argparse.ArgumentParser()
parser.add_argument('--work',type=Path,default=Path.cwd()/'openmw-source')
parser.add_argument('--jobs',type=int,default=2)
parser.add_argument('--arch-deps',action='store_true',help='Download and unpack Arch packages locally; no sudo or installation')
parser.add_argument('--portable-deps',action='store_true',help='Build pinned MyGUI and Recast from source for portable releases')
a=parser.parse_args()
if a.jobs<1:parser.error('--jobs must be positive')
work=a.work.resolve();work.mkdir(parents=True,exist_ok=True)
source=work/'openmw-openmw-0.51.0';archive=work/'openmw-0.51.0.tar.gz'
url='https://codeload.github.com/OpenMW/openmw/tar.gz/refs/tags/openmw-0.51.0'
if not source.exists():
    if not archive.exists():urlretrieve(url,archive)
    with tarfile.open(archive) as tar:tar.extractall(work,filter='data')
if a.arch_deps:
    prefix=work/'deps';prefix.mkdir(exist_ok=True)
    packages=work/'packages';packages.mkdir(exist_ok=True)
    names=['boost','boost-libs','openscenegraph','collada-dom','bullet-dp','sdl2','mygui','openal','ffmpeg','yaml-cpp','luajit','recastnavigation']
    urls=subprocess.check_output(['pacman','-Sp','--print-format','%l',*names],text=True).splitlines()
    def fetch(url):
        filename=url.rsplit('/',1)[1];path=packages/filename
        if not path.exists():
            try:urlretrieve(url,path)
            except Exception:
                # A mirror may have moved since the local pacman database was updated.
                name=filename.rsplit('-',3)[0]
                metadata=json.load(urlopen('https://archlinux.org/packages/extra/x86_64/'+name+'/json/'))
                url='https://geo.mirror.pkgbuild.com/extra/os/x86_64/'+metadata['filename']
                path=packages/metadata['filename'];urlretrieve(url,path)
        return path,{'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    with ThreadPoolExecutor(max_workers=4) as pool: downloads=list(pool.map(fetch,urls))
    for path,_ in downloads:subprocess.run(['bsdtar','-xf',str(path),'-C',str(prefix),'usr'],check=True)
    (work/'dependencies.json').write_text(json.dumps([x for _,x in downloads],indent=2)+'\n')
subprocess.run(['python3',str(Path(__file__).with_name('patch_engine.py')),str(source)],check=True)
prefix=work/'deps/usr'
portable_paths='-march=x86-64 -mtune=generic '+shlex.quote('-ffile-prefix-map='+str(work)+'=astra-build')
args=['cmake','-S',str(source),'-B',str(work/'engine'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
      '-DCMAKE_CXX_FLAGS_RELEASE=-O1 -DNDEBUG','-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
      # __FILE__ and debug diagnostics must not publish the builder's home/workspace.
      '-DCMAKE_CXX_FLAGS='+portable_paths,
      '-DCMAKE_C_FLAGS='+portable_paths,
      '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON','-DCMAKE_INSTALL_RPATH=$ORIGIN/lib',
      '-DOPENMW_USE_SYSTEM_RECASTNAVIGATION='+('OFF' if a.portable_deps else 'ON')]
if a.portable_deps:
    args += ['-DOPENMW_USE_SYSTEM_MYGUI=OFF', '-DOPENMW_USE_SYSTEM_SQLITE3=OFF']
if prefix.exists():
    args += ['-DCMAKE_PREFIX_PATH='+str(prefix),
             '-DCMAKE_EXE_LINKER_FLAGS=-L'+str(prefix/'lib')+' -Wl,-rpath-link,'+str(prefix/'lib'),
             '-DBULLET_COLLISION_LIBRARY='+str(prefix/'lib/libBulletCollision.so'),
             '-DBULLET_MATH_LIBRARY='+str(prefix/'lib/libLinearMath.so')]
for target in ['LAUNCHER','WIZARD','MWINIIMPORTER','OPENCS','ESSIMPORTER','BSATOOL','ESMTOOL','NIFTEST','NAVMESHTOOL','BULLETOBJECTTOOL']:
    args.append('-DBUILD_'+target+'=OFF')
subprocess.run(args,check=True)
subprocess.run(['cmake','--build',str(work/'engine'),'--target','openmw','-j',str(a.jobs)],check=True)
print('Engine:',work/'engine/openmw')
print('Library directory:',prefix/'lib')

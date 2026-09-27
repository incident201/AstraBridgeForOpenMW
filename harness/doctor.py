#!/usr/bin/env python3
"""Read-only preflight for an extracted AstraBridge installation."""
import ctypes,importlib.util,json,os,platform,shutil,subprocess,sys
import importlib.metadata
from pathlib import Path
from astra_bridge.diagnostics import inspect_auto_fixes
from astra_bridge.dependencies import offline_runtime
root=Path(__file__).resolve().parent;errors=[];checks={}
checks['python']=platform.python_version()
checks['offline_runtime']=offline_runtime(root)
if sys.version_info<(3,11):errors.append('Python >= 3.11 required')
for name in ('mss','imageio_ffmpeg','PIL'):
 checks[name]=importlib.util.find_spec(name) is not None
 if not checks[name]:errors.append(f'Missing {name}; run bootstrap.py'+(' --offline' if checks['offline_runtime']['available'] else ' (online; no compatible offline wheel)'))
checks['runtime_versions']={}
for name in ('mss','imageio-ffmpeg','Pillow'):
 try:checks['runtime_versions'][name]=importlib.metadata.version(name)
 except importlib.metadata.PackageNotFoundError:checks['runtime_versions'][name]=None
for name in ('libxcb.so.1','libxcb-composite.so.0','libX11.so.6'):
 try:ctypes.CDLL(name);checks[name]=True
 except OSError:checks[name]=False;errors.append(f'Missing system library {name}')
checks['display']=os.environ.get('DISPLAY');checks['wayland_session']=bool(os.environ.get('WAYLAND_DISPLAY'))
if not checks['display']:errors.append('DISPLAY is missing: run from the graphical KDE/XWayland session')
engines=list(root.parent.glob('openmw-*/openmw.x86_64'))
if len(engines)!=1:errors.append('Matching OpenMW binary archive is not extracted beside this harness')
else:
 engine=engines[0];info=json.loads((engine.parent/'BUILD-INFO.json').read_text())
 required=tuple(map(int,info['minimum_glibc'].split('.')))
 actual=platform.libc_ver()[1]
 checks['glibc']=actual;checks['minimum_glibc']=info['minimum_glibc']
 if not actual or tuple(map(int,actual.split('.')))<required:errors.append('System glibc is older than this build requires')
 env={**os.environ,'LD_LIBRARY_PATH':str(engine.parent/'lib')}
 r=subprocess.run([str(engine),'--version'],env=env,cwd=engine.parent,capture_output=True,text=True)
 checks['engine_version']=(r.stdout+r.stderr).strip()
 if r.returncode:errors.append('Engine cannot load its libraries; see engine_version')
checks['config']=(root.parent/'config/openmw.cfg').is_file()
if not checks['config']:errors.append('Run configure.py with the Morrowind and recording paths')
checks['xdotool']=shutil.which('xdotool') or str(root/'tools/usr/bin/xdotool')
if not Path(checks['xdotool']).is_file():errors.append('xdotool is unavailable')
checks['auto_fixes']=inspect_auto_fixes(root)
print(json.dumps({'ok':not errors,'checks':checks,'errors':errors},ensure_ascii=False,indent=2))
sys.exit(bool(errors))

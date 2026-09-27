#!/usr/bin/env python3
"""Install Python dependencies; optionally unpack Arch X11 test tools locally."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
from astra_bridge.dependencies import offline_runtime

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--headless-local', action='store_true', help='Arch Linux only: unpack Xvfb/xdotool dependencies under tools/')
parser.add_argument('--tests', action='store_true')
parser.add_argument('--offline', action='store_true',help='Install from the packaged wheelhouse without a network connection')
options = parser.parse_args()
python = root / '.venv/bin/python'
if options.offline:
    target = {}
    if python.exists():
        target = json.loads(subprocess.check_output([str(python), '-c',
            'import json,sys,platform,sysconfig; print(json.dumps(dict(version=list(sys.version_info[:2]), '
            'implementation=sys.implementation.name, architecture=platform.machine(), '
            'threaded=bool(sysconfig.get_config_var("Py_GIL_DISABLED")))))'], text=True))
    bundle = offline_runtime(root, **target)
    if not bundle['available']:
        parser.error('Offline runtime wheels unavailable for '+bundle['implementation']+' '+bundle['python']
                     +' '+bundle['abi']+' '+bundle['architecture']+': '+', '.join(bundle['missing'])
                     +'. Use a supported CPython 3.11–3.14 Linux x86_64 interpreter, or run bootstrap.py without --offline.')
    if options.tests:
        parser.error('The bundled wheels cover runtime dependencies; install test dependencies with bootstrap.py --tests (online).')
if not python.exists():
    if shutil.which('uv'):
        subprocess.run(['uv', 'venv', '--python', sys.executable, str(root / '.venv')], check=True)
    else:
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], check=True)
packages = ['-r', str(root / 'requirements.txt')]
if options.offline:
    packages=['--no-index','--find-links',str(root/'wheelhouse'),*packages]
if options.tests:
    packages += ['pytest==9.1.1']
if shutil.which('uv'):
    subprocess.run(['uv', 'pip', 'install', '--python', str(python), *packages], check=True)
else:
    subprocess.run([str(python), '-m', 'pip', 'install', *packages], check=True)

if options.headless_local:
    if not shutil.which('pacman') or not shutil.which('bsdtar'):
        sys.exit('Local package bootstrap is for Arch Linux. Elsewhere use distro Xvfb, xauth and xdotool.')
    tools = root / 'tools'
    tools.mkdir(exist_ok=True)
    urls = subprocess.check_output(['pacman', '-Sp', '--print-format', '%l',
                                    'xorg-server-xvfb', 'xorg-xauth', 'xdotool'], text=True).splitlines()
    def download(url):
        if not url.startswith('https://'):
            raise RuntimeError('Package mirror must use HTTPS')
        path = tools / url.rsplit('/', 1)[1]
        if not path.exists():
            urllib.request.urlretrieve(url, path)
        return path, {'url': url, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(download, urls))
    for path, _ in results:
        subprocess.run(['bsdtar', '-xf', str(path), '-C', str(tools), 'usr'], check=True)
    (tools / 'manifest.json').write_text(json.dumps([r for _, r in results], indent=2)+'\n')
    print('Test tools unpacked locally. No system packages installed.')
print('Ready. Run ./astra start in your graphical X11/XWayland session (normal game window).')
if options.headless_local:print('For this optional test display only: ./astra start --headless --no-sound')

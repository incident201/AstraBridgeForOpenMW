"""Inspect the offline runtime bundle without importing optional dependencies."""
import platform
import re
import sys
import sysconfig
from pathlib import Path


def offline_runtime(root, *, version=None, implementation=None, architecture=None, threaded=None):
    root = Path(root)
    major, minor = version or sys.version_info[:2]
    implementation = implementation or sys.implementation.name
    architecture = architecture or platform.machine()
    if threaded is None:
        threaded = bool(sysconfig.get_config_var('Py_GIL_DISABLED'))
    python_tag = f'cp{major}{minor}'
    abi = python_tag + ('t' if threaded else '')
    wheels = list((root / 'wheelhouse').glob('*.whl'))
    matches, missing = {}, []
    normalize = lambda text: re.sub(r'[-_.]+', '_', text).lower()
    for line in (root / 'requirements.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, release = line.split('==')
        compatible = []
        for wheel in wheels:
            parts = wheel.stem.split('-')
            if len(parts) < 5 or normalize(parts[0]) != normalize(name) or parts[1] != release:
                continue
            py, wheel_abi, target = parts[-3:]
            platform_ok = (sys.platform == 'linux' and any(tag.startswith('manylinux') and tag.endswith('_' + architecture)
                                                          for tag in target.split('.')))
            pure = 'py3' in py.split('.') and wheel_abi == 'none' and (target == 'any' or platform_ok)
            native = (implementation == 'cpython' and python_tag in py.split('.')
                      and abi in wheel_abi.split('.') and platform_ok)
            if pure or native:
                compatible.append(wheel.name)
        if compatible:
            matches[name] = sorted(compatible)[0]
        else:
            missing.append(line)
    return {'available': not missing, 'python': f'{major}.{minor}', 'implementation': implementation,
            'abi': abi if implementation == 'cpython' else implementation,
            'architecture': architecture, 'wheels': matches, 'missing': missing}

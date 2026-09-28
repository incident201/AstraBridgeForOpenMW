#!/usr/bin/env python3
"""Build immutable Linux release assets from a clean tag; no game data is included."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'openmw-source/openmw-openmw-0.51.0'
HOST_LIBRARIES = re.compile(r'^(ld-linux|lib(c|m|mvec|pthread|dl|rt|resolv|util|GL|GLX|GLdispatch|EGL|drm)\.so)')


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def sha256(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
        return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def copy_tracked(directory, destination):
    files = git('ls-files', directory).splitlines()
    for name in files:
        relative = Path(name).relative_to(directory)
        if relative.parts[0] in {'tests', 'native'}:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)


def collect_libraries(binary, destination, search):
    destination.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'LD_LIBRARY_PATH': ':'.join(map(str, search))}
    output = subprocess.check_output(['ldd', str(binary)], env=env, text=True)
    if 'not found' in output:
        raise ValueError('Unresolved runtime libraries:\n' + output)
    for line in output.splitlines():
        match = re.search(r'^\s*(\S+) => (/\S+)', line)
        if match and not HOST_LIBRARIES.match(match[1]):
            target = destination / match[1]
            if not target.exists():
                shutil.copy2(match[2], target)


def cpu_floor(runtime):
    level = 1
    for path in runtime.rglob("*"):
        if not path.is_file(): continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF": continue
        notes = subprocess.check_output(["readelf", "--notes", str(path)], text=True)
        for line in notes.splitlines():
            if "ISA needed:" in line:
                level = max([level] + [int(x) for x in re.findall(r"x86-64-v([234])", line)])
    return "x86-64-baseline" if level == 1 else f"x86-64-v{level}"


def glibc_floor(runtime):
    versions = {(2, 17)}
    for path in runtime.rglob('*'):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        output = subprocess.check_output(['readelf', '--version-info', str(path)], text=True)
        versions.update(tuple(map(int, x.split('.'))) for x in re.findall(r'GLIBC_(\d+\.\d+)', output))
    return '.'.join(map(str, max(versions)))


def wheels(destination, existing):
    destination.mkdir(parents=True)
    if existing:
        for wheel in existing.glob('*.whl'):
            if '-cp3' in wheel.name and '-cp312-' not in wheel.name: continue
            shutil.copy2(wheel, destination / wheel.name)
    else:
        for version in ('312',):
            run(sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--no-deps',
                '--platform', 'manylinux2014_x86_64', '--platform', 'manylinux_2_28_x86_64',
                '--platform', 'manylinux_2_27_x86_64', '--implementation', 'cp',
                '--python-version', version, '--abi', 'cp' + version,
                '-r', ROOT / 'harness/requirements.txt', '-d', destination)
    sys.path.insert(0, str(ROOT / 'harness'))
    from astra_bridge.dependencies import offline_runtime
    for minor in (12,):
        report = offline_runtime(destination.parent, version=(3, minor), implementation='cpython',
                                 architecture='x86_64', threaded=False)
        if not report['available']:
            raise ValueError('Incomplete wheelhouse: ' + str(report))


def wheel_notices(wheelhouse, destination):
    for wheel in wheelhouse.glob('*.whl'):
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                path = Path(name)
                if '..' in path.parts or path.is_absolute():
                    raise ValueError('Unsafe wheel member')
                if not name.endswith('/') and (any(word in path.name.lower() for word in ('license', 'copying', 'notice')) or path.name == 'METADATA'):
                    target = destination / wheel.stem / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))


def python_runtime(runtime, work):
    descriptor = json.loads((ROOT / 'packaging/python-runtime.json').read_text())
    archive = work / 'python-runtime.tar.gz'
    if not archive.exists(): urllib.request.urlretrieve(descriptor['url'], archive)
    if sha256(archive) != descriptor['sha256']: raise ValueError('Python runtime checksum mismatch')
    with tarfile.open(archive, 'r:gz') as tar:
        tar.extractall(runtime, filter='data')
    shutil.copy2(ROOT / 'packaging/python-runtime.json', runtime / 'LICENSES/python-runtime.json')
    # Keep notices shipped by python-build-standalone alongside its interpreter.
    license_file = runtime / 'python/LICENSE'
    if license_file.exists(): shutil.copy2(license_file, runtime / 'LICENSES/Python.txt')
    return descriptor['version']


def run_container(args):
    tool = shutil.which('podman') or shutil.which('docker')
    if not tool: raise ValueError('Install Podman or Docker on the build host; end users do not need either')
    image = 'localhost/astrabridge-builder:' + sha256(ROOT / 'packaging/Containerfile')[:12]
    runner = [tool]
    if args.container_storage:
        if Path(tool).name != 'podman': raise ValueError('--container-storage currently requires Podman')
        runner += ['--root', str(args.container_storage.expanduser().resolve()),
                   '--runroot', f'/run/user/{os.getuid()}/astrabridge-containers']
    build = [*runner, 'build']
    if Path(tool).name == 'podman': build.append('--http-proxy=false')
    cached = subprocess.run([*runner, 'image', 'inspect', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if cached.returncode:
        run(*build, '-t', image, '-f', ROOT / 'packaging/Containerfile', ROOT / 'packaging')
    command = [*runner, 'run', '--rm']
    if Path(tool).name == 'podman': command += ['--userns=keep-id', '--http-proxy=false']
    else: command += ['--user', f'{os.getuid()}:{os.getgid()}']
    command += ['-v', f'{ROOT}:{ROOT}', '-w', str(ROOT), '-e', 'PIP_CACHE_DIR=/tmp/pip-cache']
    forwarded = list(sys.argv[1:])
    for key in ('work', 'output', 'engine_prefix', 'engine_receipt', 'wheelhouse', 'tools_prefix'):
        path = getattr(args, key)
        if path is None: continue
        path = path.expanduser().resolve()
        if key in ('work', 'output'): path.mkdir(parents=True, exist_ok=True)
        mount = path.parent if path.is_file() else path
        if not mount.is_relative_to(ROOT): command += ['-v', f'{mount}:{mount}']
        forwarded += ['--' + key.replace('_', '-'), str(path)]
    run(*command, image, 'python3', ROOT / 'packaging/build_release.py',
        '--host-build', '--portable-deps', *forwarded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--work', type=Path, default=ROOT / '.release-work')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--arch-deps', action='store_true')
    parser.add_argument('--container-storage', type=Path, help='Optional separate Podman storage (for builds on another disk)')
    parser.add_argument('--host-build', action='store_true', help='Explicit native development/build-container mode')
    parser.add_argument('--portable-deps', action='store_true', help='Use pinned source dependencies on the portable builder')
    parser.add_argument('--development', action='store_true', help='Allow an untagged clean commit; never a frozen release')
    parser.add_argument('--engine-prefix', type=Path, help='Reuse an engine/resources/lib directory with a build receipt')
    parser.add_argument('--engine-receipt', type=Path, help='Generated receipt proving engine hash and matching source/native Git trees')
    parser.add_argument('--wheelhouse', type=Path, help='Existing downloaded wheels; otherwise download pinned requirements')
    parser.add_argument('--tools-prefix', type=Path, help='Prefix containing usr/bin/xdotool and its shared libraries')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.uname().machine != 'x86_64':
        parser.error('Build on Linux x86_64')
    if git('status', '--porcelain', '--untracked-files=normal'):
        parser.error('Build from a clean committed checkout')
    if not args.host_build and os.environ.get('ASTRA_BUILD_CONTAINER') != '1':
        if args.arch_deps: parser.error('--arch-deps is only for explicit --host-build development')
        return run_container(args)
    version = json.loads((ROOT / 'VERSION.json').read_text())
    tag = 'v' + version['project_version']
    if not args.development and tag not in git('tag', '--points-at', 'HEAD').splitlines():
        parser.error('HEAD must have tag ' + tag)
    commit = git('rev-parse', 'HEAD')
    source_tree = git('rev-parse', 'HEAD:' + SOURCE)
    native_tree = git('rev-parse', 'HEAD:harness/native')
    args.work = args.work.resolve(); args.work.mkdir(parents=True, exist_ok=True)
    args.output = args.output.resolve()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output directory must be empty; released assets must never be overwritten')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.engine_prefix:
        if not args.engine_receipt:
            parser.error('--engine-prefix requires --engine-receipt')
        prefix = args.engine_prefix.resolve()
        receipt = json.loads(args.engine_receipt.read_text())
        executable = prefix / ('openmw.x86_64' if (prefix / 'openmw.x86_64').exists() else 'openmw')
        if any(receipt.get(k) != v for k, v in {'source_tree': source_tree, 'native_tree': native_tree,
                                               'engine_sha256': sha256(executable)}.items()):
            parser.error('Prebuilt engine receipt does not match this source/native tree and executable')
    else:
        build = args.work / 'build'
        if not (build / 'openmw-openmw-0.51.0').exists():
            shutil.copytree(ROOT / SOURCE, build / 'openmw-openmw-0.51.0')
        else:
            parser.error('Use a fresh --work directory to avoid stale source builds')
        command = [sys.executable, ROOT / 'harness/native/build_engine.py', '--work', build, '--jobs', args.jobs]
        if args.arch_deps: command.append('--arch-deps')
        if args.portable_deps: command.append('--portable-deps')
        run(*command)
        prefix = build / 'engine'
        executable = prefix / 'openmw'
        receipt = {'source_tree': source_tree, 'native_tree': native_tree, 'engine_sha256': sha256(executable),
                   'build_commit': commit}
        write_json(args.work / 'engine-receipt.json', receipt)
    with tempfile.TemporaryDirectory(prefix='bundle-', dir=args.work) as temporary:
        runtime = Path(temporary) / 'AstraOpenMW'; runtime.mkdir()
        engine = runtime / 'engine'; engine.mkdir()
        shutil.copy2(executable, engine / 'openmw')
        for name in ('resources', 'lib'):
            if (prefix / name).exists(): shutil.copytree(prefix / name, engine / name, symlinks=False)
        if not (engine / 'resources').is_dir(): raise ValueError('Engine resources are missing')
        for name in ('defaults.bin', 'gamecontrollerdb.txt', 'openmw.cfg'):
            shutil.copy2(prefix / name, engine / name)
        search = [engine / 'lib', prefix / 'lib', args.work / 'build/deps/usr/lib']
        collect_libraries(engine / 'openmw', engine / 'lib', search)
        # Arch's SDL2 compatibility library dlopens SDL3, so ldd cannot see it.
        sdl2 = engine / 'lib/libSDL2-2.0.so.0'
        if sdl2.is_file() and b'libSDL3.so' in sdl2.read_bytes():
            sdl3 = next((base / 'libSDL3.so.0' for base in [*search, Path('/usr/lib/x86_64-linux-gnu'), Path('/usr/lib')]
                         if (base / 'libSDL3.so.0').is_file()), None)
            if sdl3 is None: raise ValueError('SDL2 compatibility runtime requires libSDL3.so.0')
            shutil.copy2(sdl3, engine / 'lib/libSDL3.so.0')
            collect_libraries(engine / 'lib/libSDL3.so.0', engine / 'lib', search)
        # Only ship the plugins requested by OpenMW, not unrelated optional
        # image/database backends with their own large dependency stacks.
        cmake = (ROOT / SOURCE / 'CMakeLists.txt').read_text()
        plugin_block = re.search(r'set\(USED_OSG_PLUGINS(.*?)\)', cmake, re.S)
        required_plugins = set(plugin_block.group(1).split())
        existing = list((engine / 'lib').glob('osgPlugins-*'))
        if not existing:
            for base in (args.work / 'build/deps/usr/lib', Path('/usr/lib/x86_64-linux-gnu'), Path('/usr/lib')):
                for plugins in base.glob('osgPlugins-*'):
                    destination = engine / 'lib' / plugins.name
                    destination.mkdir(exist_ok=True)
                    for name in required_plugins:
                        path = plugins / (name + '.so')
                        if path.is_file(): shutil.copy2(path, destination / path.name)
        installed = list((engine / 'lib').glob('osgPlugins-*/*.so'))
        if required_plugins - {p.stem for p in installed}:
            raise ValueError('Required OpenMW OSG plugins are missing')
        for plugin in installed:
            if plugin.stem not in required_plugins:
                plugin.unlink()
                continue
            collect_libraries(plugin, engine / 'lib', search)
        # Exercise the packaged loader without a window system. This catches
        # dlopen dependencies (notably SDL3) that a link-time check misses.
        run(engine / 'openmw', '--version', cwd=engine,
            env={**os.environ, 'LD_LIBRARY_PATH': str(engine / 'lib'), 'SDL_VIDEODRIVER': 'dummy'})
        copy_tracked('harness', runtime / 'AstraBridge')
        copy_tracked('skill', runtime / 'skill/openmw-play')
        copy_tracked('LICENSES', runtime / 'LICENSES')
        shutil.copy2(ROOT / 'LICENSE', runtime / 'LICENSES/GPL-3.0.txt')
        shutil.copy2(ROOT / SOURCE / 'LICENSE', runtime / 'LICENSES/OpenMW.txt')
        shutil.copy2(ROOT / 'VERSION.json', runtime / 'VERSION.json')
        # Preserve upstream embedded-component license files as well.
        for path in (ROOT / SOURCE / 'extern').rglob('*'):
            if path.is_file() and any(x in path.name.lower() for x in ('license', 'copying', 'copyright')):
                target = runtime / 'LICENSES/OpenMW-extern' / path.relative_to(ROOT / SOURCE / 'extern')
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)
        for index, notices in enumerate((prefix / 'licenses', args.work / 'build/deps/usr/share/licenses', Path('/usr/share/licenses'))):
            if notices.is_dir():
                shutil.copytree(notices, runtime / f'LICENSES/libraries-{index}', symlinks=False,
                                ignore=lambda directory, names: [name for name in names
                                    if (Path(directory) / name).is_symlink() and not (Path(directory) / name).exists()])
        if shutil.which('dpkg-query'):
            packages = subprocess.check_output(['dpkg-query', '-W', '-f=${Package} ${Version}\n'], text=True)
            (runtime / 'LICENSES/debian-packages.txt').write_text(packages)
            for copyright_file in Path('/usr/share/doc').glob('*/copyright'):
                target = runtime / 'LICENSES/debian' / copyright_file.parent.name / 'copyright'
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copyright_file, target)
        for path in (args.work / 'build/engine/extern/fetched').rglob('*'):
            if path.is_file() and path.name.lower().startswith(('license', 'copying', 'copyright')):
                target = runtime / 'LICENSES/fetched' / path.relative_to(args.work / 'build/engine/extern/fetched')
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)
        dependencies = args.work / 'build/dependencies.json'
        if dependencies.is_file(): shutil.copy2(dependencies, runtime / 'LICENSES/dependency-packages.json')
        for name in ('dependency-packages.json',):
            if (prefix / name).exists(): shutil.copy2(prefix / name, runtime / 'LICENSES' / name)
        tools = runtime / 'AstraBridge/tools/usr'
        if args.tools_prefix:
            shutil.copytree(args.tools_prefix / 'usr', tools, symlinks=False)
        else:
            tool = shutil.which('xdotool')
            if not tool: raise ValueError('Install xdotool on the builder or supply --tools-prefix')
            (tools / 'bin').mkdir(parents=True); shutil.copy2(tool, tools / 'bin/xdotool')
        collect_libraries(tools / 'bin/xdotool', tools / 'lib', [tools / 'lib', Path('/usr/lib/x86_64-linux-gnu'), Path('/usr/lib')])
        python_version = python_runtime(runtime, args.work)
        wheels(runtime / 'AstraBridge/wheelhouse', args.wheelhouse)
        wheel_notices(runtime / 'AstraBridge/wheelhouse', runtime / 'LICENSES/wheels')
        write_json(runtime / 'LICENSES/engine-build.json', receipt)
        label = ('dev-' + commit[:12]) if args.development else tag
        asset = f'astrabridge-openmw-{label}-linux-x86_64.tar.gz'
        manifest = json.loads((ROOT / 'packaging/manifest.template.json').read_text())
        manifest.update(version, python_version=python_version, git_commit=commit, git_tag=None if args.development else tag,
                        minimum_glibc=glibc_floor(runtime), minimum_cpu_isa=cpu_floor(runtime), asset_filename=asset, engine_sha256=sha256(engine / 'openmw'))
        if not args.development and tuple(map(int, manifest['minimum_glibc'].split('.'))) > (2, 35):
            raise ValueError('Portable release must require glibc <= 2.35; use the container builder')
        if manifest['minimum_cpu_isa'] != 'x86-64-baseline':
            raise ValueError('Release engine/dependencies must target baseline x86_64; rebuild without -march=native/v3')
        manifest['files'] = {p.relative_to(runtime).as_posix(): sha256(p) for p in sorted(runtime.rglob('*')) if p.is_file()}
        write_json(runtime / 'manifest.json', manifest)
        # Dereference libraries; archives contain no links or special files.
        timestamp = git('show', '-s', '--format=%ct', 'HEAD')
        run('tar', '--sort=name', '--mtime=@' + timestamp, '--owner=0', '--group=0', '--numeric-owner',
            '--dereference', '-czf', args.output / asset, '-C', runtime.parent, 'AstraOpenMW')
        manifest['asset_sha256'] = sha256(args.output / asset)
        write_json(args.output / 'manifest.json', manifest)
        source_asset = args.output / f'astrabridge-{label}-source.tar.gz'
        run('git', '-C', ROOT, 'archive', '--format=tar.gz', '--prefix=AstraBridgeForOpenMW/', '-o', source_asset, 'HEAD')
        paths = [args.output / asset, args.output / 'manifest.json', source_asset]
        (args.output / 'SHA256SUMS').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in paths))
        print(json.dumps({'assets': str(args.output), 'version': label, 'minimum_glibc': manifest['minimum_glibc']}, indent=2))


if __name__ == '__main__':
    main()

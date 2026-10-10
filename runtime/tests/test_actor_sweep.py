"""Real Bullet collision contracts for the private player-body sensor."""
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest


def test_actor_body_collision_contracts(tmp_path):
    compiler=shutil.which('c++')
    pkg_config=shutil.which('pkg-config')
    if not compiler or not pkg_config:
        pytest.skip('Native collision test requires a C++ compiler and pkg-config')
    flags=subprocess.run([pkg_config,'--cflags','--libs','bullet'],
                         capture_output=True,text=True)
    if flags.returncode:
        pytest.skip('Native collision test requires Bullet development libraries')
    root=Path(__file__).resolve().parents[1]
    binary=tmp_path/'actor-sweep'
    build=subprocess.run([compiler,'-std=c++17','-O2','-I',str(root/'native'),
                          str(root/'tests/actor_sweep.cpp'),'-o',str(binary),
                          *shlex.split(flags.stdout)],capture_output=True,text=True)
    assert build.returncode==0,build.stdout+build.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

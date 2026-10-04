"""Freeze runtime OS dependencies independently of application releases."""
import hashlib
import json
from pathlib import Path
import subprocess


def base_key(recipe):
    return hashlib.sha256(recipe.read_bytes()).hexdigest()[:24]


def prepare_base(run, output, runner, recipe, work, registry=None, proxy=()):
    key=base_key(recipe)
    local='localhost/astrabridge-runtime-base:'+key
    remote=f'{registry}:base-{key}' if registry else None
    if remote:
        # A failed registry request is not permission to replace a frozen tag.
        result=subprocess.run([*runner,'pull',remote],capture_output=True,text=True)
        if result.returncode==0:
            digest=output(*runner,'image','inspect',remote,'--format','{{.Digest}}')
            reference=remote.split(':base-')[0]+'@'+digest
            return reference
        if not any(word in result.stderr.lower() for word in ('manifest unknown','name unknown','manifest_unknown','404')):
            raise RuntimeError('Cannot check frozen runtime base: '+result.stderr)
    if subprocess.run([*runner,'image','exists',local],stdout=subprocess.DEVNULL).returncode:
        run(*runner,'build',*proxy,'--timestamp','0','-t',local,'-f',recipe,recipe.parent)
    if remote:
        run(*runner,'tag',local,remote)
        digest_file=work/'dist/base-registry.digest'
        run(*runner,'push','--digestfile',digest_file,remote,'docker://'+remote)
        return remote.split(':base-')[0]+'@'+digest_file.read_text().strip()
    return local

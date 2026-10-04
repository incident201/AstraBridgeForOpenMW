import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

@pytest.fixture
def base(monkeypatch):
    directory=Path(__file__).parents[1];monkeypatch.syspath_prepend(str(directory))
    spec=importlib.util.spec_from_file_location('runtime_base',directory/'runtime_base.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_existing_registry_base_is_used_without_rebuilding_or_pushing(base,tmp_path,monkeypatch):
    recipe=tmp_path/'Base.Containerfile';recipe.write_text('FROM pinned\n')
    monkeypatch.setattr(base.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stderr=''))
    calls=[]
    result=base.prepare_base(lambda *a: calls.append(a),lambda *a:'sha256:'+'a'*64,['podman'],recipe,tmp_path,'ghcr.io/example/runtime')
    assert result=='ghcr.io/example/runtime@sha256:'+'a'*64
    assert not calls

def test_registry_outage_does_not_rebuild_frozen_base(base,tmp_path,monkeypatch):
    recipe=tmp_path/'Base.Containerfile';recipe.write_text('FROM pinned\n')
    monkeypatch.setattr(base.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=125,stderr='connection timeout'))
    with pytest.raises(RuntimeError,match='timeout'):
        base.prepare_base(lambda *a:pytest.fail('Must not mutate base'),lambda *a:'', ['podman'],recipe,tmp_path,'registry/example')

def test_missing_base_is_published_once_and_returned_by_digest(base,tmp_path,monkeypatch):
    recipe=tmp_path/'Base.Containerfile';recipe.write_text('FROM pinned\n');(tmp_path/'dist').mkdir()
    monkeypatch.setattr(base.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=125,stderr='manifest unknown'))
    calls=[]
    def run(*args):
        calls.append(args)
        if 'push' in args:Path(args[args.index('--digestfile')+1]).write_text('sha256:'+'b'*64)
    result=base.prepare_base(run,lambda *a:'', ['podman'],recipe,tmp_path,'registry/example')
    assert result=='registry/example@sha256:'+'b'*64
    assert len([c for c in calls if 'push' in c])==1
    before=base.base_key(recipe);recipe.write_text('FROM new-pin\n');assert base.base_key(recipe)!=before

import importlib.util
from pathlib import Path
import pytest


@pytest.fixture
def builder(monkeypatch):
    directory=Path(__file__).parents[1];monkeypatch.syspath_prepend(str(directory))
    spec=importlib.util.spec_from_file_location('build_runtime',directory/'build_runtime.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_restored_builder_archive_is_replaced_only_after_export(builder,tmp_path):
    archive=tmp_path/'builder-image.tar';archive.write_bytes(b'previous')
    def export(*args):
        target=Path(args[args.index('-o')+1])
        assert target!=archive and not target.exists()
        assert archive.read_bytes()==b'previous'
        target.write_bytes(b'new image')
    builder.save_builder_cache(export,['podman'],archive,'image')
    assert archive.read_bytes()==b'new image'
    assert not archive.with_suffix('.partial.tar').exists()


def test_failed_export_preserves_restored_builder_archive(builder,tmp_path):
    archive=tmp_path/'builder-image.tar';archive.write_bytes(b'previous')
    def export(*args):
        Path(args[args.index('-o')+1]).write_bytes(b'incomplete')
        raise RuntimeError('export failed')
    with pytest.raises(RuntimeError,match='export failed'):
        builder.save_builder_cache(export,['podman'],archive,'image')
    assert archive.read_bytes()==b'previous'
    assert not archive.with_suffix('.partial.tar').exists()

from pathlib import Path
import pytest
from astra_bridge.protocol import BridgeError
from astra_daemon.storage import Storage


def fixture(tmp_path):
    install=tmp_path/'installation';(install/'runtime/templates').mkdir(parents=True)
    (install/'runtime/templates/openmw.cfg').write_text('fallback=test,value\n')
    game=tmp_path/'Game with spaces';(game/'Data Files').mkdir(parents=True)
    (game/'Data Files/Morrowind.esm').touch();(game/'Data Files/Morrowind.bsa').touch()
    store=Storage(tmp_path/'state',game,install);store.update({'content':['Morrowind.esm']})
    return store


def test_profile_uses_selected_paths_and_available_explicit_content(tmp_path):
    store=fixture(tmp_path);store.prepare_profile()
    text=(store.root/'profile/base/openmw.cfg').read_text()
    assert f'data="{store.game / "Data Files"}"' in text and 'content=Morrowind.esm' in text
    assert 'Tribunal' not in text and 'fallback-archive=Morrowind.bsa' in text
    settings=(store.root/'profile/settings.cfg').read_text()
    assert 'difficulty = 0' in settings and 'best attack = true' in settings


def test_missing_explicit_assets_prevent_start_instead_of_changing_load_order(tmp_path):
    store=fixture(tmp_path);store.update({'content':['Missing.esp','Morrowind.esm']})
    with pytest.raises(BridgeError,match='content_file_missing'):store.prepare_profile()
    assert not (store.root/'profile/base/openmw.cfg').exists()
    assert store.config()['content']==['Missing.esp','Morrowind.esm']


def test_profile_generation_never_imports_or_replaces_saves(tmp_path):
    store=fixture(tmp_path);target=store.root/'saves/Player';target.mkdir()
    (target/'safe.omwsave').write_bytes(b'user');store.prepare_profile()
    assert (target/'safe.omwsave').read_bytes()==b'user'
    assert list(target.iterdir())==[target/'safe.omwsave']


def test_profile_cannot_escape_selected_game_directory(tmp_path):
    store=fixture(tmp_path)
    with pytest.raises(BridgeError,match='invalid_data_directory'):store.update({'data_relative':'../outside'})
    other=tmp_path/'outside';other.mkdir();(store.game/'external').symlink_to(other)
    store.update({'data_relative':'external'})
    with pytest.raises(BridgeError,match='game_data_directory_missing'):store.prepare_profile()

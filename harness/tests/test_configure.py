from pathlib import Path
import pytest
from configure import configure


def fixture(tmp_path):
    root=tmp_path/'AstraOpenMW'/'AstraBridge';root.mkdir(parents=True)
    (root/'templates').mkdir();(root/'templates/openmw.cfg').write_text('fallback=test,value\n')
    engine=root.parent/'openmw-test';engine.mkdir();(engine/'openmw.x86_64').touch()
    game=tmp_path/'Game with spaces'/'Data Files';game.mkdir(parents=True)
    (game/'Morrowind.esm').touch();(game/'Morrowind.bsa').touch()
    return root,game


def test_relocated_profile_uses_actual_paths_and_only_available_content(tmp_path):
    root,game=fixture(tmp_path)
    configure(root,game.parent,tmp_path/'Videos')
    text=(root.parent/'config/openmw.cfg').read_text()
    assert f'data="{game}"' in text and 'content=Morrowind.esm' in text
    assert 'Tribunal' not in text and 'fallback-archive=Morrowind.bsa' in text
    settings=(root.parent/'config/settings.cfg').read_text()
    assert 'difficulty = -100' in settings and 'best attack = true' in settings


def test_missing_assets_and_active_controller_prevent_configuration(tmp_path):
    root,game=fixture(tmp_path)
    with pytest.raises(ValueError):configure(root,tmp_path/'missing',tmp_path/'Videos')
    (root/'runtime').mkdir();(root/'runtime/bridge.sock').touch()
    with pytest.raises(ValueError,match='Stop'):configure(root,game,tmp_path/'Videos')
    assert not (root.parent/'config/openmw.cfg').exists()


def test_import_refuses_to_replace_user_save(tmp_path):
    root,game=fixture(tmp_path)
    clean=root/'checkpoints/main';clean.mkdir(parents=True);(clean/'safe.omwsave').write_bytes(b'clean')
    target=root/'runtime/userdata/saves/Astra_Test';target.mkdir(parents=True);(target/'safe.omwsave').write_bytes(b'user')
    with pytest.raises(ValueError,match='overwrite'):configure(root,game,tmp_path/'Videos',checkpoint='main')
    assert (target/'safe.omwsave').read_bytes()==b'user'


def test_release_engine_layout(tmp_path):
    root,game=fixture(tmp_path)
    (root.parent/'openmw-test/openmw.x86_64').unlink()
    engine=root.parent/'engine';engine.mkdir();(engine/'openmw').touch()
    configure(root,game,tmp_path/'Videos')
    assert (root/'runtime').stat().st_mode & 0o777 == 0o700
    assert (root.parent/'config/openmw.cfg').is_file()

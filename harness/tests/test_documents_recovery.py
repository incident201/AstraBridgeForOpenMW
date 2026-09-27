import configparser
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.protocol import BridgeError, check_result, validate
from astra_bridge.session import Session


@pytest.mark.parametrize('args', [
    {'limit': 0}, {'limit': 8001}, {'limit': True}, {'offset': -1},
    {'offset': 1.5}, {'ref': 'item_hidden'}, {'path': 'book.txt'},
])
def test_read_rejects_invalid_bounds_and_non_document_access(args):
    with pytest.raises(BridgeError, match='invalid_arguments'):
        validate('read', args)


def test_document_projection_and_unicode_chunk():
    validate('read', {'ref': 'document_session_hash', 'offset': 4000, 'limit': 8000})
    check_result({'document': {'ref': 'document_session_hash', 'title': 'Книга',
                              'kind': 'book', 'characters': 23000}})
    check_result({'ref': 'document_session_hash', 'title': 'Книга', 'kind': 'book',
                  'characters': 23000, 'text': 'Текст 🕮', 'offset': 0,
                  'next_offset': 7, 'eof': False})


@pytest.mark.parametrize('args', [{}, {'reason': ''}, {'reason': '  '},
                                  {'reason': '\0'}, {'reason': 'x' * 301},
                                  {'reason': 12}, {'reason': 'NPC fell', 'command': 'tgm'}])
def test_reset_requires_explicit_reason_and_has_no_console_arguments(args):
    with pytest.raises(BridgeError, match='invalid_arguments'):
        validate('resetNPC', args)


def test_read_returns_only_chunk_and_does_not_observe_or_unpause(tmp_path):
    s = Session.__new__(Session)
    s.lock = threading.RLock(); s.runtime = tmp_path; s.recorder = None
    s.latest_observation = {'ui_mode': 'Book', 'observation': 5}
    calls = []
    chunk = {'text': 'Книга', 'offset': 0, 'next_offset': 5, 'eof': True}
    s.command = lambda op, args, **kw: calls.append((op, args)) or chunk.copy()
    s.observe = lambda: pytest.fail('Reading must not duplicate a full observation')
    assert s.call('read', {'offset': 0, 'limit': 4000}) == chunk
    assert calls == [('read', {'offset': 0, 'limit': 4000})]


def test_existing_profile_enables_bundled_idle_fix_without_losing_preferences(tmp_path):
    s = Session.__new__(Session)
    s.root = tmp_path / 'AstraBridge'; s.installation = tmp_path
    s.runtime = s.root / 'runtime'; s.profile = s.runtime / 'profile'
    s.profile.mkdir(parents=True)
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/openmw.cfg').write_text('content=Morrowind.esm\n')
    (tmp_path / 'config/settings.cfg').write_text('[Game]\ndifficulty = -10\n')
    settings = s.profile / 'settings.cfg'
    settings.write_text('[Game]\ndifficulty = 20\nuse additional anim sources = false\n[Video]\nvsync = true\n')
    animation = s.root / 'mod/Animations/xbase_anim/_xYAIAF.kf'
    animation.parent.mkdir(parents=True); animation.touch()
    s.display = SimpleNamespace(headless=False)
    s.prepare()
    cfg = configparser.ConfigParser(); cfg.read(settings)
    assert cfg['Game']['use additional anim sources'] == 'true'
    assert cfg['Game']['difficulty'] == '20'
    assert cfg['Video']['vsync'] == 'true'
    first = settings.read_bytes()
    s.prepare()
    assert settings.read_bytes() == first

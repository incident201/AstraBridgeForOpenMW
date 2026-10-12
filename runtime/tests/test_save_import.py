import json
import struct
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astra_bridge.protocol import BridgeError
from astra_daemon.runtime import Runtime
from astra_daemon.server import application


def subrecord(name, data):
    return name + struct.pack('<I', len(data)) + data


def record(name, data):
    return name + struct.pack('<III', len(data), 0, 0) + data


def save_bytes(game=b'Morrowind.esm', padding=0):
    header = subrecord(b'FORM', struct.pack('<I', 37)) + subrecord(b'HEDR', bytes(20))
    saved = b''.join(subrecord(name, data) for name, data in [
        (b'PLNA', 'A character / not a path'.encode()), (b'PLLE', struct.pack('<I', 10)),
        (b'PLCE', b'Urshilaku Camp'), (b'TSTM', bytes(16)), (b'TIME', bytes(8)),
        (b'DESC', b'Before the burial caverns'), (b'DEPE', game), (b'SCRN', b'image'),
    ])
    return record(b'TES3', header) + record(b'SAVE', saved) + record(b'GLOB', bytes(padding))


async def chunks(data):
    for start in range(0, len(data), 10000):
        yield data[start:start + 10000]


@pytest.mark.asyncio
@pytest.mark.parametrize('new_profile', [False, True])
async def test_import_adds_independent_slots_only_to_requested_profile(tmp_path, new_profile):
    runtime = Runtime(tmp_path/'installation', tmp_path/'state', tmp_path/'game')
    target = 'default'
    if new_profile:
        target = (await runtime.profile_operation('create', {'name': 'Experiment'}))['result']['id']
    root = runtime.profiles.path(target)
    prior = root/'saves/Existing'
    prior.mkdir()
    (prior/'progress.omwsave').write_bytes(b'untouched save')
    note = root/'atlas/note.json'
    note.write_text('{"note":"untouched knowledge"}')
    source = save_bytes()
    try:
        for _ in range(2):
            result = await runtime.import_save(target, 'test.omwsave', chunks(source), len(source))
            assert result['profile']['id'] == target and result['imported']
            assert result['player_name'] == 'A character / not a path'
            assert result['description'] == 'Before the burial caverns'
            assert result['bytes'] == len(source)
        imported = list((root/'saves').glob('Imported-*/*.omwsave'))
        assert len(imported) == 2
        assert all(path.read_bytes() == source for path in imported)
        assert imported[0].stat().st_ino != imported[1].stat().st_ino
        assert (prior/'progress.omwsave').read_bytes() == b'untouched save'
        assert json.loads(note.read_text()) == {'note': 'untouched knowledge'}
        assert runtime.profiles.data['active'] == 'default'
        assert not list(root.glob('.save-import-*'))
        if new_profile:
            assert list((runtime.root/'saves').iterdir()) == []
            assert list((runtime.root/'atlas').iterdir()) == []
            assert list((runtime.root/'sessions').iterdir()) == []
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_streamed_upload_exceeds_json_limit_but_requires_authentication(tmp_path):
    runtime = Runtime(tmp_path/'installation', tmp_path/'state', tmp_path/'game')
    client = TestClient(TestServer(application(runtime, 'p'*40)))
    await client.start_server()
    source = save_bytes(padding=2*1024*1024)
    path = '/v1/runtime/profiles/default/saves/import'
    headers = {'Content-Type': 'application/octet-stream', 'X-Astra-Save-Filename': 'large.omwsave'}
    try:
        response = await client.post(path, data=source, headers=headers)
        assert response.status == 401
        assert list((runtime.root/'saves').iterdir()) == []
        headers['Authorization'] = 'Bearer '+'p'*40
        response = await client.post(path, data=source, headers=headers)
        assert response.status == 200
        assert (await response.json())['result']['bytes'] == len(source)
        imported = next((runtime.root/'saves').glob('Imported-*/*.omwsave'))
        assert imported.read_bytes() == source
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('filename,data,error', [
    ('original.ess', save_bytes(), 'unsupported_save_format'),
    ('../outside.omwsave', save_bytes(), 'invalid_save_filename'),
    ('C:\\outside.omwsave', save_bytes(), 'invalid_save_filename'),
    ('empty.omwsave', b'', 'invalid_save_file'),
    ('renamed.omwsave', b'not an OpenMW save', 'invalid_save_file'),
    ('truncated.omwsave', save_bytes()[:-1], 'invalid_save_file'),
    ('original.omwsave', record(b'TES3', subrecord(b'HEDR', bytes(300))) + record(b'SAVE', b''), 'invalid_save_file'),
])
async def test_invalid_imports_leave_no_files(tmp_path, filename, data, error):
    runtime = Runtime(tmp_path/'installation', tmp_path/'state', tmp_path/'game')
    try:
        with pytest.raises(BridgeError, match=error):
            await runtime.import_save('default', filename, chunks(data), len(data))
        assert list((runtime.root/'saves').iterdir()) == []
        assert not list(runtime.root.glob('.save-import-*'))
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_running_game_and_unknown_profile_reject_without_reading_upload(tmp_path):
    runtime = Runtime(tmp_path/'installation', tmp_path/'state', tmp_path/'game')
    async def unread():
        raise AssertionError('A rejected upload must not be consumed')
        yield b''
    try:
        with pytest.raises(BridgeError, match='profile_not_found'):
            await runtime.import_save('../other', 'save.omwsave', unread())
        runtime.running = lambda: True
        with pytest.raises(BridgeError, match='stop_game_before_managing_profiles'):
            await runtime.import_save('default', 'save.omwsave', unread())
        assert not list(runtime.root.glob('.save-import-*'))
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_partial_oversized_and_mismatched_uploads_are_removed(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path/'installation', tmp_path/'state', tmp_path/'game')
    runtime.storage.update({'content': ['Morrowind.esm']})
    async def interrupted():
        yield save_bytes()[:50]
        raise ConnectionResetError('disconnected')
    try:
        with pytest.raises(ConnectionResetError):
            await runtime.import_save('default', 'save.omwsave', interrupted())
        with pytest.raises(BridgeError, match='invalid_save_file'):
            await runtime.import_save('default', 'save.omwsave', chunks(save_bytes()), len(save_bytes())+1)
        with pytest.raises(BridgeError, match='save_game_mismatch'):
            await runtime.import_save('default', 'save.omwsave', chunks(save_bytes(b'Other.esm')))
        monkeypatch.setattr('astra_daemon.runtime.MAX_SAVE_BYTES', 100)
        with pytest.raises(BridgeError, match='save_import_too_large'):
            await runtime.import_save('default', 'save.omwsave', chunks(save_bytes()))
        assert list((runtime.root/'saves').iterdir()) == []
        assert not list(runtime.root.glob('.save-import-*'))
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_slot_collision_never_removes_an_existing_directory(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path/'installation', tmp_path/'state', tmp_path/'game')
    existing = runtime.root/'saves/Imported-collision'
    existing.mkdir()
    (existing/'keep.omwsave').write_bytes(b'keep')
    monkeypatch.setattr('astra_daemon.runtime.uuid.uuid4', lambda: SimpleNamespace(hex='collision'))
    try:
        with pytest.raises(FileExistsError):
            await runtime.import_save('default', 'save.omwsave', chunks(save_bytes()))
        assert (existing/'keep.omwsave').read_bytes() == b'keep'
        assert not list(runtime.root.glob('.save-import-*'))
    finally:
        await runtime.close()

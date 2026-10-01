import io
import json
from pathlib import Path
import tarfile
import threading
from types import SimpleNamespace
import queue

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astra_bridge.protocol import BridgeError
from astra_bridge.media_stream import MediaStream
from astra_bridge.recording import Recorder
from astra_daemon.importer import import_game
from astra_daemon.ownership import Ownership
from astra_daemon.runtime import Runtime
from astra_daemon.server import application
from astra_daemon.snapshot import snapshot
from astra_daemon.storage import Storage


def test_agent_owner_persists_between_commands_and_rejects_old_token():
    owner=Ownership();first=owner.acquire_agent('Agent')
    owner.since=0
    owner.verify_agent(first['session_token'])
    with pytest.raises(BridgeError,match='agent_owns_input'):owner.acquire_manual('viewer')
    with pytest.raises(BridgeError,match='agent_already_connected'):owner.acquire_agent('Other')
    owner.release();second=owner.acquire_agent('Next')
    with pytest.raises(BridgeError,match='agent_not_connected'):owner.verify_agent(first['session_token'])
    owner.verify_agent(second['session_token'])
    assert 'token' not in owner.public()


def test_import_is_atomic_and_preserves_game_bytes(tmp_path):
    source=io.BytesIO()
    with tarfile.open(fileobj=source,mode='w') as archive:
        info=tarfile.TarInfo('Data Files/Example.esp');info.size=4;archive.addfile(info,io.BytesIO(b'\xff\x00ab'))
    source.seek(0);import_game(source,tmp_path)
    assert (tmp_path/'content/Data Files/Example.esp').read_bytes()==b'\xff\x00ab'
    with pytest.raises(ValueError,match='already exists'):import_game(io.BytesIO(),tmp_path)


def test_failed_import_does_not_activate_partial_data(tmp_path):
    source=io.BytesIO()
    with tarfile.open(fileobj=source,mode='w') as archive:
        info=tarfile.TarInfo('../escape');info.size=1;archive.addfile(info,io.BytesIO(b'x'))
    source.seek(0)
    with pytest.raises(tarfile.FilterError):import_game(source,tmp_path)
    assert not (tmp_path/'content').exists()
    assert not list(tmp_path.glob('.import-*'))


def make_storage(tmp_path):
    game=tmp_path/'game';(game/'Data Files').mkdir(parents=True)
    install=tmp_path/'installation';(install/'runtime/templates').mkdir(parents=True)
    (install/'runtime/templates/openmw.cfg').write_text('fallback=Water_SurfaceFPS,12\n')
    return Storage(tmp_path/'state',game,install)


def test_ini_uses_explicit_encoding_and_load_order_without_reading_content(tmp_path):
    store=make_storage(tmp_path)
    text='[Game Files]\nGameFile2=Мод.esp\nGameFile0=Morrowind.esm\n[Archives]\nArchive0=Extra.bsa\n'
    (store.game/'Morrowind.ini').write_bytes(text.encode('cp1251'))
    for name in ('Morrowind.esm','Мод.esp','Morrowind.bsa','Extra.bsa'):(store.game/'Data Files'/name).write_bytes(b'not an ESM')
    result=store.import_ini('win1251')
    assert result['configuration']['content']==['Morrowind.esm','Мод.esp']
    store.prepare_profile()
    text=(store.root/'profile/base/openmw.cfg').read_text()
    assert text.index('content=Morrowind.esm')<text.index('content=Мод.esp')
    assert 'fallback-archive=Morrowind.bsa' in text and 'encoding=win1251' in text


def test_game_settings_survive_launch_unless_explicitly_changed(tmp_path):
    store=make_storage(tmp_path);(store.game/'Data Files/Morrowind.esm').touch()
    store.update({'content':['Morrowind.esm']});store.prepare_profile()
    profile=store.root/'profile/settings.cfg';profile.write_text(profile.read_text().replace('difficulty = -100','difficulty = 20'))
    store.update({'viewer_quality':'1080p60'});store.prepare_profile()
    assert 'difficulty = 20' in profile.read_text()
    store.update({'difficulty':0});store.prepare_profile()
    assert 'difficulty = 0' in profile.read_text()


def test_viewer_capture_does_not_change_recording_request_or_clock(tmp_path):
    stream=MediaStream(tmp_path/'media')
    try:
        with stream.capture():
            assert stream.get(108,'I')==1 and stream.get(56,'I')==0 and stream.samples==0
            with stream.capture():assert stream.get(108,'I')==1
            assert stream.get(108,'I')==1
        assert stream.get(108,'I')==0 and stream.get(56,'I')==0
    finally:stream.close()


def test_recording_trims_viewer_audio_to_exact_sample_interval():
    blocks={1:{'start':90,'samples':20,'pcm':bytes(range(160))},2:{'start':110,'samples':20,'pcm':bytes(range(160))}}
    recorder=Recorder.__new__(Recorder);recorder.condition=threading.Condition()
    recorder.media=SimpleNamespace(sequence=2,slots=128,read=blocks.get)
    recorder.audio_cursor=0;recorder.base_sample=100;recorder.end_sample=120;recorder.audio_samples=0;recorder.audio_queue=queue.Queue()
    recorder._audio()
    assert recorder.audio_samples==20
    assert recorder.audio_queue.get()==blocks[1]['pcm'][80:]
    assert recorder.audio_queue.get()==blocks[2]['pcm'][:80]


def test_update_snapshot_restores_state_without_touching_recordings(tmp_path):
    (tmp_path/'profile').mkdir();(tmp_path/'profile/settings.cfg').write_text('old')
    (tmp_path/'recordings').mkdir();(tmp_path/'recordings/keep.mp4').write_bytes(b'keep')
    snapshot(tmp_path,'backup','before-update')
    (tmp_path/'profile/settings.cfg').write_text('new')
    snapshot(tmp_path,'restore','before-update')
    assert (tmp_path/'profile/settings.cfg').read_text()=='old'
    assert (tmp_path/'recordings/keep.mp4').read_bytes()==b'keep'


@pytest.mark.asyncio
async def test_http_boundary_requires_auth_and_rejects_internal_commands(tmp_path):
    runtime=Runtime(tmp_path/'installation',tmp_path/'state',tmp_path/'game')
    client=TestClient(TestServer(application(runtime,'x'*40)))
    await client.start_server()
    try:
        assert (await client.get('/health')).status==200
        assert (await client.get('/v1/runtime/status')).status==401
        headers={'Authorization':'Bearer '+'x'*40}
        assert (await client.get('/v1/runtime/status',headers={**headers,'Origin':'https://example.com'})).status==403
        for op,args in (('serve',{}),('stop',{'_runtime_mode':'manual'})):
            response=await client.post('/v1/game/command',headers=headers,json={'op':op,'args':args})
            assert response.status==409
        response=await client.post('/v1/game/command',headers=headers,json={'op':'observe','args':{}})
        assert (await response.json())['error']=='agent_not_connected'
        assert (await client.get('/v1/artifacts/not-a-path',headers=headers)).status==404
    finally:await client.close()

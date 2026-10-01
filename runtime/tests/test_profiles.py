import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astra_bridge.protocol import BridgeError
from astra_daemon.runtime import Runtime
from astra_daemon.server import application
from astra_daemon.snapshot import snapshot


def runtime_at(tmp_path):
    return Runtime(tmp_path/'installation',tmp_path/'state',tmp_path/'game')


def seed(root):
    (root/'saves/character').mkdir(parents=True)
    (root/'saves/character/progress.omwsave').write_bytes(b'saved character')
    shot=root/'runtime/screenshots/note.png';shot.write_bytes(b'picture')
    (root/'atlas/spatial-memory.json').write_text(json.dumps({'note':'Remember this door','screenshot':str(shot)}))
    with sqlite3.connect(root/'atlas/exploration-memory.sqlite3') as db:
        db.execute('CREATE TABLE graphs(ref TEXT PRIMARY KEY,payload TEXT)')
        db.execute('INSERT INTO graphs VALUES (?,?)',('node',json.dumps({'views':[str(shot)]})))
    with sqlite3.connect(root/'atlas/agent-memory.sqlite3') as db:
        db.execute('CREATE TABLE notes(ref TEXT PRIMARY KEY,text TEXT)')
        db.execute('INSERT INTO notes VALUES (?,?)',('object','This door is locked'))
    (root/'sessions/events.jsonl').write_text('{"event":"original history"}\n')
    (root/'runtime/frames.bin').write_bytes(b'disposable engine buffer')
    return shot


@pytest.mark.asyncio
async def test_fresh_profile_has_no_saved_data_and_stale_artifacts_are_unavailable(tmp_path):
    runtime=runtime_at(tmp_path);shot=seed(runtime.root)
    old=runtime.project(str(shot));assert old.startswith('/v1/artifacts/')
    await runtime.profile_operation('create',{'name':'Other playthrough'})
    other=runtime.profiles.catalog()['profiles'][-1]['id']
    await runtime.profile_operation('switch',{'id':other})
    assert runtime.root!=runtime.base
    assert list((runtime.root/'saves').iterdir())==[]
    assert list((runtime.root/'atlas').iterdir())==[]
    assert list((runtime.root/'sessions').iterdir())==[]
    assert runtime.artifacts=={} and runtime.atlas_cache=={'supported':False}
    assert runtime.project(str(shot)) is None
    assert runtime.recordings_root==runtime.base/'recordings'/other
    with pytest.raises(BridgeError,match='profile_mismatch'):await runtime.start_engine(profile='default')
    with pytest.raises(BridgeError,match='profile_mismatch'):await runtime.acquire_agent('Wrong','default')
    await runtime.close()


@pytest.mark.asyncio
async def test_duplicate_rebases_attachments_and_survives_permanent_source_deletion(tmp_path):
    runtime=runtime_at(tmp_path);source=runtime.root;shot=seed(source)
    result=await runtime.profile_operation('duplicate',{'id':'default','name':'Independent copy'})
    clone=result['result']['id'];target=runtime.profiles.path(clone)
    assert result['active']['id']=='default'
    assert (target/'saves/character/progress.omwsave').read_bytes()==b'saved character'
    assert not (target/'runtime/frames.bin').exists()
    copied=json.loads((target/'atlas/spatial-memory.json').read_text())['screenshot']
    assert copied==str(target/'runtime/screenshots/note.png')
    assert Path(copied).stat().st_ino!=shot.stat().st_ino
    with sqlite3.connect(target/'atlas/exploration-memory.sqlite3') as db:
        assert json.loads(db.execute('SELECT payload FROM graphs').fetchone()[0])['views']==[copied]
    with sqlite3.connect(source/'atlas/agent-memory.sqlite3') as db:
        db.execute("UPDATE notes SET text='Changed later'")
    with sqlite3.connect(target/'atlas/agent-memory.sqlite3') as db:
        assert db.execute('SELECT text FROM notes').fetchone()[0]=='This door is locked'
    await runtime.profile_operation('delete',{'id':'default'})
    assert runtime.profiles.data['active']==clone and runtime.root==target
    assert not (source/'atlas').exists() and Path(copied).read_bytes()==b'picture'
    assert not (source/'trash').exists()
    await runtime.close()


@pytest.mark.asyncio
async def test_delete_last_profile_starts_empty_and_keeps_host_recordings(tmp_path):
    runtime=runtime_at(tmp_path);seed(runtime.root)
    video=runtime.recordings_root/'keep.mp4';video.write_bytes(b'video')
    await runtime.profile_operation('delete',{'id':'default'})
    assert runtime.profiles.public()['name']=='Default'
    assert runtime.profiles.public()['id']!='default'
    assert list((runtime.root/'saves').iterdir())==[]
    assert runtime.recordings()==[] and video.read_bytes()==b'video'
    await runtime.close()


@pytest.mark.asyncio
async def test_http_profiles_reject_every_mutation_while_game_is_running(tmp_path):
    runtime=runtime_at(tmp_path);client=TestClient(TestServer(application(runtime,'p'*40)))
    await client.start_server();headers={'Authorization':'Bearer '+'p'*40}
    try:
        response=await client.post('/v1/runtime/profiles/create',headers=headers,json={'name':'Second'})
        second=(await response.json())['result']['result']['id']
        runtime.session=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),display=SimpleNamespace(frame_stream=None,media_stream=None),control=SimpleNamespace(status=lambda:None),recorder=None)
        for operation,args in [('create',{'name':'New'}),('duplicate',{'id':'default','name':'Copy'}),('rename',{'id':'default','name':'Renamed'}),('switch',{'id':second}),('delete',{'id':second})]:
            response=await client.post('/v1/runtime/profiles/'+operation,headers=headers,json=args)
            assert response.status==409
            assert (await response.json())['error']=='stop_game_before_managing_profiles'
        assert runtime.profiles.data['active']=='default'
    finally:
        runtime.session=None;await client.close()


@pytest.mark.asyncio
async def test_snapshot_restores_all_profiles_and_note_screenshots(tmp_path):
    runtime=runtime_at(tmp_path);seed(runtime.root)
    clone=(await runtime.profile_operation('duplicate',{'id':'default','name':'Copy'}))['result']['id']
    await runtime.profile_operation('switch',{'id':clone});target=runtime.root
    snapshot(runtime.base,'backup','update-before')
    await runtime.profile_operation('delete',{'id':clone})
    snapshot(runtime.base,'restore','update-before')
    restored=runtime_at(tmp_path)
    assert restored.root==target and restored.profiles.data['active']==clone
    assert (target/'runtime/screenshots/note.png').read_bytes()==b'picture'
    assert (restored.base/'runtime/screenshots/note.png').read_bytes()==b'picture'
    assert not (restored.base/'backups/update-before/runtime/frames.bin').exists()
    await restored.close();await runtime.close()

import os
import struct
from pathlib import Path
import pytest
from astra_daemon.content_order import import_order,validate_order,masters
from astra_bridge.protocol import BridgeError


def plugin(path,parents=()):
    data=b''.join(struct.pack('<4sI',b'MAST',len(name.encode('cp1252'))+1)+name.encode('cp1252')+b'\0' for name in parents)
    path.write_bytes(b'TES3'+struct.pack('<III',len(data),0,0)+data+b'Unrelated game records are not parsed')


def test_steam_ini_order_and_download_timestamps_do_not_put_expansions_before_masters(tmp_path):
    plugin(tmp_path/'Bloodmoon.esm',['Morrowind.esm']);plugin(tmp_path/'Morrowind.esm');plugin(tmp_path/'Tribunal.esm',['Morrowind.esm'])
    for name,t in [('Tribunal.esm',1),('Bloodmoon.esm',2),('Morrowind.esm',3)]:os.utime(tmp_path/name,(t,t))
    names=['Bloodmoon.esm','Morrowind.esm','Tribunal.esm']
    assert import_order(tmp_path,names,'win1252')==['Morrowind.esm','Tribunal.esm','Bloodmoon.esm']
    with pytest.raises(BridgeError,match='content_load_order'):validate_order(tmp_path,names,'win1252')
    validate_order(tmp_path,['Morrowind.esm','Tribunal.esm','Bloodmoon.esm'],'win1252')


def test_mod_dependencies_missing_masters_and_cycles(tmp_path):
    plugin(tmp_path/'Base.esm');plugin(tmp_path/'Child.esp',['base.ESM'])
    assert import_order(tmp_path,['Child.esp','Base.esm'],'win1252')==['Base.esm','Child.esp']
    with pytest.raises(BridgeError,match='content_dependency_missing'):import_order(tmp_path,['Child.esp'],'win1252')
    plugin(tmp_path/'Base.esm',['Child.esp'])
    with pytest.raises(BridgeError,match='content_dependency_cycle'):import_order(tmp_path,['Child.esp','Base.esm'],'win1252')


def test_header_read_is_bounded(tmp_path):
    p=tmp_path/'Corrupt.esm';p.write_bytes(b'TES3'+struct.pack('<III',2**30,0,0))
    with pytest.raises(BridgeError,match='invalid_content_header'):masters(p,'win1252')


def test_repair_preserves_an_already_valid_custom_order(tmp_path):
    plugin(tmp_path/'Base.esm');plugin(tmp_path/'First.esp',['Base.esm']);plugin(tmp_path/'Second.esp',['Base.esm'])
    wanted=['Base.esm','Second.esp','First.esp']
    assert import_order(tmp_path,wanted,'win1252',by_timestamp=False)==wanted

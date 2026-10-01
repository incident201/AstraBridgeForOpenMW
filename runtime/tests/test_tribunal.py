"""Synthetic script fixtures: no Bethesda or third-party script is bundled."""
import struct

import pytest

from astra_bridge.tribunal import (ADDON, GATE, MARKER, _record, _sub, build_addon,
                                  gate_source, prepare_tribunal_delay, read_attack_script)


def synthetic_script(source=None):
    source = source or (b'Begin dbattackScript\nshort counter\nfloat delay\n\n'
                        b'set counter to ( counter + 1 )\nEnd\n')
    names = b'counter\0delay\0'
    header = struct.pack('<32s5I', b'dbattackScript', 1, 0, 1, 3, len(names))
    return 0, {b'SCHD': header, b'SCVR': names, b'SCDT': b'old', b'SCTX': source}


def write_plugin(path, source=None):
    flags, parts = synthetic_script(source)
    path.write_bytes(_record(b'TES3', b'') + _record(b'SCPT', b''.join(_sub(k, v) for k, v in parts.items()), flags))


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_gate_before_executable_code_preserves_source_and_local_layout(tmp_path, newline):
    source = (b'; comment\nBeGiN "dbattackScript" ; name\n\nshort counter ; local\n'
              b'float delay\n; localized message follows\nMessageBox "' + 'Тест'.encode('cp1251') + b'"\nEnd\n')
    source = source.replace(b'\n', newline)
    patched = gate_source(source)
    gate = GATE.replace(b'\n', newline)
    assert patched.replace(gate, b'') == source
    assert patched.index(b'float delay') < patched.index(MARKER) < patched.index(b'MessageBox')
    original = synthetic_script(source)
    path = tmp_path / ADDON
    path.write_bytes(build_addon(original, []))
    _, actual = read_attack_script(path)
    assert actual[b'SCTX'] == patched
    assert actual[b'SCHD'][:44] == original[1][b'SCHD'][:44]
    assert actual[b'SCHD'][48:] == original[1][b'SCHD'][48:]
    assert actual[b'SCVR'] == original[1][b'SCVR']
    assert actual[b'SCDT'] == b'' and struct.unpack_from('<I', actual[b'SCHD'], 44)[0] == 0


def test_effective_load_order_local_data_and_repeat_prepare(tmp_path):
    data = tmp_path / 'Game Data'; data.mkdir()
    local = tmp_path / 'local'; local.mkdir()
    output = tmp_path / 'runtime'; output.mkdir()
    (data / 'Morrowind.esm').write_bytes(_record(b'TES3', b''))
    write_plugin(data / 'Tribunal.esm')
    write_plugin(data / 'Changes.esp', b'Begin dbattackScript\nshort counter\nset counter to 2\nEnd\n')
    effective = b'Begin dbattackScript\nshort counter\nset counter to 3\nEnd\n'
    write_plugin(local / 'changes.ESP', effective)
    cfg = f'data="{data}"\ndata="{output}"\ncontent=Morrowind.esm\ncontent=TRIBUNAL.ESM\ncontent=Changes.esp\ncontent=Test.omwscripts\n'
    args = dict(base_dir=tmp_path, local_data=local)
    result = prepare_tribunal_delay(cfg, output, **args)
    path = output / ADDON
    first = path.read_bytes(); timestamp = path.stat().st_mtime_ns
    assert read_attack_script(path)[1][b'SCTX'].replace(GATE, b'') == effective
    assert result.endswith(f'content={ADDON}\n')
    assert prepare_tribunal_delay(result, output, **args) == result
    assert path.read_bytes() == first and path.stat().st_mtime_ns == timestamp
    changed = effective.replace(b'to 3', b'to 4')
    write_plugin(local / 'changes.ESP', changed)
    prepare_tribunal_delay(cfg, output, **args)
    assert read_attack_script(path)[1][b'SCTX'].replace(GATE, b'') == changed


def test_default_enabled_optional_off_and_absent_tribunal(tmp_path):
    output = tmp_path / 'output'
    cfg = f'data="{tmp_path}"\ncontent=Tribunal.esm\n'
    write_plugin(tmp_path / 'Tribunal.esm')
    assert ADDON in prepare_tribunal_delay(cfg, output, base_dir=tmp_path)
    assert ADDON not in prepare_tribunal_delay(cfg + f'content={ADDON.upper()}\n', output, base_dir=tmp_path, enabled=False)
    assert prepare_tribunal_delay('content=Morrowind.esm\n', output, base_dir=tmp_path) == 'content=Morrowind.esm\n'
    with pytest.raises(ValueError, match='true or false'):
        prepare_tribunal_delay(cfg, output, base_dir=tmp_path, enabled='false')


@pytest.mark.parametrize('source', [b'', b'Begin unrelated\nEnd\n', b'Begin dbattackScript\nshort a\n'])
def test_invalid_source_is_not_silently_published(source):
    with pytest.raises(ValueError):
        gate_source(source)


def test_missing_deleted_and_truncated_content_fail_before_replacing_addon(tmp_path):
    target = tmp_path / ADDON; target.write_bytes(b'previous')
    cfg = f'data="{tmp_path}"\ncontent=Tribunal.esm\n'
    with pytest.raises(ValueError, match='cannot locate'):
        prepare_tribunal_delay(cfg, tmp_path, base_dir=tmp_path)
    plugin = tmp_path / 'Tribunal.esm'
    plugin.write_bytes(b'SCPT')
    with pytest.raises(ValueError, match='Truncated'):
        prepare_tribunal_delay(cfg, tmp_path, base_dir=tmp_path)
    flags, parts = synthetic_script(); parts[b'DELE'] = b'\0'
    plugin.write_bytes(_record(b'SCPT', b''.join(_sub(k, v) for k, v in parts.items())))
    with pytest.raises(ValueError, match='deleted'):
        prepare_tribunal_delay(cfg, tmp_path, base_dir=tmp_path)
    assert target.read_bytes() == b'previous'


def test_session_automatically_enables_patch_in_existing_profile(tmp_path):
    from types import SimpleNamespace
    from astra_bridge.session import Session
    s = Session.__new__(Session)
    s.root = tmp_path / 'AstraBridge'; s.installation = tmp_path
    s.runtime = s.root / 'runtime'; s.profile = s.runtime / 'profile'
    s.profile.mkdir(parents=True)
    (tmp_path / 'config').mkdir()
    data = tmp_path / 'Game'; data.mkdir()
    (data / 'Morrowind.esm').write_bytes(_record(b'TES3', b''))
    write_plugin(data / 'Tribunal.esm')
    original = (data / 'Tribunal.esm').read_bytes()
    (tmp_path / 'config/openmw.cfg').write_text(f'data="{data}"\ncontent=Morrowind.esm\ncontent=Tribunal.esm\n')
    (tmp_path / 'config/settings.cfg').write_text('[Game]\ndifficulty = 0\n')
    (s.profile / 'openmw.cfg').write_text('old profile\n')
    s.display = SimpleNamespace(headless=False)
    s.prepare()
    assert (s.profile / 'openmw.cfg').read_text().endswith(f'content={ADDON}\n')
    assert read_attack_script(s.runtime / 'data' / ADDON) is not None
    assert (data / 'Tribunal.esm').read_bytes() == original

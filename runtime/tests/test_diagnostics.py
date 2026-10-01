import json

from astra_bridge.diagnostics import inspect_auto_fixes
from astra_bridge.tribunal import ADDON, prepare_tribunal_delay
from test_tribunal import write_plugin


def setup(tmp_path):
    root = tmp_path / 'AstraBridge'
    profile = root / 'runtime/profile'; profile.mkdir(parents=True)
    config_dir = tmp_path / 'config'; config_dir.mkdir()
    game = tmp_path / 'Game'; game.mkdir()
    write_plugin(game / 'Tribunal.esm')
    data = root / 'runtime/data'
    cfg = f'data="{game}"\ndata="{root / "mod"}"\ndata="{data}"\ncontent=Tribunal.esm\n'
    (config_dir / 'openmw.cfg').write_text(cfg)
    (profile / 'openmw.cfg').write_text(prepare_tribunal_delay(cfg, data, base_dir=profile))
    (profile / 'settings.cfg').write_text('[Game]\nuse additional anim sources = true\n[Physics]\nasync num threads = 0\n')
    for name in ('xbase_anim', 'xbase_anim_female', 'xbase_animkna'):
        p = root / 'mod/Animations' / name / '_xYAIAF.kf'
        p.parent.mkdir(parents=True); p.write_bytes(b'test animation')
    return root, game, profile


def test_reports_configured_fixes_without_writes_or_game_state(tmp_path):
    root, _, _ = setup(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    report = inspect_auto_fixes(root)
    assert report['scope'] == 'profile_on_disk'
    assert {r['status'] for r in report['fixes'].values()} == {'configured'}
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_fresh_profile_pending_and_missing_animation(tmp_path):
    root, _, profile = setup(tmp_path)
    for p in profile.iterdir(): p.unlink()
    report = inspect_auto_fixes(root)['fixes']
    assert {r['status'] for r in report.values()} == {'pending_start'}
    (root / 'mod/Animations/xbase_anim_female/_xYAIAF.kf').unlink()
    assert inspect_auto_fixes(root)['fixes']['npc_idle_drift']['status'] == 'missing_assets'
    assert not (profile / 'settings.cfg').exists()


def test_disabled_and_tribunal_not_installed(tmp_path):
    root, _, profile = setup(tmp_path)
    (root / 'local-settings.json').write_text(json.dumps({'delay_tribunal': False}))
    assert inspect_auto_fixes(root)['fixes']['tribunal_delay']['status'] == 'pending_start'
    (profile / 'openmw.cfg').write_text('')
    assert inspect_auto_fixes(root)['fixes']['tribunal_delay']['status'] == 'disabled'
    (root / 'local-settings.json').unlink()
    (root.parent / 'config/openmw.cfg').write_text('content=Morrowind.esm\n')
    assert inspect_auto_fixes(root)['fixes']['tribunal_delay']['status'] == 'not_applicable'


def test_detects_later_script_override(tmp_path):
    root, game, profile = setup(tmp_path)
    write_plugin(game / 'Later.esp')
    with (profile / 'openmw.cfg').open('a') as f: f.write('content=Later.esp\n')
    report = inspect_auto_fixes(root)['fixes']['tribunal_delay']
    assert report['status'] == 'overridden' and report['by'] == 'Later.esp'


def test_malformed_configuration_and_missing_generated_file(tmp_path):
    root, _, profile = setup(tmp_path)
    (root / 'runtime/data' / ADDON).unlink()
    assert inspect_auto_fixes(root)['fixes']['tribunal_delay']['status'] == 'needs_prepare'
    (root / 'local-settings.json').write_text('{')
    (profile / 'settings.cfg').write_text('bad ini')
    assert {r['status'] for r in inspect_auto_fixes(root)['fixes'].values()} == {'error'}

import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('prepare_release',Path(__file__).parents[1]/'prepare_release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def test_prerelease_updates_all_desktop_version_files(tmp_path):
    (tmp_path/'desktop').mkdir()
    (tmp_path/'VERSION.json').write_text(json.dumps({'project_version':'0.3.0-dev','protocol_version':1}))
    (tmp_path/'desktop/package.json').write_text(json.dumps({'name':'astrabridge','version':'0.3.0-dev'}))
    (tmp_path/'desktop/package-lock.json').write_text(json.dumps({'version':'0.3.0-dev','packages':{'':{'version':'0.3.0-dev'}}}))
    release.prepare(tmp_path,'v0.3.0-rc1')
    assert json.loads((tmp_path/'VERSION.json').read_text())=={'project_version':'0.3.0-rc1','protocol_version':1}
    assert json.loads((tmp_path/'desktop/package.json').read_text())['version']=='0.3.0-rc1'
    lock=json.loads((tmp_path/'desktop/package-lock.json').read_text())
    assert lock['version']==lock['packages']['']['version']=='0.3.0-rc1'
    release.prepare(tmp_path,'v0.3.0')
    with pytest.raises(ValueError,match='backwards'):release.prepare(tmp_path,'v0.3.0-rc1')
    assert json.loads((tmp_path/'VERSION.json').read_text())['project_version']=='0.3.0'


@pytest.mark.parametrize('value',['0.3.0-01','0.3.0-rc.01','0.3.0-','0.3.0+build','01.3.0','0.3.0\n','0.3.0;echo test'])
def test_invalid_release_versions_are_rejected(value):
    with pytest.raises(ValueError):release.version_key(value)


def test_numeric_prereleases_use_semver_precedence():
    assert release.version_key('0.3.0-rc.2')<release.version_key('0.3.0-rc.10')<release.version_key('0.3.0')


def test_existing_compact_rc_series_continues_past_nine():
    assert release.version_key('0.3.0-rc9')<release.version_key('0.3.0-rc10')<release.version_key('0.3.0-rc11')<release.version_key('0.3.0')

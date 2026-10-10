from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_external_actions_are_pinned_to_commit_sha():
    for workflow in (ROOT / '.github/workflows').glob('*.yml'):
        for action in re.findall(r'^\s+(?:-\s+)?uses:\s*(\S+)', workflow.read_text(), re.MULTILINE):
            if action.startswith('./'):
                continue
            assert re.fullmatch(r'[\w.-]+/[\w./-]+@[0-9a-f]{40}', action), (workflow.name, action)


def test_desktop_build_has_read_only_repository_permissions():
    workflow = (ROOT / '.github/workflows/container-release.yml').read_text()
    desktop_job = workflow.split('  desktop:\n', 1)[1].split('  draft:\n', 1)[0]
    assert '    permissions:\n      contents: read\n' in desktop_job
    assert 'packages: write' not in desktop_job

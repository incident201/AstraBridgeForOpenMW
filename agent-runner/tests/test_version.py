from pathlib import Path
import tomllib

from astrabridge_runner import __version__


def test_imported_version_matches_wheel_metadata():
    project = Path(__file__).resolve().parents[1] / 'pyproject.toml'
    metadata = tomllib.loads(project.read_text(encoding='utf-8'))
    assert __version__ == metadata['project']['version']

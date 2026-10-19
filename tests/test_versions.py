"""Tests for --version of the bash scripts.

Unlike test_update_sw.py these run real subprocesses: bash on the scripts in
bin/, which handle --version before they need pyenv.
"""

import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / 'bin'
SCRIPTS = ['update-python', 'update-venv']


def version_output(script):
    result = subprocess.run(
        ['bash', str(script), '--version'],
        capture_output=True,
        check=True,
        encoding='utf8',
    )
    return result.stdout


@pytest.mark.parametrize('name', SCRIPTS)
def test_version_from_repo(name):
    prefix, _, version = version_output(BIN / name).rstrip('\n').partition(' ')
    assert prefix == name
    assert version


@pytest.mark.parametrize('name', SCRIPTS)
def test_version_through_symlink(name, tmp_path):
    # Absolute and relative link targets, and a link to a link.
    absolute = tmp_path / f'abs-{name}'
    absolute.symlink_to(BIN / name)
    relative_dir = tmp_path / 'sub'
    relative_dir.mkdir()
    relative = relative_dir / f'rel-{name}'
    relative.symlink_to(Path('..') / f'abs-{name}')

    expected = version_output(BIN / name).split(' ', 1)[1]
    for link in (absolute, relative):
        out = version_output(link)
        assert out.startswith(f'{name} ')
        # Resolved back to the clone, so the same version, not 'unknown'.
        assert out.split(' ', 1)[1] == expected

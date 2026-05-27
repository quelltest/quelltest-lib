import pytest
from pathlib import Path
from quell.cli import _install_precommit_hook

def test_install_precommit_hook_missing(tmp_path: Path):
    _install_precommit_hook(tmp_path)
    config_file = tmp_path / ".pre-commit-config.yaml"
    assert config_file.exists()
    content = config_file.read_text()
    assert "id: quell" in content
    assert "entry: quell find --fix --auto" in content

def test_install_precommit_hook_exists(tmp_path: Path):
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.write_text("repos:\n  - repo: https://github.com/pre-commit/pre-commit-hooks\n")
    
    _install_precommit_hook(tmp_path)
    content = config_file.read_text()
    assert "id: quell" in content
    assert "entry: quell find --fix --auto" in content
    assert "pre-commit-hooks" in content

def test_install_precommit_hook_idempotent(tmp_path: Path):
    _install_precommit_hook(tmp_path)
    config_file = tmp_path / ".pre-commit-config.yaml"
    first_content = config_file.read_text()
    
    # Run again, should be a no-op
    _install_precommit_hook(tmp_path)
    second_content = config_file.read_text()
    assert first_content == second_content

"""Unit tests for quell.auth.storage (spec7 §3.3)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from quell.auth.storage import (
    Credentials,
    clear_credentials,
    is_configured,
    load_credentials,
    resolve_key,
    save_credentials,
)


@pytest.fixture(autouse=True)
def isolated_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect auth file to a temp directory for each test."""
    auth_file = tmp_path / "quell" / "auth.json"

    def _fake_path() -> Path:
        return auth_file

    monkeypatch.setattr("quell.auth.storage._auth_path", _fake_path)
    # Also patch the reference used inside save/load/clear
    import quell.auth.storage as _mod
    monkeypatch.setattr(_mod, "_auth_path", _fake_path)


class TestSaveAndLoad:
    def test_roundtrip_without_key(self):
        save_credentials("groq", "quell", key="")
        creds = load_credentials()
        assert creds is not None
        assert creds.provider == "groq"
        assert creds.mode == "quell"

    def test_roundtrip_with_plaintext_key(self):
        with patch("quell.auth.storage._try_keyring", return_value=False):
            save_credentials("groq", "byo", key="sk-test-123")
        creds = load_credentials()
        assert creds is not None
        assert creds.key_plaintext == "sk-test-123"

    def test_load_returns_none_when_no_file(self):
        assert load_credentials() is None

    def test_corrupt_file_returns_none(self, tmp_path: Path):
        import quell.auth.storage as _mod
        path = _mod._auth_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json", encoding="utf-8")
        assert load_credentials() is None

    def test_save_creates_parent_directories(self):
        save_credentials("anthropic", "byo", key="")
        # verify by loading back — indirect check that file was written
        assert load_credentials() is not None


class TestResolveKey:
    def test_resolve_plaintext_key(self):
        creds = Credentials(provider="groq", mode="byo", key_plaintext="my-key")
        with patch("quell.auth.storage._try_keyring", return_value=False):
            assert resolve_key(creds) == "my-key"

    def test_resolve_empty_key(self):
        creds = Credentials(provider="groq", mode="quell")
        with patch("quell.auth.storage._try_keyring", return_value=False):
            assert resolve_key(creds) == ""


class TestClearCredentials:
    def test_clear_removes_file(self):
        save_credentials("groq", "byo", key="")
        assert load_credentials() is not None  # file exists
        cleared = clear_credentials()
        assert cleared
        assert load_credentials() is None  # file gone

    def test_clear_when_nothing_stored_returns_false(self):
        assert not clear_credentials()

    def test_load_after_clear_returns_none(self):
        save_credentials("groq", "byo", key="")
        clear_credentials()
        assert load_credentials() is None


class TestIsConfigured:
    def test_not_configured_when_no_file(self):
        assert not is_configured()

    def test_configured_after_save(self):
        save_credentials("groq", "byo", key="sk-test")
        assert is_configured()

    def test_not_configured_for_none_provider(self):
        save_credentials("none", "none", key="")  # type: ignore[arg-type]
        assert not is_configured()

"""Tests for OAuth PKCE flow — no network calls."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from quell.auth.oauth import (
    _pkce_pair,
    _save_credentials,
    get_valid_token,
    load_credentials,
)


def test_pkce_pair_generates_distinct_values() -> None:
    v1, c1 = _pkce_pair()
    v2, c2 = _pkce_pair()
    assert v1 != v2
    assert c1 != c2
    assert len(v1) > 20
    assert len(c1) > 20


def test_pkce_challenge_is_base64url() -> None:
    _, challenge = _pkce_pair()
    assert "+" not in challenge
    assert "/" not in challenge


@pytest.mark.skipif(
    __import__("sys").platform == "win32",
    reason="Unix chmod not applicable on Windows",
)
def test_save_credentials_sets_chmod_600(tmp_path: Path) -> None:
    creds_path = tmp_path / ".quell" / "credentials.json"
    with patch("quell.auth.oauth.CREDENTIALS_PATH", creds_path):
        _save_credentials({"access_token": "test", "email": "a@b.com"})
    mode = oct(creds_path.stat().st_mode)[-3:]
    assert mode == "600"


def test_load_credentials_returns_none_when_missing(tmp_path: Path) -> None:
    with patch("quell.auth.oauth.CREDENTIALS_PATH", tmp_path / "missing.json"):
        assert load_credentials() is None


def test_load_credentials_from_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("QUELL_API_KEY", "qll_test_key")
    creds = load_credentials()
    assert creds is not None
    assert creds["access_token"] == "qll_test_key"


def test_get_valid_token_returns_none_when_not_logged_in(tmp_path: Path) -> None:
    with patch("quell.auth.oauth.CREDENTIALS_PATH", tmp_path / "missing.json"):
        assert get_valid_token() is None


def test_get_valid_token_refreshes_expired_token(tmp_path: Path) -> None:
    expired_creds = {
        "access_token": "old_token",
        "refresh_token": "refresh_me",
        "expires_at": time.time() - 100,
        "email": "test@test.com",
    }
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps(expired_creds))

    with patch("quell.auth.oauth.CREDENTIALS_PATH", creds_file):
        with patch("quell.auth.oauth._refresh_token") as mock_refresh:
            mock_refresh.return_value = {"access_token": "new_token"}
            token = get_valid_token()
            assert token == "new_token"
            mock_refresh.assert_called_once_with("refresh_me")


def test_get_valid_token_returns_token_when_valid(tmp_path: Path) -> None:
    valid_creds = {
        "access_token": "valid_token",
        "refresh_token": "refresh",
        "expires_at": time.time() + 3600,
        "email": "test@test.com",
    }
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps(valid_creds))

    with patch("quell.auth.oauth.CREDENTIALS_PATH", creds_file):
        token = get_valid_token()
        assert token == "valid_token"

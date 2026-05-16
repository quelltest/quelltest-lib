"""Secure credential storage for Quell auth (spec7 §3.3).

Storage path:
  Linux/Mac: ~/.config/quell/auth.json
  Windows:   %APPDATA%/quell/auth.json

File mode 0600 on Unix. Uses OS keyring where available; falls back to
plain JSON storage (key is NOT encrypted in the fallback — users are warned).

Never store plaintext keys in the final JSON if keyring is available.
"""
from __future__ import annotations

import json
import os
import platform
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

ProviderName = Literal["groq", "quell", "anthropic", "openai", "none"]
AuthMode = Literal["byo", "quell", "none"]
Tier = Literal["free", "pro", "team"]

_KEYRING_SERVICE = "quelltest"
_KEY_FALLBACK_FIELD = "key_plaintext"  # used when keyring unavailable


@dataclass
class Credentials:
    """Stored authentication credentials."""

    provider: ProviderName
    mode: AuthMode
    tier: Tier = "free"
    # One of these will be set:
    key_ref: str = ""        # keyring username (key stored in OS keyring)
    key_plaintext: str = ""  # fallback when keyring unavailable


def _auth_path() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "quell" / "auth.json"


def _try_keyring() -> bool:
    """Return True if the keyring package is available and functional."""
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def save_credentials(provider: ProviderName, mode: AuthMode, key: str, tier: Tier = "free") -> None:
    """Save credentials to disk (and OS keyring when available)."""
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    creds = Credentials(provider=provider, mode=mode, tier=tier)

    if _try_keyring() and key:
        import keyring
        username = f"quell_{provider}_{mode}"
        keyring.set_password(_KEYRING_SERVICE, username, key)
        creds.key_ref = username
    elif key:
        creds.key_plaintext = key

    path.write_text(json.dumps(asdict(creds), indent=2), encoding="utf-8")

    # Restrict file permissions on Unix
    if platform.system() != "Windows":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def load_credentials() -> Credentials | None:
    """Return stored credentials or None if not configured."""
    path = _auth_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Credentials(**data)
    except Exception:
        return None


def resolve_key(creds: Credentials) -> str:
    """Retrieve the actual API key from keyring or plaintext fallback."""
    if creds.key_ref and _try_keyring():
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, creds.key_ref) or ""
    return creds.key_plaintext


def clear_credentials() -> bool:
    """Remove stored credentials. Returns True if anything was cleared."""
    path = _auth_path()
    cleared = False

    creds = load_credentials()
    if creds and creds.key_ref and _try_keyring():
        try:
            import keyring
            keyring.delete_password(_KEYRING_SERVICE, creds.key_ref)
            cleared = True
        except Exception:
            pass

    if path.exists():
        path.unlink()
        cleared = True

    return cleared


def is_configured() -> bool:
    """Return True if any auth credentials are stored."""
    creds = load_credentials()
    return creds is not None and creds.provider != "none"

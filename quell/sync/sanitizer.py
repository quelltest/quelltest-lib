"""Sanitizer — the enforced gate between local data and any cloud call.

This is the single code path that may produce an outbound sync payload.
It has 100% branch coverage requirement (enforced in CI).

Allowlist model: only fields defined in SyncPayload may pass through.
Any unexpected key in a blocklisted namespace raises SanitizationError.
"""
from __future__ import annotations

from quell.sync.models import SyncPayload

# Keys that must NEVER appear in any sync payload at any nesting level.
_BLOCKLISTED_KEY_FRAGMENTS = frozenset({
    "source",
    "body",
    "code",
    "docstring",
    "content",
    "impl",
    "raw",
    "text",
    "function_body",
    "test_body",
})

_MAX_STRING_LENGTH = 500


class SanitizationError(ValueError):
    """Raised when a payload contains data that must never leave the machine."""


def _check_dict(obj: dict, path: str = "") -> None:
    """Recursively verify no blocklisted key exists in a nested dict."""
    for key, value in obj.items():
        full_path = f"{path}.{key}" if path else key
        lower_key = key.lower()
        for fragment in _BLOCKLISTED_KEY_FRAGMENTS:
            if fragment in lower_key:
                raise SanitizationError(
                    f"Blocklisted key '{key}' at '{full_path}' must not be synced. "
                    "Source code and test bodies must never leave the machine."
                )
        if isinstance(value, str) and len(value) > _MAX_STRING_LENGTH:
            raise SanitizationError(
                f"String value at '{full_path}' is {len(value)} chars "
                f"(max {_MAX_STRING_LENGTH}). Possible source code leak."
            )
        if isinstance(value, dict):
            _check_dict(value, full_path)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    _check_dict(item, f"{full_path}[{i}]")
                elif isinstance(item, str) and len(item) > _MAX_STRING_LENGTH:
                    raise SanitizationError(
                        f"String in list at '{full_path}[{i}]' is {len(item)} chars "
                        f"(max {_MAX_STRING_LENGTH}). Possible source code leak."
                    )


def sanitize(payload: dict) -> SyncPayload:
    """Validate and sanitize a raw payload dict before any cloud push.

    Raises SanitizationError if the payload contains blocklisted fields.
    Validates the result against SyncPayload schema before returning.
    """
    _check_dict(payload)

    # Validate via Pydantic — this is the schema enforcement step.
    # Any extra fields not in SyncPayload are silently ignored by Pydantic
    # (model_config would need to forbid them; here we rely on _check_dict above).
    return SyncPayload.model_validate(payload)

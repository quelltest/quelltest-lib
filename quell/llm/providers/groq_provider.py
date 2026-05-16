"""Groq LLM provider — fast inference, used as LLM fallback in quell find.

Auth priority (spec7 §3.1-3.4):
  1. Credentials from quell auth storage (~/.config/quell/auth.json)
  2. GROQ_API_KEY environment variable
  3. Raises RuntimeError — free tier uses rule engine only, not this provider

LLM is only called when:
  - User has valid auth (quell auth set --provider groq --key sk-...)
  - Case falls in the ~25% the rule engine can't handle
  - Case is NOT a FLAGGED category (env-dependent, object-state, etc.)
"""
from __future__ import annotations

import os

from quell.core.models import QuellConfig
from quell.llm.client import LLMClient

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_MAX_TOKENS = 1024


class GroqProvider(LLMClient):
    """Groq inference provider. Resolves key from auth storage or env."""

    def __init__(self, config: QuellConfig) -> None:
        self._model = getattr(config, "llm_model", _DEFAULT_MODEL) or _DEFAULT_MODEL
        self._api_key = self._resolve_key()

    def _resolve_key(self) -> str:
        """Return Groq API key from auth storage, then env, then raise."""
        try:
            from quell.auth.storage import is_configured, load_credentials, resolve_key
            if is_configured():
                creds = load_credentials()
                if creds and creds.provider == "groq":
                    key = resolve_key(creds)
                    if key:
                        return key
        except Exception:
            pass
        env_key = os.environ.get("GROQ_API_KEY", "")
        if env_key:
            return env_key
        raise RuntimeError(
            "No Groq API key found. Run: quell auth set --provider groq --key sk-..."
        )

    async def generate(self, prompt: str) -> str:
        """Send prompt to Groq and return the response text."""
        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError(
                "groq package not installed. Run: pip install groq"
            ) from exc

        client = Groq(api_key=self._api_key)
        response = client.chat.completions.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

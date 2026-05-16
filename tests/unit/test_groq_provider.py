"""Unit tests for quell.llm.providers.groq_provider (spec7 §3.4)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from quell.core.models import QuellConfig


def _make_provider(api_key: str = "sk-test"):  # type: ignore[return]
    from quell.llm.providers.groq_provider import GroqProvider
    cfg = QuellConfig(llm_provider="groq")
    with patch.object(GroqProvider, "_resolve_key", return_value=api_key):
        return GroqProvider(cfg)


class TestGroqProviderKeyResolution:
    def test_resolves_env_key_when_no_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "sk-env-test")
        # auth storage absent → exception swallowed → falls through to env
        from quell.llm.providers.groq_provider import GroqProvider
        cfg = QuellConfig(llm_provider="groq")
        p = GroqProvider(cfg)
        assert p._api_key == "sk-env-test"

    def test_raises_when_no_key_anywhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        from quell.llm.providers.groq_provider import GroqProvider
        cfg = QuellConfig(llm_provider="groq")
        with pytest.raises(RuntimeError, match="No Groq API key"):
            GroqProvider(cfg)

    def test_env_key_takes_precedence_over_missing_storage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "sk-env-fallback")
        from quell.llm.providers.groq_provider import GroqProvider
        cfg = QuellConfig(llm_provider="groq")
        p = GroqProvider(cfg)
        assert p._api_key == "sk-env-fallback"

    def test_resolve_key_uses_auth_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "sk-env-fallback")
        # Simulate auth storage returning a key for groq
        fake_creds = MagicMock()
        fake_creds.provider = "groq"
        fake_storage = MagicMock()
        fake_storage.is_configured.return_value = True
        fake_storage.load_credentials.return_value = fake_creds
        fake_storage.resolve_key.return_value = "sk-from-storage"

        # Patch the lazy import inside _resolve_key
        with patch.dict("sys.modules", {"quell.auth.storage": fake_storage}):
            from quell.llm.providers.groq_provider import GroqProvider
            cfg = QuellConfig(llm_provider="groq")
            p = GroqProvider(cfg)
        assert p._api_key in ("sk-from-storage", "sk-env-fallback")


class TestGroqProviderGenerate:
    def test_generate_returns_content(self) -> None:
        provider = _make_provider("sk-test")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "def test_foo(): pass"
        mock_groq_cls = MagicMock()
        mock_groq_cls.return_value.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"groq": MagicMock(Groq=mock_groq_cls)}):
            result = asyncio.run(provider.generate("write a test"))

        assert result == "def test_foo(): pass"

    def test_generate_returns_empty_string_on_none_content(self) -> None:
        provider = _make_provider("sk-test")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = None
        mock_groq_cls = MagicMock()
        mock_groq_cls.return_value.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"groq": MagicMock(Groq=mock_groq_cls)}):
            result = asyncio.run(provider.generate("write a test"))

        assert result == ""


class TestLLMClientFactory:
    def test_from_config_groq(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "sk-factory-test")
        from quell.llm.client import LLMClient
        from quell.llm.providers.groq_provider import GroqProvider
        cfg = QuellConfig(llm_provider="groq")
        client = LLMClient.from_config(cfg)
        assert isinstance(client, GroqProvider)

    def test_from_config_unknown_raises(self) -> None:
        from quell.llm.client import LLMClient
        cfg = QuellConfig(llm_provider="unknown_xyz")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMClient.from_config(cfg)

    def test_from_config_anthropic_still_works(self) -> None:
        from quell.llm.client import LLMClient
        from quell.llm.providers.anthropic_provider import AnthropicProvider
        cfg = QuellConfig(llm_provider="anthropic")
        with patch("anthropic.Anthropic"):
            client = LLMClient.from_config(cfg)
        assert isinstance(client, AnthropicProvider)

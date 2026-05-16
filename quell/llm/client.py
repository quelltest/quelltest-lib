"""Abstract LLM client + factory."""
from __future__ import annotations

from abc import ABC, abstractmethod

from quell.core.models import QuellConfig


class LLMClient(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Send prompt, return text response."""
        ...

    @classmethod
    def from_config(cls, config: QuellConfig) -> LLMClient:
        """Factory: create provider from config."""
        from quell.llm.providers.anthropic_provider import AnthropicProvider
        from quell.llm.providers.groq_provider import GroqProvider
        from quell.llm.providers.ollama_provider import OllamaProvider
        from quell.llm.providers.openai_provider import OpenAIProvider
        providers = {
            "anthropic": AnthropicProvider,
            "openai": OpenAIProvider,
            "ollama": OllamaProvider,
            "groq": GroqProvider,
        }
        provider_cls = providers.get(config.llm_provider)
        if provider_cls is None:
            raise ValueError(
                f"Unknown LLM provider {config.llm_provider!r}. "
                f"Supported: {list(providers)}"
            )
        return provider_cls(config)  # type: ignore[return-value]

    @classmethod
    def from_auth(cls) -> LLMClient:
        """Create a Groq provider using stored auth credentials (spec7 §3.4)."""
        from quell.llm.providers.groq_provider import GroqProvider
        config = QuellConfig(llm_provider="groq", llm_model="llama-3.3-70b-versatile")
        return GroqProvider(config)

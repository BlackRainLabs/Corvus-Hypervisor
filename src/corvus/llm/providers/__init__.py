"""LLM provider adapters."""

from corvus.llm.providers.openai_compat import OpenAiCompatProviderAdapter
from corvus.llm.providers.stub import StubProviderAdapter

__all__ = ["OpenAiCompatProviderAdapter", "StubProviderAdapter"]

"""Load server-owned LLM provider registry from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from corvus.server.catalog import LLMProviderCatalogEntry


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    api_base_url: str
    credential_ref: str
    supported_models: list[str]
    hosted_tools_allowed: bool = False
    allowed_hosted_tools: list[str] = field(default_factory=list)

    def to_catalog_entry(self) -> LLMProviderCatalogEntry:
        return LLMProviderCatalogEntry(
            provider_id=self.provider_id,
            supported_models=list(self.supported_models),
            credential_ref=self.credential_ref,
            quota_class="dev",
            hosted_tools_allowed=self.hosted_tools_allowed,
            allowed_hosted_tools=list(self.allowed_hosted_tools),
        )

    def public_payload(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "supported_models": list(self.supported_models),
            "hosted_tools_allowed": self.hosted_tools_allowed,
            "allowed_hosted_tools": list(self.allowed_hosted_tools),
        }


class LlmProviderRegistry:
    def __init__(self, providers: dict[str, ProviderConfig]) -> None:
        self.providers = providers

    def get(self, provider_id: str) -> ProviderConfig | None:
        return self.providers.get(provider_id)

    def public_providers(self) -> list[dict[str, Any]]:
        return [provider.public_payload() for provider in self.providers.values()]

    @classmethod
    def load(cls, path: Path) -> LlmProviderRegistry:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        providers: dict[str, ProviderConfig] = {}
        for provider_id, entry in (raw.get("providers") or {}).items():
            providers[str(provider_id)] = ProviderConfig(
                provider_id=str(provider_id),
                api_base_url=str(entry["api_base_url"]),
                credential_ref=str(entry.get("credential_ref", "none")),
                supported_models=[str(model) for model in entry.get("supported_models", [])],
                hosted_tools_allowed=bool(entry.get("hosted_tools_allowed", False)),
                allowed_hosted_tools=[
                    str(tool) for tool in entry.get("allowed_hosted_tools", [])
                ],
            )
        if not providers:
            raise ValueError(f"no LLM providers defined in {path}")
        return cls(providers)

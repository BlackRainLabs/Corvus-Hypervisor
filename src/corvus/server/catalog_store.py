"""DB-backed capability catalog with DEFAULT_CATALOG seed."""

from __future__ import annotations

from typing import Any

from corvus.server.catalog import (
    DEFAULT_CATALOG,
    CapabilityCatalog,
    LLMProviderCatalogEntry,
    MemoryNamespaceTemplate,
    SkillCatalogEntry,
    ToolCatalogEntry,
    WorkspaceCatalogEntry,
)
from corvus.server.db import Database

_KIND_MODELS = {
    "tools": (ToolCatalogEntry, "name"),
    "skills": (SkillCatalogEntry, "name"),
    "workspaces": (WorkspaceCatalogEntry, "id"),
    "memory_namespaces": (MemoryNamespaceTemplate, "name"),
    "llm_providers": (LLMProviderCatalogEntry, "provider_id"),
}


class CatalogStore:
    """Loads catalog entries from SQLite; seeds from DEFAULT_CATALOG when empty."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._catalog = DEFAULT_CATALOG.model_copy(deep=True)

    @property
    def catalog(self) -> CapabilityCatalog:
        return self._catalog

    async def ensure_seeded(self) -> None:
        mapping = {
            "tools": DEFAULT_CATALOG.tools,
            "skills": DEFAULT_CATALOG.skills,
            "workspaces": DEFAULT_CATALOG.workspaces,
            "memory_namespaces": DEFAULT_CATALOG.memory_namespaces,
            # llm_providers seeded from YAML registry in AppContext.startup
        }
        for kind, entries in mapping.items():
            if await self.db.catalog_kind_empty(kind):
                for entry_id, entry in entries.items():
                    await self.db.upsert_catalog_entry(
                        kind, entry_id, entry.model_dump(mode="json")
                    )
        await self.reload()

    async def seed_llm_providers_from_registry(self, registry) -> None:
        """Seed provider rows once from YAML registry; never overwrite existing DB."""
        if not await self.db.catalog_kind_empty("llm_providers"):
            await self.reload()
            return
        for provider in registry.providers.values():
            await self.db.upsert_catalog_entry(
                "llm_providers",
                provider.provider_id,
                provider.to_catalog_entry().model_dump(mode="json"),
            )
        await self.reload()

    def rebuild_llm_registry(self):
        from corvus.llm.registry import LlmProviderRegistry, ProviderConfig

        providers = {
            pid: ProviderConfig.from_catalog_entry(entry)
            for pid, entry in self._catalog.llm_providers.items()
        }
        if not providers:
            return None
        return LlmProviderRegistry(providers)

    async def reload(self) -> CapabilityCatalog:
        tools = {
            e["name"]: ToolCatalogEntry.model_validate(e)
            for e in await self.db.list_catalog_entries("tools")
        }
        skills = {
            e["name"]: SkillCatalogEntry.model_validate(e)
            for e in await self.db.list_catalog_entries("skills")
        }
        workspaces = {
            e["id"]: WorkspaceCatalogEntry.model_validate(e)
            for e in await self.db.list_catalog_entries("workspaces")
        }
        memory_namespaces = {
            e["name"]: MemoryNamespaceTemplate.model_validate(e)
            for e in await self.db.list_catalog_entries("memory_namespaces")
        }
        llm_providers = {
            e["provider_id"]: LLMProviderCatalogEntry.model_validate(e)
            for e in await self.db.list_catalog_entries("llm_providers")
        }
        self._catalog = CapabilityCatalog(
            tools=tools,
            skills=skills,
            workspaces=workspaces,
            memory_namespaces=memory_namespaces,
            llm_providers=llm_providers,
        )
        return self._catalog

    async def upsert(self, kind: str, entry: dict[str, Any]) -> dict[str, Any]:
        if kind not in _KIND_MODELS:
            raise ValueError(f"Unknown catalog kind: {kind}")
        model_cls, id_field = _KIND_MODELS[kind]
        parsed = model_cls.model_validate(entry)
        entry_id = getattr(parsed, id_field)
        payload = parsed.model_dump(mode="json")
        await self.db.upsert_catalog_entry(kind, entry_id, payload)
        await self.reload()
        return payload

    async def delete(self, kind: str, entry_id: str) -> bool:
        if kind not in _KIND_MODELS:
            raise ValueError(f"Unknown catalog kind: {kind}")
        ok = await self.db.delete_catalog_entry(kind, entry_id)
        if ok:
            await self.reload()
        return ok

"""Server-owned capability catalogs for launch-time manifest resolution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ToolCatalogEntry(BaseModel):
    name: str
    version: str
    entrypoint: str
    permissions: list[str] = Field(default_factory=list)
    package_source: str
    required_files: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"


class SkillCatalogEntry(BaseModel):
    name: str
    version: str
    runtime_dependencies: list[str] = Field(default_factory=list)
    exposed_tool_schemas: list[str] = Field(default_factory=list)
    package_source: str


class LLMProviderCatalogEntry(BaseModel):
    provider_id: str
    supported_models: list[str]
    credential_ref: str
    quota_class: str = "dev"
    hosted_tools_allowed: bool = False
    allowed_hosted_tools: list[str] = Field(default_factory=list)


class WorkspaceCatalogEntry(BaseModel):
    id: str
    source: str
    mount_path: str
    mount_mode: Literal["ro", "rw"] = "ro"
    allowed_agents: list[str] = Field(default_factory=lambda: ["*"])
    retention_policy: str = "ephemeral"


class MemoryNamespaceQuota(BaseModel):
    max_records: int = 1000
    max_record_bytes: int = 65536
    default_ttl_seconds: int | None = None


class MemoryNamespaceTemplate(BaseModel):
    name: str
    quota: MemoryNamespaceQuota = Field(default_factory=MemoryNamespaceQuota)
    retention_policy: str = "agent-private"


class CapabilityCatalog(BaseModel):
    tools: dict[str, ToolCatalogEntry]
    skills: dict[str, SkillCatalogEntry]
    llm_providers: dict[str, LLMProviderCatalogEntry]
    workspaces: dict[str, WorkspaceCatalogEntry]
    memory_namespaces: dict[str, MemoryNamespaceTemplate]

    def api_payload(self) -> dict[str, list[dict]]:
        return {
            "tools": [entry.model_dump(mode="json") for entry in self.tools.values()],
            "skills": [entry.model_dump(mode="json") for entry in self.skills.values()],
            "llm_providers": [
                entry.model_dump(mode="json") for entry in self.llm_providers.values()
            ],
            "workspaces": [
                entry.model_dump(mode="json") for entry in self.workspaces.values()
            ],
            "memory_namespaces": [
                entry.model_dump(mode="json") for entry in self.memory_namespaces.values()
            ],
        }


DEFAULT_CATALOG = CapabilityCatalog(
    tools={
        "echo": ToolCatalogEntry(
            name="echo",
            version="1.0",
            entrypoint="corvus.tools.echo",
            permissions=["stdout"],
            package_source="builtin",
            risk_level="low",
        ),
        "terminal": ToolCatalogEntry(
            name="terminal",
            version="1.0",
            entrypoint="corvus.tools.terminal",
            permissions=["subprocess"],
            package_source="builtin",
            risk_level="medium",
        ),
        "file_read": ToolCatalogEntry(
            name="file_read",
            version="1.0",
            entrypoint="corvus.tools.file_read",
            permissions=["fs:read"],
            package_source="builtin",
            risk_level="low",
        ),
    },
    skills={
        "base-runtime": SkillCatalogEntry(
            name="base-runtime",
            version="1.0",
            runtime_dependencies=["corvus-runtime"],
            exposed_tool_schemas=[],
            package_source="builtin",
        )
    },
    llm_providers={
        "openai": LLMProviderCatalogEntry(
            provider_id="openai",
            supported_models=["gpt-4", "gpt-4o", "gpt-4.1"],
            credential_ref="env:OPENAI_API_KEY",
            quota_class="dev",
        ),
        "stub": LLMProviderCatalogEntry(
            provider_id="stub",
            supported_models=["stub-v1"],
            credential_ref="none",
            quota_class="dev",
        ),
        "dummy-http": LLMProviderCatalogEntry(
            provider_id="dummy-http",
            supported_models=["dummy-v1"],
            credential_ref="none",
            quota_class="dev",
        ),
    },
    workspaces={
        "default": WorkspaceCatalogEntry(
            id="default",
            source="/srv/corvus/workspaces/default",
            mount_path="/workspace",
            mount_mode="rw",
        )
    },
    memory_namespaces={
        "private": MemoryNamespaceTemplate(name="private"),
        "shared-knowledge": MemoryNamespaceTemplate(
            name="shared-knowledge",
            retention_policy="explicit-grant",
        ),
    },
)

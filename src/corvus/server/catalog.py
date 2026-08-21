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
    format: Literal["builtin", "agentskills"] = "builtin"
    content_hash: str | None = None
    source_uri: str | None = None
    source_pin: str | None = None
    allow_scripts: bool = False
    install_status: Literal["approved", "pending", "rejected"] = "approved"
    description: str = ""
    store_path: str | None = None


class LLMProviderCatalogEntry(BaseModel):
    provider_id: str
    supported_models: list[str]
    credential_ref: str
    api_base_url: str = "stub://local"
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
        "skill_read": ToolCatalogEntry(
            name="skill_read",
            version="1.0",
            entrypoint="corvus.skills.runner",
            permissions=["skill:read"],
            package_source="builtin",
            risk_level="low",
        ),
        "skill_run": ToolCatalogEntry(
            name="skill_run",
            version="1.0",
            entrypoint="corvus.skills.runner",
            permissions=["skill:run"],
            package_source="builtin",
            risk_level="high",
        ),
    },
    skills={
        "base-runtime": SkillCatalogEntry(
            name="base-runtime",
            version="1.0",
            runtime_dependencies=["corvus-runtime"],
            exposed_tool_schemas=["skill_read", "skill_run"],
            package_source="builtin",
            format="builtin",
            description="Builtin Corvus runtime skill (ping / instruction stub).",
            allow_scripts=False,
            install_status="approved",
            content_hash="builtin:base-runtime:1.0",
        )
    },
    llm_providers={
        "openai": LLMProviderCatalogEntry(
            provider_id="openai",
            supported_models=["gpt-4", "gpt-4o", "gpt-4.1"],
            credential_ref="env:OPENAI_API_KEY",
            api_base_url="https://api.openai.com/v1",
            quota_class="dev",
        ),
        "stub": LLMProviderCatalogEntry(
            provider_id="stub",
            supported_models=["stub-v1"],
            credential_ref="none",
            api_base_url="stub://local",
            quota_class="dev",
        ),
        "dummy-http": LLMProviderCatalogEntry(
            provider_id="dummy-http",
            supported_models=["dummy-v1"],
            credential_ref="none",
            api_base_url="http://127.0.0.1:8765/v1",
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

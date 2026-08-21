"""Typed launch manifest contract and canonicalization helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from corvus.server.catalog import DEFAULT_CATALOG, CapabilityCatalog


class Engine1Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[str] = Field(default_factory=list)


class Engine2Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platforms: list[str] = Field(default_factory=lambda: ["api"])


class Engine3Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_providers: list[str] = Field(default_factory=lambda: ["stub"])
    allowed_models: list[str] = Field(default_factory=lambda: ["stub-v1"])
    tool_execution_mode: Literal["local", "hybrid"] = "local"
    provider_tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tool_execution(self) -> Engine3Manifest:
        if self.tool_execution_mode == "local" and self.provider_tools:
            raise ValueError(
                "provider_tools must be empty when tool_execution_mode is local"
            )
        return self


class Engine4Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespaces: list[str] = Field(default_factory=list)


class EngineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine1: Engine1Manifest = Field(default_factory=Engine1Manifest)
    engine2: Engine2Manifest = Field(default_factory=Engine2Manifest)
    engine3: Engine3Manifest = Field(default_factory=Engine3Manifest)
    engine4: Engine4Manifest = Field(default_factory=Engine4Manifest)


class LaunchGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent: str
    namespace: str
    permissions: list[Literal["read", "write", "delete"]]
    expires_at: datetime | None = None

    @field_validator("permissions")
    @classmethod
    def permissions_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("launch grant permissions must not be empty")
        return value


class ResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_mb: int = Field(default=512, ge=128, le=65536)
    vcpu_count: int = Field(default=1, ge=1, le=64)


class WorkspaceMount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = "default"
    mount_path: str = "/workspace"
    mode: Literal["ro", "rw"] = "rw"


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: Literal["1.0"] = "1.0"
    engines: EngineManifest = Field(default_factory=EngineManifest)
    skills: list[str] = Field(default_factory=list)
    workspaces: list[WorkspaceMount] = Field(default_factory=list)
    launch_grants: list[LaunchGrant] = Field(default_factory=list)
    rootfs_image: str = "corvus-test-rootfs"
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)

    @model_validator(mode="after")
    def default_workspace(self) -> AgentManifest:
        if not self.workspaces:
            self.workspaces = [WorkspaceMount()]
        return self


def canonical_manifest(manifest: AgentManifest | dict[str, Any]) -> dict[str, Any]:
    model = (
        manifest
        if isinstance(manifest, AgentManifest)
        else AgentManifest.model_validate(manifest)
    )
    return model.model_dump(mode="json", exclude_none=True)


def manifest_hash(manifest: AgentManifest | dict[str, Any]) -> str:
    canonical = json.dumps(canonical_manifest(manifest), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def sync_llm_registry_to_catalog(registry) -> None:
    """Merge YAML provider registry into the server catalog for manifest validation."""
    for provider_id, config in registry.providers.items():
        DEFAULT_CATALOG.llm_providers[provider_id] = config.to_catalog_entry()


def resolve_manifest(
    manifest: AgentManifest | dict[str, Any],
    catalog: CapabilityCatalog = DEFAULT_CATALOG,
) -> AgentManifest:
    model = (
        manifest
        if isinstance(manifest, AgentManifest)
        else AgentManifest.model_validate(manifest)
    )

    unknown_tools = sorted(set(model.engines.engine1.tools) - set(catalog.tools))
    if unknown_tools:
        raise ValueError(f"Unknown tool catalog entries: {', '.join(unknown_tools)}")

    unknown_skills = sorted(set(model.skills) - set(catalog.skills))
    if unknown_skills:
        raise ValueError(f"Unknown skill catalog entries: {', '.join(unknown_skills)}")

    unknown_providers = sorted(
        set(model.engines.engine3.allowed_providers) - set(catalog.llm_providers)
    )
    if unknown_providers:
        raise ValueError(f"Unknown LLM providers: {', '.join(unknown_providers)}")

    supported_models = {
        model_name
        for provider_id in model.engines.engine3.allowed_providers
        for model_name in catalog.llm_providers[provider_id].supported_models
    }
    unknown_models = sorted(set(model.engines.engine3.allowed_models) - supported_models)
    if unknown_models:
        raise ValueError(f"Unsupported LLM models: {', '.join(unknown_models)}")

    if model.engines.engine3.tool_execution_mode == "hybrid":
        for entry in model.engines.engine3.provider_tools:
            if ":" not in entry:
                raise ValueError(f"Invalid provider_tools entry: {entry}")
            provider_id, tool_name = entry.split(":", 1)
            if provider_id not in catalog.llm_providers:
                raise ValueError(f"Unknown provider in provider_tools: {provider_id}")
            provider_entry = catalog.llm_providers[provider_id]
            if not provider_entry.hosted_tools_allowed:
                raise ValueError(
                    f"Provider {provider_id} does not allow hosted tools"
                )
            if tool_name not in provider_entry.allowed_hosted_tools:
                raise ValueError(
                    f"Hosted tool {tool_name} not allowed for provider {provider_id}"
                )

    workspace_ids = {workspace.workspace_id for workspace in model.workspaces}
    unknown_workspaces = sorted(workspace_ids - set(catalog.workspaces))
    if unknown_workspaces:
        raise ValueError(f"Unknown workspace catalog entries: {', '.join(unknown_workspaces)}")

    namespaces = set(model.engines.engine4.namespaces)
    namespaces.update(grant.namespace for grant in model.launch_grants)
    unknown_namespaces = sorted(namespaces - set(catalog.memory_namespaces))
    if unknown_namespaces:
        raise ValueError(f"Unknown memory namespace templates: {', '.join(unknown_namespaces)}")

    return AgentManifest.model_validate(canonical_manifest(model))


def default_chat_manifest() -> AgentManifest:
    """Minimal chat-only manifest: stub LLM, no tools/skills/memory."""
    return resolve_manifest(AgentManifest())


def full_capability_manifest() -> AgentManifest:
    """Dev/test manifest with tools, memory namespaces, and optional skills."""
    return resolve_manifest(
        {
            "manifest_version": "1.0",
            "engines": {
                "engine1": {
                    "tools": ["echo", "terminal", "file_read", "skill_read", "skill_run"]
                },
                "engine2": {"platforms": ["api"]},
                "engine3": {
                    "allowed_providers": ["openai", "stub", "dummy-http"],
                    "allowed_models": ["gpt-4", "stub-v1", "dummy-v1"],
                },
                "engine4": {"namespaces": ["private"]},
            },
            "skills": ["base-runtime"],
            "launch_grants": [],
            "rootfs_image": "corvus-test-rootfs",
            "resource_limits": {"memory_mb": 512, "vcpu_count": 1},
        }
    )

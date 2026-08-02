"""Operator Console — server-rendered GUI mounted on the Management API.

Zero-build: Jinja2 templates + HTMX + Alpine.js (vendored). Every handler is a
presentation layer over the existing ``/v1`` JSON endpoints (reused in-process
via :class:`ApiClient`) plus read-only display of server config.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from corvus.management.ui_client import (
    COOKIE_NAME,
    NAV,
    SESSION_MAX_AGE_SECONDS,
    ApiClient,
    session_user_id,
    sign_session_for_user,
    verify_session,
)
from corvus.server.bootstrap import AppContext
from corvus.server.config import ServerConfig

_HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"

_REDACTED_CONFIG_FIELDS = {"api_key", "memory_master_key", "ui_session_secret"}

# Roles permitted to sign in to the operator console.
CONSOLE_ROLES = {"admin", "operator"}


def _config_view(config: ServerConfig) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for f in dataclasses.fields(config):
        value = getattr(config, f.name)
        if f.name in _REDACTED_CONFIG_FIELDS:
            display = "********" if value else "(unset)"
        elif isinstance(value, Path):
            display = str(value)
        elif value is None:
            display = "(unset)"
        else:
            display = str(value)
        rows.append({"name": f.name, "value": display})
    return rows


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def mount_ui(app: FastAPI, ctx: AppContext) -> None:
    """Attach the operator console router + static assets to ``app``."""
    config = ctx.config
    prefix = config.ui_path_prefix.rstrip("/") or "/ui"
    secret = config.ui_session_secret or secrets.token_hex(32)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    api = ApiClient(app, config.api_key)

    app.mount(
        f"{prefix}/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="corvus-ui-static",
    )

    def login_url() -> str:
        return f"{prefix}/login"

    def require_session(request: Request) -> str:
        token = request.cookies.get(COOKIE_NAME)
        if not verify_session(secret, token):
            raise HTTPException(status_code=307, headers={"Location": login_url()})
        return session_user_id(token) or "operator"

    def render(
        request: Request,
        name: str,
        active: str,
        **context: Any,
    ) -> HTMLResponse:
        base = {
            "request": request,
            "nav": NAV,
            "active": active,
            "prefix": prefix,
            "static_url": f"{prefix}/static",
            "current_user": session_user_id(request.cookies.get(COOKIE_NAME)),
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        }
        base.update(context)
        return templates.TemplateResponse(request, name, base)

    def redirect(path: str, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
        query = {k: v for k, v in {"msg": msg, "err": err}.items() if v}
        target = f"{prefix}{path}"
        if query:
            target = f"{target}?{urlencode(query)}"
        return RedirectResponse(target, status_code=303)

    def _error_text(data: Any, fallback: str) -> str:
        if isinstance(data, dict):
            return str(data.get("message") or data.get("code") or fallback)
        return fallback

    router = APIRouter(prefix=prefix)

    # ---- Auth -------------------------------------------------------------
    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "prefix": prefix,
                "static_url": f"{prefix}/static",
                "err": request.query_params.get("err"),
            },
        )

    @router.post("/login")
    async def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> RedirectResponse:
        user = await ctx.db.get_user(username)
        authenticated = (
            user is not None
            and user.get("role") in CONSOLE_ROLES
            and await ctx.db.verify_user_secret(username, password)
        )
        if not authenticated:
            return RedirectResponse(
                f"{login_url()}?err=Invalid+credentials", status_code=303
            )
        resp = RedirectResponse(f"{prefix}/", status_code=303)
        resp.set_cookie(
            COOKIE_NAME,
            sign_session_for_user(secret, username),
            httponly=True,
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
        )
        return resp

    @router.get("/logout")
    async def logout() -> RedirectResponse:
        resp = RedirectResponse(login_url(), status_code=303)
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp

    # ---- Summary ----------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    async def summary(request: Request) -> HTMLResponse:
        require_session(request)
        health = await api.get("/v1/health")
        elevations = await api.get("/v1/elevations", params={"status": "pending"})
        audit = await api.get("/v1/audit/logs", params={"limit": 8})
        return render(
            request,
            "summary.html",
            "summary",
            health=health,
            pending_elevations=elevations.get("elevations", []),
            recent_audit=audit.get("logs", []),
        )

    @router.get("/partials/health", response_class=HTMLResponse)
    async def health_partial(request: Request) -> HTMLResponse:
        require_session(request)
        health = await api.get("/v1/health")
        return templates.TemplateResponse(
            request,
            "partials/health_tiles.html",
            {"request": request, "health": health},
        )

    # ---- Agents -----------------------------------------------------------
    @router.get("/agents", response_class=HTMLResponse)
    async def agents_page(request: Request) -> HTMLResponse:
        require_session(request)
        agents = await api.get("/v1/agents")
        catalog_tools = await api.get("/v1/catalog/tools")
        catalog_skills = await api.get("/v1/catalog/skills")
        catalog_providers = await api.get("/v1/catalog/llm-providers")
        catalog_ws = await api.get("/v1/catalog/workspaces")
        return render(
            request,
            "agents.html",
            "agents",
            agents=agents.get("agents", []),
            tools=catalog_tools.get("tools", []),
            skills=catalog_skills.get("skills", []),
            providers=catalog_providers.get("llm_providers", []),
            namespaces=catalog_ws.get("memory_namespaces", []),
            workspaces=catalog_ws.get("workspaces", []),
        )

    @router.get("/agents/{agent_id}", response_class=HTMLResponse)
    async def agent_detail(request: Request, agent_id: str) -> HTMLResponse:
        require_session(request)
        ok, manifest, _ = await api.call("GET", f"/v1/agents/{agent_id}/manifest")
        if not ok:
            return redirect("/agents", err=_error_text(manifest, "Agent not found"))
        vms = await api.get(f"/v1/agents/{agent_id}/vms")
        namespaces = await api.get(f"/v1/agents/{agent_id}/namespaces")
        return render(
            request,
            "agent_detail.html",
            "agents",
            agent_id=agent_id,
            manifest=manifest.get("manifest", {}),
            manifest_hash=manifest.get("manifest_hash", ""),
            manifest_json=json.dumps(manifest.get("manifest", {}), indent=2),
            vms=vms.get("vms", []),
            namespaces=namespaces.get("namespaces", []),
        )

    @router.post("/agents/create")
    async def agent_create(
        request: Request,
        agent_id: str = Form(...),
        tools: list[str] = Form(default=[]),
        skills: list[str] = Form(default=[]),
        allowed_providers: list[str] = Form(default=[]),
        allowed_models: str = Form(default=""),
        namespaces: list[str] = Form(default=[]),
        platforms: str = Form(default="api"),
        tool_execution_mode: str = Form(default="local"),
        provider_tools: str = Form(default=""),
        workspaces: list[str] = Form(default=[]),
        rootfs_image: str = Form(default="corvus-test-rootfs"),
        namespace_permissions: str = Form(default="read,write"),
        launch_grants_json: str = Form(default=""),
        memory_mb: int = Form(default=512),
        vcpu_count: int = Form(default=1),
    ) -> RedirectResponse:
        require_session(request)
        engines: dict[str, Any] = {}
        if tools:
            engines["engine1"] = {"tools": tools}
        platform_list = _split_csv(platforms) or ["api"]
        engines["engine2"] = {"platforms": platform_list}
        if allowed_providers or allowed_models or tool_execution_mode or provider_tools:
            engine3: dict[str, Any] = {
                "allowed_providers": allowed_providers or ["stub"],
                "allowed_models": _split_csv(allowed_models) or ["stub-v1"],
                "tool_execution_mode": tool_execution_mode or "local",
                "provider_tools": _split_csv(provider_tools),
            }
            engines["engine3"] = engine3
        if namespaces:
            engines["engine4"] = {"namespaces": namespaces}
        manifest: dict[str, Any] = {"manifest_version": "1.0", "engines": engines}
        if skills:
            manifest["skills"] = skills
        if workspaces:
            manifest["workspaces"] = [
                {"workspace_id": wid, "mount_path": "/workspace", "mode": "rw"}
                for wid in workspaces
            ]
        if rootfs_image:
            manifest["rootfs_image"] = rootfs_image
        launch_grants: list[dict[str, Any]] = []
        if launch_grants_json.strip():
            try:
                parsed = json.loads(launch_grants_json)
                if not isinstance(parsed, list):
                    return redirect("/agents", err="launch_grants_json must be a JSON array")
                launch_grants = parsed
            except json.JSONDecodeError:
                return redirect("/agents", err="Invalid launch_grants_json")
        if launch_grants:
            manifest["launch_grants"] = launch_grants
        # namespace_permissions is reserved for day-2 docs/UI hint; namespaces list is authoritative
        _ = namespace_permissions
        manifest["resource_limits"] = {"memory_mb": memory_mb, "vcpu_count": vcpu_count}
        ok, data, _ = await api.call(
            "POST", "/v1/agents", json={"id": agent_id, "manifest": manifest}
        )
        if not ok:
            return redirect("/agents", err=_error_text(data, "Create failed"))
        return redirect("/agents", msg=f"Agent {agent_id} created")

    @router.post("/agents/{agent_id}/launch")
    async def agent_launch(request: Request, agent_id: str) -> RedirectResponse:
        require_session(request)
        ok, data, _ = await api.call("POST", f"/v1/agents/{agent_id}/launch")
        if not ok:
            return redirect(f"/agents/{agent_id}", err=_error_text(data, "Launch failed"))
        return redirect(f"/agents/{agent_id}", msg="VM launch requested")

    @router.post("/agents/{agent_id}/stop")
    async def agent_stop(request: Request, agent_id: str) -> RedirectResponse:
        require_session(request)
        ok, data, _ = await api.call("POST", f"/v1/agents/{agent_id}/stop")
        if not ok:
            return redirect(f"/agents/{agent_id}", err=_error_text(data, "Stop failed"))
        return redirect(f"/agents/{agent_id}", msg="VM stop requested")

    @router.post("/agents/{agent_id}/namespaces/{namespace}")
    async def agent_namespace_patch(
        request: Request,
        agent_id: str,
        namespace: str,
        max_records: int = Form(...),
        max_record_bytes: int = Form(...),
        default_ttl_seconds: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        payload: dict[str, Any] = {
            "max_records": max_records,
            "max_record_bytes": max_record_bytes,
            "default_ttl_seconds": int(default_ttl_seconds) if default_ttl_seconds else None,
        }
        ok, data, _ = await api.call(
            "PATCH", f"/v1/agents/{agent_id}/namespaces/{namespace}", json=payload
        )
        if not ok:
            return redirect(f"/agents/{agent_id}", err=_error_text(data, "Quota update failed"))
        return redirect(f"/agents/{agent_id}", msg=f"Namespace {namespace} updated")

    @router.post("/agents/{agent_id}/patch")
    async def agent_patch(
        request: Request,
        agent_id: str,
        manifest_json: str = Form(...),
    ) -> RedirectResponse:
        require_session(request)
        try:
            manifest = json.loads(manifest_json)
        except json.JSONDecodeError:
            return redirect(f"/agents/{agent_id}", err="Invalid manifest JSON")
        ok, data, _ = await api.call(
            "PATCH", f"/v1/agents/{agent_id}", json={"manifest": manifest}
        )
        if not ok:
            return redirect(f"/agents/{agent_id}", err=_error_text(data, "Patch failed"))
        return redirect(f"/agents/{agent_id}", msg="Manifest updated")

    # ---- Tools & Skills ---------------------------------------------------
    @router.get("/tools", response_class=HTMLResponse)
    async def tools_page(request: Request) -> HTMLResponse:
        require_session(request)
        tools = await api.get("/v1/catalog/tools")
        skills = await api.get("/v1/catalog/skills")
        ws = await api.get("/v1/catalog/workspaces")
        return render(
            request,
            "tools.html",
            "tools",
            tools=tools.get("tools", []),
            skills=skills.get("skills", []),
            workspaces=ws.get("workspaces", []),
        )

    @router.post("/tools/catalog/{kind}")
    async def catalog_upsert_form(
        request: Request,
        kind: str,
        name: str = Form(default=""),
        id: str = Form(default=""),
        version: str = Form(default="1.0"),
        entrypoint: str = Form(default=""),
        package_source: str = Form(default="builtin"),
        permissions: str = Form(default=""),
        risk_level: str = Form(default="low"),
        runtime_dependencies: str = Form(default=""),
        exposed_tool_schemas: str = Form(default=""),
        source: str = Form(default=""),
        mount_path: str = Form(default="/workspace"),
        mount_mode: str = Form(default="ro"),
        allowed_agents: str = Form(default="*"),
        retention_policy: str = Form(default="ephemeral"),
    ) -> RedirectResponse:
        require_session(request)
        dest = "/tools"
        if kind == "tools":
            body = {
                "name": name,
                "version": version,
                "entrypoint": entrypoint,
                "package_source": package_source,
                "permissions": _split_csv(permissions),
                "risk_level": risk_level,
                "required_files": [],
            }
        elif kind == "skills":
            body = {
                "name": name,
                "version": version,
                "package_source": package_source,
                "runtime_dependencies": _split_csv(runtime_dependencies),
                "exposed_tool_schemas": _split_csv(exposed_tool_schemas),
            }
        elif kind == "workspaces":
            body = {
                "id": id,
                "source": source,
                "mount_path": mount_path,
                "mount_mode": mount_mode,
                "allowed_agents": _split_csv(allowed_agents) or ["*"],
                "retention_policy": retention_policy,
            }
        elif kind == "memory-namespaces":
            dest = "/memory"
            body = {
                "name": name,
                "retention_policy": retention_policy or "agent-private",
                "quota": {
                    "max_records": 1000,
                    "max_record_bytes": 65536,
                    "default_ttl_seconds": None,
                },
            }
            kind = "memory_namespaces"
        else:
            return redirect("/tools", err="Unknown catalog kind")
        ok, data, _ = await api.call("POST", f"/v1/catalog/{kind}", json=body)
        if not ok:
            return redirect(dest, err=_error_text(data, "Catalog save failed"))
        return redirect(dest, msg="Catalog entry saved")

    @router.post("/tools/catalog/{kind}/{entry_id}/delete")
    async def catalog_delete_form(
        request: Request, kind: str, entry_id: str
    ) -> RedirectResponse:
        require_session(request)
        api_kind = "memory_namespaces" if kind == "memory-namespaces" else kind
        dest = "/memory" if api_kind == "memory_namespaces" else "/tools"
        if api_kind == "llm_providers":
            dest = "/inference"
        ok, data, _ = await api.call("DELETE", f"/v1/catalog/{api_kind}/{entry_id}")
        if not ok:
            return redirect(dest, err=_error_text(data, "Delete failed"))
        return redirect(dest, msg="Catalog entry deleted")

    # ---- Inference --------------------------------------------------------
    @router.get("/inference", response_class=HTMLResponse)
    async def inference_page(request: Request) -> HTMLResponse:
        require_session(request)
        providers = await api.get("/v1/catalog/llm-providers")
        quotas = await api.get("/v1/quotas")
        token_quotas = [
            q for q in quotas.get("quotas", []) if "llm_tokens" in str(q.get("key", ""))
        ]
        settings_resp = await api.get("/v1/settings")
        inference_settings = settings_resp.get("settings", {}).get("inference", [])
        return render(
            request,
            "inference.html",
            "inference",
            providers=providers.get("llm_providers", []),
            token_quotas=token_quotas,
            settings={
                "default_provider": next(
                    (s["value"] for s in inference_settings if s["key"] == "llm_default_provider"),
                    config.llm_default_provider,
                ),
                "request_timeout_seconds": next(
                    (
                        s["value"]
                        for s in inference_settings
                        if s["key"] == "llm_request_timeout_seconds"
                    ),
                    config.llm_request_timeout_seconds,
                ),
                "tokens_daily_limit": next(
                    (
                        s["value"]
                        for s in inference_settings
                        if s["key"] == "llm_tokens_daily_limit"
                    ),
                    config.llm_tokens_daily_limit,
                ),
                "providers_path": str(config.llm_providers_path),
            },
            inference_settings=inference_settings,
        )

    @router.post("/inference/providers")
    async def inference_provider_save(
        request: Request,
        provider_id: str = Form(...),
        api_base_url: str = Form(default="stub://local"),
        supported_models: str = Form(default=""),
        credential_ref: str = Form(default="none"),
        hosted_tools_allowed: str = Form(default="0"),
        allowed_hosted_tools: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        body = {
            "provider_id": provider_id,
            "api_base_url": api_base_url,
            "supported_models": _split_csv(supported_models),
            "credential_ref": credential_ref,
            "quota_class": "dev",
            "hosted_tools_allowed": hosted_tools_allowed == "1",
            "allowed_hosted_tools": _split_csv(allowed_hosted_tools),
        }
        ok, data, _ = await api.call(
            "PUT", f"/v1/catalog/llm_providers/{provider_id}", json=body
        )
        if not ok:
            return redirect("/inference", err=_error_text(data, "Provider save failed"))
        return redirect("/inference", msg=f"Provider {provider_id} saved")

    @router.post("/settings/patch")
    async def settings_patch(request: Request) -> RedirectResponse:
        require_session(request)
        form = await request.form()
        return_to = str(form.get("return_to") or "/system")
        if not return_to.startswith("/"):
            return_to = "/system"
        updates: dict[str, Any] = {}
        for key, value in form.items():
            if key in {"return_to"} or not str(key).startswith("setting_"):
                continue
            setting_key = str(key)[len("setting_") :]
            raw = str(value)
            if raw in {"true", "false"}:
                updates[setting_key] = raw == "true"
            else:
                try:
                    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
                        updates[setting_key] = int(raw)
                    else:
                        updates[setting_key] = float(raw) if "." in raw else raw
                except ValueError:
                    updates[setting_key] = raw
        ok, data, _ = await api.call("PATCH", "/v1/settings", json={"settings": updates})
        if not ok:
            return redirect(return_to, err=_error_text(data, "Settings update failed"))
        msg = "Settings updated"
        if isinstance(data, dict) and data.get("restart_required"):
            msg += f" (restart required: {', '.join(data['restart_required'])})"
        return redirect(return_to, msg=msg)

    # ---- Memory -----------------------------------------------------------
    @router.get("/memory", response_class=HTMLResponse)
    async def memory_page(request: Request) -> HTMLResponse:
        require_session(request)
        ws = await api.get("/v1/catalog/workspaces")
        health = await api.get("/v1/health")
        server = health.get("server", {})
        settings_resp = await api.get("/v1/settings")
        memory_settings = settings_resp.get("settings", {}).get("memory", [])
        settings = {
            "encryption_enabled": next(
                (
                    s["value"]
                    for s in memory_settings
                    if s["key"] == "memory_encryption_enabled"
                ),
                config.memory_encryption_enabled,
            ),
            "sweep_interval_seconds": next(
                (
                    s["value"]
                    for s in memory_settings
                    if s["key"] == "memory_sweep_interval_seconds"
                ),
                config.memory_sweep_interval_seconds,
            ),
            "soft_delete_retention_hours": next(
                (
                    s["value"]
                    for s in memory_settings
                    if s["key"] == "memory_soft_delete_retention_hours"
                ),
                config.memory_soft_delete_retention_hours,
            ),
            "writes_daily_limit": next(
                (
                    s["value"]
                    for s in memory_settings
                    if s["key"] == "memory_writes_daily_limit"
                ),
                config.memory_writes_daily_limit,
            ),
            "sweeper_running": server.get("memory_sweeper_running"),
        }
        return render(
            request,
            "memory.html",
            "memory",
            namespaces=ws.get("memory_namespaces", []),
            settings=settings,
            memory_settings=memory_settings,
        )

    # ---- Users & Access ---------------------------------------------------
    @router.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request) -> HTMLResponse:
        require_session(request)
        users = await api.get("/v1/users")
        groups = await api.get("/v1/groups")
        return render(
            request,
            "users.html",
            "users",
            users=users.get("users", []),
            groups=groups.get("groups", []),
        )

    @router.get("/users/{user_id}", response_class=HTMLResponse)
    async def user_detail(request: Request, user_id: str) -> HTMLResponse:
        require_session(request)
        ok, data, _ = await api.call("GET", f"/v1/users/{user_id}")
        if not ok:
            return redirect("/users", err=_error_text(data, "User not found"))
        return render(
            request,
            "user_detail.html",
            "users",
            user=data.get("user", {}),
            user_json=json.dumps(data.get("user", {}), indent=2),
        )

    @router.post("/users/create")
    async def user_create(
        request: Request,
        user_id: str = Form(...),
        role: str = Form(default="researcher"),
        groups: str = Form(default=""),
        privileges: str = Form(default=""),
        allowed_agents: str = Form(default=""),
        aliases_json: str = Form(default=""),
        pin: str = Form(default=""),
        password: str = Form(default=""),
        return_to: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        payload: dict[str, Any] = {
            "id": user_id,
            "role": role,
            "groups": _split_csv(groups),
            "privileges": _split_csv(privileges),
            "allowed_agents": _split_csv(allowed_agents),
        }
        if aliases_json.strip():
            try:
                aliases = json.loads(aliases_json)
                if not isinstance(aliases, list):
                    dest = return_to or "/users"
                    return redirect(dest, err="aliases_json must be a JSON array")
                payload["aliases"] = aliases
            except json.JSONDecodeError:
                dest = return_to or "/users"
                return redirect(dest, err="Invalid aliases_json")
        if pin:
            payload["pin"] = pin
        if password:
            payload["password"] = password
        ok, data, _ = await api.call("POST", "/v1/users", json=payload)
        dest = return_to or "/users"
        if not ok:
            return redirect(dest, err=_error_text(data, "Create failed"))
        return redirect(dest, msg=f"User {user_id} saved")

    @router.post("/users/{user_id}/deactivate")
    async def user_deactivate(request: Request, user_id: str) -> RedirectResponse:
        require_session(request)
        ok, data, _ = await api.call("DELETE", f"/v1/users/{user_id}")
        if not ok:
            return redirect("/users", err=_error_text(data, "Deactivate failed"))
        return redirect("/users", msg=f"User {user_id} deactivated")

    @router.post("/users/groups/create")
    async def group_create(
        request: Request,
        group_id: str = Form(...),
        parent_group: str = Form(default=""),
        inherited_rules: str = Form(default="1"),
        members: str = Form(default=""),
        rule_ids: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        payload = {
            "id": group_id,
            "parent_group": parent_group or None,
            "inherited_rules": inherited_rules != "0",
            "members": _split_csv(members),
            "rule_ids": _split_csv(rule_ids),
        }
        ok, data, _ = await api.call("POST", "/v1/groups", json=payload)
        if not ok:
            return redirect("/users", err=_error_text(data, "Group save failed"))
        return redirect("/users", msg=f"Group {group_id} saved")

    @router.post("/users/groups/{group_id}/delete")
    async def group_delete(request: Request, group_id: str) -> RedirectResponse:
        require_session(request)
        ok, data, _ = await api.call("DELETE", f"/v1/groups/{group_id}")
        if not ok:
            return redirect("/users", err=_error_text(data, "Group delete failed"))
        return redirect("/users", msg=f"Group {group_id} deleted")

    # ---- Security ---------------------------------------------------------
    @router.get("/security", response_class=HTMLResponse)
    async def security_page(request: Request) -> HTMLResponse:
        require_session(request)
        rules = await api.get("/v1/rules")
        grants = await api.get("/v1/grants")
        elevations = await api.get("/v1/elevations")
        quotas = await api.get("/v1/quotas")
        users = await api.get("/v1/users")
        settings_resp = await api.get("/v1/settings")
        security_settings = settings_resp.get("settings", {}).get("security", [])
        behavioral_keys = {
            "behavioral_grant_denial_window_minutes",
            "behavioral_grant_denial_threshold",
            "behavioral_cross_agent_window_minutes",
            "behavioral_cross_agent_threshold",
            "behavioral_rate_baseline_minutes",
            "behavioral_rate_zscore_threshold",
            "behavioral_tool_zscore_threshold",
            "behavioral_counter_retention_hours",
        }
        behavioral_settings = [s for s in security_settings if s["key"] in behavioral_keys]
        behavioral = {
            "grant_denial_window_minutes": config.behavioral_grant_denial_window_minutes,
            "grant_denial_threshold": config.behavioral_grant_denial_threshold,
            "cross_agent_window_minutes": config.behavioral_cross_agent_window_minutes,
            "cross_agent_threshold": config.behavioral_cross_agent_threshold,
            "rate_baseline_minutes": config.behavioral_rate_baseline_minutes,
            "rate_zscore_threshold": config.behavioral_rate_zscore_threshold,
            "tool_zscore_threshold": config.behavioral_tool_zscore_threshold,
            "counter_retention_hours": config.behavioral_counter_retention_hours,
        }
        for row in behavioral_settings:
            short = row["key"].removeprefix("behavioral_")
            if short in behavioral:
                behavioral[short] = row["value"]
        rules_list = rules.get("rules", [])
        return render(
            request,
            "security.html",
            "security",
            rules=rules_list,
            rules_json=json.dumps(rules_list, indent=2),
            grants=grants.get("grants", []),
            elevations=elevations.get("elevations", []),
            quotas=quotas.get("quotas", []),
            users=users.get("users", []),
            behavioral=behavioral,
            behavioral_settings=behavioral_settings,
        )

    @router.post("/security/rules/create")
    async def rule_create(request: Request, rule_json: str = Form(...)) -> RedirectResponse:
        require_session(request)
        try:
            body = json.loads(rule_json)
        except json.JSONDecodeError as exc:
            return redirect("/security", err=f"Invalid JSON: {exc}")
        ok, data, _ = await api.call("POST", "/v1/rules", json=body)
        if not ok:
            return redirect("/security", err=_error_text(data, "Rule rejected"))
        return redirect("/security", msg=f"Rule {body.get('id', '')} saved")

    @router.post("/security/rules/{rule_id}/update")
    async def rule_update(
        request: Request, rule_id: str, rule_json: str = Form(...)
    ) -> RedirectResponse:
        require_session(request)
        try:
            body = json.loads(rule_json)
        except json.JSONDecodeError as exc:
            return redirect("/security", err=f"Invalid JSON: {exc}")
        ok, data, _ = await api.call("PUT", f"/v1/rules/{rule_id}", json=body)
        if not ok:
            return redirect("/security", err=_error_text(data, "Rule rejected"))
        return redirect("/security", msg=f"Rule {rule_id} updated")

    @router.post("/security/rules/{rule_id}/delete")
    async def rule_delete(request: Request, rule_id: str) -> RedirectResponse:
        require_session(request)
        ok, data, _ = await api.call("DELETE", f"/v1/rules/{rule_id}")
        if not ok:
            return redirect("/security", err=_error_text(data, "Delete failed"))
        return redirect("/security", msg=f"Rule {rule_id} deleted")

    @router.post("/security/simulate", response_class=HTMLResponse)
    async def rule_simulate(
        request: Request,
        agent_id: str = Form(...),
        engine: str = Form(default="engine3"),
        msg_type: str = Form(...),
        triggered_by: str = Form(default="agent_initiated"),
        scope: str = Form(default="local"),
        context_json: str = Form(default="{}"),
        payload_json: str = Form(default="{}"),
    ) -> HTMLResponse:
        require_session(request)
        try:
            context = json.loads(context_json or "{}")
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError as exc:
            return templates.TemplateResponse(
                request,
                "partials/simulate_result.html",
                {"request": request, "error": f"Invalid JSON: {exc}", "result": None},
            )
        body = {
            "message": {
                "source": {"agent_id": agent_id, "engine": engine},
                "type": msg_type,
                "tags": {"triggered_by": triggered_by, "scope": scope},
                "payload": payload,
            },
            "context": context,
        }
        ok, data, _ = await api.call("POST", "/v1/rules/simulate", json=body)
        return templates.TemplateResponse(
            request,
            "partials/simulate_result.html",
            {
                "request": request,
                "error": None if ok else _error_text(data, "Simulation failed"),
                "result": data if ok else None,
            },
        )

    @router.post("/security/grants/create")
    async def grant_create(
        request: Request,
        subject_agent: str = Form(...),
        target_agent: str = Form(...),
        namespace: str = Form(...),
        permissions: list[str] = Form(default=[]),
        expires_at: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        payload: dict[str, Any] = {
            "subject_agent": subject_agent,
            "target_agent": target_agent,
            "namespace": namespace,
            "permissions": permissions,
            "expires_at": expires_at or None,
        }
        ok, data, _ = await api.call("POST", "/v1/grants", json=payload)
        if not ok:
            return redirect("/security", err=_error_text(data, "Grant failed"))
        return redirect("/security", msg="Grant created")

    @router.post("/security/grants/{grant_id}/revoke")
    async def grant_revoke(request: Request, grant_id: str) -> RedirectResponse:
        require_session(request)
        ok, data, _ = await api.call("DELETE", f"/v1/grants/{grant_id}")
        if not ok:
            return redirect("/security", err=_error_text(data, "Revoke failed"))
        return redirect("/security", msg="Grant revoked")

    @router.post("/security/quotas/patch")
    async def quota_patch(
        request: Request,
        key: str = Form(...),
        limit: int = Form(...),
        used: int = Form(default=0),
        window_type: str = Form(default="daily"),
        return_to: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        dest = return_to if return_to.startswith("/") else "/security"
        ok, data, _ = await api.call(
            "PATCH",
            f"/v1/quotas/{key}",
            json={"limit": limit, "used": used, "window_type": window_type},
        )
        if not ok:
            return redirect(dest, err=_error_text(data, "Quota update failed"))
        return redirect(dest, msg=f"Quota {key} updated")

    @router.post("/security/elevations/{elevation_id}/{action}")
    async def elevation_decision(
        request: Request,
        elevation_id: str,
        action: str,
        approver_user_id: str = Form(...),
        pin: str = Form(default=""),
        password: str = Form(default=""),
        grant_subject_agent: str = Form(default=""),
        grant_target_agent: str = Form(default=""),
        grant_namespace: str = Form(default=""),
        grant_permissions: str = Form(default=""),
        grant_expires_at: str = Form(default=""),
    ) -> RedirectResponse:
        require_session(request)
        if action not in {"approve", "deny"}:
            return redirect("/security", err="Unknown elevation action")
        payload: dict[str, Any] = {"approver_user_id": approver_user_id}
        if pin:
            payload["pin"] = pin
        if password:
            payload["password"] = password
        if action == "approve" and (
            grant_subject_agent or grant_target_agent or grant_namespace
        ):
            payload["create_grant"] = {
                "subject_agent": grant_subject_agent,
                "target_agent": grant_target_agent,
                "namespace": grant_namespace,
                "permissions": _split_csv(grant_permissions) or ["read"],
                "expires_at": grant_expires_at or None,
            }
        ok, data, _ = await api.call(
            "POST", f"/v1/elevations/{elevation_id}/{action}", json=payload
        )
        if not ok:
            return redirect("/security", err=_error_text(data, "Elevation action failed"))
        return redirect("/security", msg=f"Elevation {action}d")

    # ---- Audit ------------------------------------------------------------
    @router.get("/audit", response_class=HTMLResponse)
    async def audit_page(request: Request) -> HTMLResponse:
        require_session(request)
        qp = request.query_params
        filters = {
            "correlation_id": qp.get("correlation_id", ""),
            "origin_correlation_id": qp.get("origin_correlation_id", ""),
            "agent_id": qp.get("agent_id", ""),
            "user_id": qp.get("user_id", ""),
            "event_type": qp.get("event_type", ""),
            "rule_id": qp.get("rule_id", ""),
            "grant_id": qp.get("grant_id", ""),
            "elevation_id": qp.get("elevation_id", ""),
            "from": qp.get("from", ""),
            "to": qp.get("to", ""),
            "limit": qp.get("limit", "100"),
        }
        params = {**filters}
        logs = await api.get("/v1/audit/logs", params=params)
        return render(
            request,
            "audit.html",
            "audit",
            logs=logs.get("logs", []),
            filters=filters,
        )

    # ---- System -----------------------------------------------------------
    @router.get("/system", response_class=HTMLResponse)
    async def system_page(request: Request) -> HTMLResponse:
        require_session(request)
        health = await api.get("/v1/health")
        ok, metrics_data, _ = await api.call("GET", "/v1/metrics")
        metrics_text = ""
        if isinstance(metrics_data, dict):
            metrics_text = metrics_data.get("raw", "")
        settings_resp = await api.get("/v1/settings")
        return render(
            request,
            "system.html",
            "system",
            health=health,
            metrics_text=metrics_text,
            config_rows=_config_view(config),
            settings_groups=settings_resp.get("settings", {}),
        )

    app.include_router(router)

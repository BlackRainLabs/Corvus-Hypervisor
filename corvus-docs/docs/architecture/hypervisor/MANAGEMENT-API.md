**Document:** hypervisor/MANAGEMENT-API.md
**Status:** Implemented — Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-02
**Related Documents:** OVERVIEW.md, hypervisor/RBAC-POLICY.md, hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md, memory/ARCHITECTURE.md, ../../planning/OPERATIONS.md, CHANGES.md
**Must Update on Change:** CHANGES.md
**AI Instruction:** When revising this document, review Core Principles & Invariants in OVERVIEW.md, update CHANGES.md, and ensure consistency with related documents. Do not contradict core fundamentals.
**API Caution:** Any changes must consider impact on the Management API surface. Maintain backward compatibility where possible and document breaking changes.

# Management API

## Purpose

The Management API provides a clean, external interface for configuring and monitoring Corvus. It is the backing surface for the Operator Console, CLI, and automation tools without tight coupling to internal implementation.

## Design Principles

- RESTful JSON API (Phase 2 default)
- Versioned endpoints (`/v1/`)
- Strong input validation and audit on all mutations
- Role-based access to the API itself (admin vs operator)
- Declarative configuration where possible
- Backward compatibility priority
- **Phase 9:** mutable control-plane state is writable via API/GUI; catalogs and runtime settings are SQLite-backed (env/YAML = bootstrap + break-glass)

## Authentication

- API keys or OAuth2 with role scoping (admin, operator, viewer)
- All API calls are audited

## Key Resource Endpoints

### Capability Catalogs

- `GET /v1/catalog/tools` — List server-owned tool catalog entries
- `GET /v1/catalog/skills` — List server-owned skill catalog entries
- `GET /v1/catalog/llm-providers` — List approved LLM providers, supported models, `api_base_url`, and hosted-tool flags (`hosted_tools_allowed`, `allowed_hosted_tools`; no credential secrets)
- `GET /v1/catalog/workspaces` — List approved workspace mounts and memory namespace templates
- `POST` / `PUT` / `DELETE` under `/v1/catalog/{tools,skills,workspaces,memory-namespaces,llm_providers}` — catalog CRUD (SQLite-backed; seeded from `DEFAULT_CATALOG` / YAML providers on first boot)
- LLM provider writes reload `LlmProviderRegistry` in-process (no restart); `credential_ref` / `api_base_url` are never returned on GET

Agent manifests select catalog IDs. The Corvus Server resolves those selections before persistence and VM launch; VM-provided capability strings are never authoritative.

### Users & Profiles

- `GET /v1/users` — List users
- `POST /v1/users` — Create or upsert user profile
- `GET /v1/users/{id}` — Get profile
- `PATCH /v1/users/{id}` — Update aliases, roles, contacts, groups, active flag
- `DELETE /v1/users/{id}` — Deactivate user (`active: false`)

**POST /v1/users request:**

```yaml
user:
  id: string                         # optional; server-generated if omitted
  role: admin | operator | researcher | viewer
  groups: [string]
  aliases:
    - platform: string
      value: string
      verified: boolean
      auth_method: pin | password | phone_number | platform_user_id | alias
      last_verified_at: iso8601 | null
      display_name: string | null
  pin: string | null                  # CLI/API setup only; stored as hash
  password: string | null             # CLI/API setup only; stored as hash
  contact_list:
    - name: string
      platform: string
      alias: string
  allowed_agents: [string]           # "*" for all
```

### Groups

- `GET /v1/groups` — List groups
- `POST /v1/groups` — Create group
- `PATCH /v1/groups/{id}` — Update members and assigned rules
- `DELETE /v1/groups/{id}` — Delete group
- `POST /v1/groups/{id}/members` — Add user to group

**POST /v1/groups request:**

```yaml
group:
  id: string
  parent_group: string | null        # max depth 3
  inherited_rules: boolean
  rule_ids: [string]
  members: [string]
```

### Agents

- `GET /v1/agents` — List agents and status
- `POST /v1/agents` — Create agent with manifest
- `PATCH /v1/agents/{id}` — Update manifest / runtime config; re-hash; reject unsafe mid-flight engine/rootfs/workspace/skills changes while VMs running
- `GET /v1/agents/{id}/manifest` — Get launch manifest
- `GET /v1/agents/{id}/vms` — List VM lifecycle records for an agent
- `POST /v1/agents/{id}/launch` — Launch an agent microVM from its resolved manifest
- `POST /v1/agents/{id}/stop` — Stop the active microVM for an agent

**POST /v1/agents request (manifest schema):**

```yaml
agent:
  id: string
  manifest:
    manifest_version: "1.0"
    engines:
      engine1:
        tools: [string]              # tool names baked into rootfs
      engine2:
        platforms: [string]          # e.g. whatsapp, api
      engine3:
        allowed_providers: [string]
        allowed_models: [string]
        tool_execution_mode: local | hybrid   # default local
        provider_tools: [string]              # hybrid only; e.g. openai:web_search
      engine4:
        namespaces: [string]         # default includes private; shared namespace is shared-knowledge
    launch_grants:                   # see memory/ARCHITECTURE.md
      - target_agent: string
        namespace: string
        permissions: [read | write | delete]
        expires_at: iso8601 | null
    skills: [string]                  # server-owned skill catalog IDs
    workspaces:
      - workspace_id: string          # server-owned workspace catalog ID
        mount_path: string
        mode: ro | rw
    rootfs_image: string
    resource_limits:
      memory_mb: integer
      vcpu_count: integer
```

Manifest hash (SHA-256 of canonical JSON) is attested at Corvus Node handshake. The server also generates a per-VM launch package containing the canonical manifest and guest environment values (`CORVUS_AGENT_ID`, `CORVUS_VM_ID`, `CORVUS_MANIFEST_HASH`, VSOCK settings, and registered engines).

**VM lifecycle response fields:**

```yaml
vm:
  vm_instance_id: string
  agent_id: string
  guest_cid: integer
  status: launching | booting | handshaking | running | degraded | failed | stopping | stopped
  manifest_hash: string
  pid: integer | null
  pid_alive: boolean
  launch_package_dir: string
  stdout_log: string
  stderr_log: string
  last_error: string | null
  graceful_stop: boolean | null
```

### Policy & Rules

- `GET /v1/rules` — List RBAC rules
- `POST /v1/rules` — Add rule
- `PUT /v1/rules/{id}` — Update rule
- `DELETE /v1/rules/{id}` — Remove rule
- `POST /v1/rules/simulate` — Dry-run (see RBAC-POLICY.md Section 14)

**POST /v1/rules request:**

```yaml
rule:
  id: string
  priority: integer
  subject:
    role: [string] | null
    agent_id: string | null
    user_id: string | null
  object:
    agent_id: string | null
    engine: [string] | null
    target_agent: string | null
  action:
    type: [string] | string
  condition: object
  effect: allow | deny | elevate
  else: elevate | null
```

**POST /v1/rules/simulate** — Request/response schemas defined in [RBAC-POLICY.md](RBAC-POLICY.md) Section 14.

Rule create/update requests are schema-validated before activation. Unsupported fields are rejected rather than silently ignored.

### Memory Grants

- `GET /v1/grants` — List grants (filter by agent, namespace)
- `POST /v1/grants` — Create grant (admin)
- `DELETE /v1/grants/{id}` — Revoke grant

**POST /v1/grants request:**

```yaml
grant:
  subject_agent: string
  target_agent: string
  namespace: string
  permissions: [read | write | delete]
  expires_at: iso8601 | null
  permanent: boolean                 # admin only; default false
  created_by: string
```

Grant schema matches [memory/ARCHITECTURE.md](../memory/ARCHITECTURE.md) Section 4.

### Memory Namespaces

- `GET /v1/agents/{id}/namespaces` — List namespaces and quotas
- `PATCH /v1/agents/{id}/namespaces/{ns}` — Update quota limits

**Namespace quota patch:**

```yaml
quota:
  max_records: integer
  max_record_bytes: integer
  default_ttl_seconds: integer | null
```

Namespace quota endpoints are implemented as control-plane configuration before Phase 4 Memory Service. `GET` lists namespaces assigned in the agent's resolved manifest and overlays any per-agent quota override onto the server-owned catalog template. `PATCH` validates the agent, namespace catalog template, and namespace assignment before storing quota config; Memory Service enforcement starts in Phase 4.

**Namespace response:**

```yaml
namespace:
  agent_id: string
  namespace: private | shared-knowledge | custom
  retention_policy: string
  quota:
    max_records: integer
    max_record_bytes: integer
    default_ttl_seconds: integer | null
  source: catalog_default | agent_override
```

### Bus & Audit

- `GET /v1/bus/traffic` — Live or historical bus inspection (not yet implemented)
- `GET /v1/audit/logs` — Query audit trail

**GET /v1/audit/logs query params:** `correlation_id`, `origin_correlation_id`, `agent_id`, `from` (alias of `from_`), `to`, `limit`

RBAC audit filters also support `user_id`, `event_type`, `rule_id`, `grant_id`, and `elevation_id`.

### Runtime Settings

- `GET /v1/settings` — Grouped runtime settings (secrets redacted)
- `PATCH /v1/settings` — Update settings; secrets are write-only replace; non-restart knobs apply in-process
- Bind host/port/transport (`mgmt_host`, `mgmt_port`, `use_tcp`) are editable but **restart_required** (operator restarts `corvus-server`; UI does not auto-kill)
- Precedence: empty DB ← seed from `load_config()`; non-empty DB is source of truth; **env wins if explicitly set** (break-glass)

### Health & Metrics

- `GET /v1/health` — Server, session, VM registry, and VM lifecycle health summary
- `GET /v1/metrics` — Prometheus text exposition (requires API key)

Health responses include database connectivity, active session count, sweeper liveness, pending replay queue depth, behavioral counter freshness, VM totals by active/failed state, PID liveness, last errors, launch logs, and per-VM package paths for GUI inspection.

### Elevation Queue

- `GET /v1/elevations` — List elevations (filter by `status`, `agent_id`)
- `POST /v1/elevations/{id}/approve` — Approve action (rejects expired/non-pending with HTTP 409)
- `POST /v1/elevations/{id}/deny` — Deny action

**Approve response includes optional grant creation and replay summary:**

```yaml
id: string
status: approved
grant_id: string
pending_replay_queued: boolean        # true when agent was offline at approval time
replay:
  replayed: boolean
  replay_delivered: boolean
  pending_replay_queued: boolean
  success: boolean
  grant_id: string
```

On approval, the server replays the stored memory operation with the new grant and delivers `memory:*_response` plus `memory:grant_created` to connected agents. When the agent is offline, undelivered messages are persisted in the `pending_replay` SQLite queue and flushed automatically on the next handshake ack after reconnect. Pending elevations expire after 1 hour (configurable via `CORVUS_ELEVATION_TTL_HOURS`); expired elevations cannot be approved.

Elevation creation emits an `elevation_pending` audit event. Optional webhook dispatch via `CORVUS_ELEVATION_WEBHOOK_URL`.

### Quotas & Limits

- `GET /v1/quotas` — List quota counters (filter by user, agent, group)
- `PATCH /v1/quotas/{key}` — Update limit or reset counter

**Quota counter response:**

```yaml
quota:
  key: string
  limit: integer
  used: integer
  window_type: daily | hourly | rpm
  reset_at: iso8601
```

## Error Responses

Standard HTTP status codes with JSON body:

```yaml
error:
  code: string                       # e.g. VALIDATION_ERROR, NOT_FOUND, FORBIDDEN
  message: string
  details: object
```

## OpenAPI

- Interactive docs: `GET /docs` and `GET /openapi.json` when the Management API server is running (FastAPI default).
- Offline export: `make openapi` or `bash tools/export-openapi.sh openapi.json`.

## Operator Console (GUI)

- A server-rendered operator console is mounted on the same app at `/ui` (Phase 8+; see [OPERATIONS.md](../../planning/OPERATIONS.md)).
- It is a presentation layer only: every console action calls these same `/v1` endpoints in-process (httpx `ASGITransport` with the server-held API key), so validation and audit are identical to direct API use.
- Phase 9 makes catalogs, settings, providers, and day-2 agent/user/group surfaces editable; health tiles, Prometheus dump, audit bodies, and resolved manifest JSON remain informational. Secrets are write-only after set.
- Sign-in uses the Management API key and sets a signed HttpOnly session cookie. Configurable via `CORVUS_UI_ENABLED`, `CORVUS_UI_SESSION_SECRET`, `CORVUS_UI_PATH_PREFIX`. Assets (HTMX, Alpine.js) are vendored — no external network required.

## Rate limiting

- Default: **100** requests per minute per API key (`CORVUS_API_RATE_LIMIT_PER_MINUTE`).
- Set to `0` to disable.
- Exceeded requests receive **429** with `Retry-After`.
- Operator console in-process calls send `X-Corvus-Internal: ui` and are exempt so HTMX polling does not starve the API key budget.

## Metrics

- `GET /v1/metrics` — Prometheus text format (requires `X-API-Key`).
- Gauges mirror `/v1/health` server and VM registry fields (sessions, sweeper liveness, pending replay depth, VM counts).
- Operator guide: [OPERATIONS.md](../planning/OPERATIONS.md).

## Future Considerations

- Webhook support for broader audit events (elevation webhook implemented; optional HMAC via `CORVUS_ELEVATION_WEBHOOK_SECRET`)

**Black Rain Labs - Research & Development Division**

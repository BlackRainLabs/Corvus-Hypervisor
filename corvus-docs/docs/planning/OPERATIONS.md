**Document:** OPERATIONS.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** ../architecture/hypervisor/MANAGEMENT-API.md, COMPONENT-STATUS.md, PHASES.md, ROADMAP.md, ../../../CHANGES.md
**Must Update on Change:** ../../../CHANGES.md

# Corvus Operations Guide

Operator reference for running, observing, and regression-testing Corvus Hypervisor (Phases 6–9.6).

## Daily development (native TCP)

```bash
make install
make dev-up          # corvus-server + corvus-node + dummy LLM (:8765)
make dev-status
# Console chat: http://127.0.0.1:8080/ui/chat  (admin-user / 0000)
corvus-runtime --once --all-engines
make dev-down
```

Environment template: `tools/corvus.env.example` (copied to `/tmp/corvus-dev/env` on first `dev-stack.sh up`).

## Docker deployment (server only)

Corvus Node and agent runtime still run on the host in TCP mode; the container hosts the authoritative server + Management API.

```bash
docker compose -f deploy/docker-compose.yml up --build -d
export CORVUS_USE_TCP=1 CORVUS_TCP_HOST=127.0.0.1 CORVUS_TCP_PORT=4040
corvus-node
```

See `deploy/README.md` for port and volume details.

## Management API

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/health` | JSON health: sweeper liveness, pending replay depth, VM registry |
| `GET /v1/metrics` | Prometheus text exposition (same API key as other routes) |
| `GET /docs` | Interactive OpenAPI (running server) |
| `POST /v1/rules/simulate` | Dry-run policy decisions |

Auth header: `X-API-Key: <CORVUS_API_KEY>` (default `dev-api-key`).

Offline OpenAPI export: `make openapi`.

## Operator Console (GUI)

A server-rendered operator console ships with the server and is served by the same
Management API process at `http://<mgmt_host>:<mgmt_port>/ui` (default
`http://127.0.0.1:8080/ui`).

- Sign in at `/ui/login` with a Corvus user id that has the `admin` or `operator`
  role, plus that user's PIN or password. A signed HttpOnly session cookie is set;
  the Management API key is used only in-process and is never stored in the browser.
- Left sidebar categories: **Summary** (live health), **Chat** (operator LLM
  playground via the server gateway), **Agents** (create / launch / stop /
  manifest / namespace quotas), **Tools & Skills** (catalogs), **Inference**
  (LLM providers, token quotas), **Memory** (namespaces, sweeper, encryption),
  **Users & Access**, **Security** (RBAC rules + dry-run simulator, grants,
  elevations, quotas, behavioral thresholds), **Audit** (filterable log browser),
  **System** (health, metrics, server settings).
- Dev login (seeded): username `admin-user`, PIN `0000`. Chat defaults to
  `test-agent-01` + in-process `stub` (echoes your text). `dummy-http` /
  `dummy-v1` needs that pair on the agent manifest; `make dev-up` starts the
  dummy API on `http://127.0.0.1:8765/v1`.
- The console is a presentation layer: every action calls the same `/v1` endpoints
  in-process, so all validation and audit behavior is identical to direct API use.

### Phase 9 product rule — GUI field taxonomy

Mutable control-plane state is **editable** in the GUI. Read-only is reserved for
informational surfaces. Section headings use quiet “Editable” / “Live view” hints;
the sidebar no longer prints taxonomy tokens. Every field/section is tagged as one of:

| Tag | Meaning |
|-----|---------|
| `editable` | Operator may create/update/delete via console → `/v1` |
| `informational` | Live/computed view only (health tiles, metrics dump, audit bodies, resolved manifest JSON, role glossary) |
| `secret` | Write-only replace after set; never returned in clear (API key, master key, webhook secret, session secret, provider credentials) |
| `restart_required` | Editable in GUI but bind host/port/transport changes apply only after operator restarts `corvus-server` (UI does not auto-kill the process) |

**Persistence:** catalogs and runtime settings are SQLite-backed (same DB as agents/rules).
Seed on first boot from `DEFAULT_CATALOG`, `config/llm_providers.yaml`, and
`load_config()` defaults. Environment variables remain **bootstrap / break-glass**
(if an env var is explicitly set it wins; otherwise DB is source of truth)—not the
primary day-2 ops path.

| Sidebar section | Taxonomy |
|-----------------|----------|
| Overview health tiles / pending elevations list | informational (elevations: link to Security) |
| Chat agent/provider/model + send | editable; transcript is local browser state (informational) |
| Agents list, create, detail editor, launch/stop, namespace quotas | editable; resolved manifest JSON dump informational |
| Tools / Skills / Workspaces catalogs | editable; exec-policy help informational |
| Inference providers | editable; token quotas editable; secrets write-only |
| Inference runtime settings | editable; bind-related knobs may be restart_required on System |
| Memory namespaces catalog | editable; sweeper/encryption settings editable; liveness informational |
| Users create/edit/deactivate, groups | editable; roles glossary informational |
| Security rules/grants/elevations/quotas | editable; behavioral thresholds editable |
| Audit filters | editable filters only; log bodies informational |
| System health / Prometheus dump | informational |
| System configuration (bind, rate limit, UI knobs, webhooks) | editable; bind host/port/transport restart_required; secrets secret |

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORVUS_UI_ENABLED` | `1` | Set `0` to disable the console (routes return 404); also seedable via `/v1/settings` |
| `CORVUS_UI_SESSION_SECRET` | random per process | HMAC secret for session cookies; set a stable value across restarts/replicas (secret) |
| `CORVUS_UI_PATH_PREFIX` | `/ui` | Base path the console mounts under |
| `CORVUS_API_RATE_LIMIT_PER_MINUTE` | `100` | Management API limit per API key (`0` disables); UI in-process calls are exempt |
| `CORVUS_MGMT_HOST` / `CORVUS_MGMT_PORT` | `127.0.0.1` / `8080` | Management bind; editable in GUI with restart_required |

The console is bundled with vendored HTMX and Alpine.js assets (no CDN / external
network required).

## Observability

### Structured logs

```bash
CORVUS_LOG_JSON=1 CORVUS_LOG_LEVEL=INFO corvus-server
```

### Prometheus metrics

Scrape `GET /v1/metrics` with the API key (e.g. bearer-style custom config or `X-API-Key` in Prometheus `authorization` headers).

Exported gauges:

| Metric | Meaning |
|--------|---------|
| `corvus_server_degraded` | `1` if any VM degraded/failed |
| `corvus_active_sessions` | Connected agent transports |
| `corvus_pending_replay_depth` | Undelivered elevation replay queue |
| `corvus_memory_sweeper_running` | Memory TTL sweeper task alive |
| `corvus_elevation_sweeper_running` | Elevation expiry sweeper alive |
| `corvus_vm_registry_*` | VM registry totals |

## Policy regression gate

RBAC rule changes should pass the YAML fixture suite before merge:

```bash
make fixtures
# or: corvus-policy-fixtures
```

Fixtures: `config/policy_fixtures/*.yaml`. CI runs this after pytest.

Add cases when introducing new default rules or behavioral gates.

## LLM provider configuration

Provider endpoints and API keys are **server-side only**. Agents select allowed provider ids and models in the launch manifest — never URLs or secrets.

Registry file (default `config/llm_providers.yaml`). Shipped seed providers are `openai`, `stub`, and `dummy-http`. The `local`/Ollama block below is an **illustration** of a custom OpenAI-compatible endpoint — it is not in the default file:

```yaml
providers:
  openai:
    api_base_url: https://api.openai.com/v1
    credential_ref: env:OPENAI_API_KEY
    supported_models: [gpt-4, gpt-4o]
  stub:
    api_base_url: stub://local
    credential_ref: none
    supported_models: [stub-v1]
  local:
    api_base_url: http://127.0.0.1:11434/v1
    credential_ref: file:/run/secrets/ollama_api_key
    supported_models: [llama3]
```

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORVUS_LLM_PROVIDERS_PATH` | `config/llm_providers.yaml` | Provider registry |
| `CORVUS_LLM_DEFAULT_PROVIDER` | `stub` | Fallback when request omits provider |
| `CORVUS_LLM_REQUEST_TIMEOUT_SECONDS` | `60` | Upstream HTTP timeout |
| `CORVUS_LLM_TOKENS_DAILY_LIMIT` | `100000` | Quota counter limit for token metering |

Credential refs: `env:VAR_NAME`, `file:/path/to/secret`, or `none` (no auth header). Keys are read at call time and never logged or returned via catalog/handshake APIs.

Public catalog: `GET /v1/catalog/llm-providers` returns `provider_id`, `api_base_url`,
`supported_models`, `hosted_tools_allowed`, and `allowed_hosted_tools` (no credential secrets).

### Tool execution modes

**Local (default):** LLM function tools are defined in `tools_schema`, validated against manifest `engines.engine1.tools`, and executed in the agent VM by Engine 1 after server RBAC. Provider-native tool types are stripped upstream.

**Hybrid (opt-in):** Set manifest `engines.engine3.tool_execution_mode: hybrid` and list `provider_tools` (e.g. `openai:web_search`). The provider registry must set `hosted_tools_allowed: true` and include the tool in `allowed_hosted_tools`. Hybrid LLM requests require **admin** role per default RBAC. Audit events: `provider_tool_invocation`, `provider_tool_execution_opaque`.

Runtime env for local tool loop: `CORVUS_LLM_LOCAL_TOOLS=echo,terminal,file_read` (set automatically by `corvus-runtime --all-engines` when configured). `file_read` reads UTF-8 files under `CORVUS_TOOL_WORKSPACE_ROOT` (default `/workspace`); path traversal is denied. Rebuild the guest rootfs after adding tools to the catalog for Firecracker smokes.

Runtime env for LLM streaming: `CORVUS_LLM_STREAM=1` (Engine 3 sends `stream: true`). Compatible with local tools and hybrid provider-hosted tools.

Turn timeouts (two separate env vars — do not rename/unify casually):

| Variable | Default | Scope |
|----------|---------|--------|
| `CORVUS_TURN_TIMEOUT_SECONDS` | **120** | Agent runtime: Agent Loop wait for terminal phase (`DONE`/`ABORTED`) and Engine 1 COLLECT backstop. On expiry the turn aborts and `--once` exits cleanly. |
| `CORVUS_TURN_TIMEOUT` | **300** | Corvus Server correlation / control-plane turn budget (seconds). Independent of the runtime knob above. |

On runtime expiry the turn is moved to terminal `ABORTED` so stalled turns cannot hang the process, which keeps concurrent multi-agent runs reliable.

### Skills library (Phase 10)

Agent Skills (`SKILL.md`) packages install **on the control plane only** via `POST /v1/catalog/skills/install` (or Operator Console → Tools & Skills → Install / Browse).

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORVUS_SKILL_SOURCE_ALLOWLIST` | empty | Comma-separated URL prefixes for remote installs; empty denies all remote. `file:` always allowed. For browse→GitHub install include `https://codeload.github.com/` and `https://api.github.com/`. |
| `CORVUS_SKILL_STORE_DIR` | `<db-dir>/skill-store` | Content-addressed approved packages |
| `CORVUS_SKILL_REGISTRY_URL` | empty | Base URL of a skills.sh-compatible registry API (browser disabled when empty) |
| `CORVUS_SKILL_REGISTRY_ALLOWLIST` | empty | Comma-separated URL prefixes the registry base must match; deny-by-default |

Browse endpoints: `GET /v1/skills/browse`, `GET /v1/skills/browse/{owner}/{repo}/{skill_id}`, `POST /v1/skills/browse/prepare-install`. Console: `/ui/tools/skills/browse`. Registry metadata is untrusted; prepare-install computes archive sha256 and uses the same pin+hash install path. Private/link-local resolved IPs are rejected for registry and source URLs.

Install requires `source`, `pin` (not `latest`), and `sha256`. Use `dry_run: true` to preview. `allow_scripts` defaults false. Guests never fetch skills; launch packages bake selected skills under `skills/`. Engine 1 tools: `skill_read`, `skill_run` (RBAC + manifest `skills` allowlist). See [PHASE-10-SKILLS.md](PHASE-10-SKILLS.md) and [SECURITY.md](../../../SECURITY.md).

Correlation depth: multi-hop tool turns increment chain depth; default `CORVUS_MAX_CHAIN_DEPTH` is **16**.

### Operator chat (console + API)

`POST /v1/agents/{agent_id}/chat` sends a chat-completion request through the
same `LlmGatewayService` Engine 3 uses (manifest allowlists, credentials, audit
`llm_completion` + `api_mutation`, token quotas). It is **text-only**: no local
or provider-hosted tools are executed. Console page: `/ui/chat`.

```bash
curl -sS -H "X-API-Key: dev-api-key" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}' \
  http://127.0.0.1:8080/v1/agents/test-agent-01/chat
```

Stub reply includes the user text (`Stub LLM response: hello`). Runtime turns
can pass custom user text with `CORVUS_CHAT_TEXT='…' make run-turn`.

### Local dummy LLM API (testing)

`make dev-up` starts the dummy server automatically. For a standalone instance:

```bash
corvus-dummy-llm --port 8765
```

It serves `POST /v1/chat/completions` (JSON or SSE when `stream: true`) and returns a fixed success payload (`Success: simulated LLM response for testing.`). Point the `dummy-http` provider in `config/llm_providers.yaml` at `http://127.0.0.1:8765/v1` (default). Pytest starts an ephemeral instance automatically in `tests/test_llm_dummy_api.py`, `tests/test_llm_streaming.py`, and `tests/test_management.py`.

## Elevation operations

1. Agent receives `SERVER_ELEVATION_REQUIRED` with `elevation_id`.
2. Operator lists pending: `GET /v1/elevations?status=pending`.
3. Approve: `POST /v1/elevations/{id}/approve` (admin credentials).
4. Offline agents: replay queues in `pending_replay`; delivered on next handshake ack.

Optional webhook: `CORVUS_ELEVATION_WEBHOOK_URL`. When `CORVUS_ELEVATION_WEBHOOK_SECRET` is set, requests include `X-Corvus-Signature: sha256=<hex>` over the canonical JSON body.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Node cannot connect | `make dev-status`; TCP port / firewall; `CORVUS_USE_TCP=1` on both sides |
| Memory ops denied | Correlation chain (`user_query` first); grants for cross-agent |
| Elevations not replaying | `GET /v1/health` → `pending_replay_depth`; agent reconnect |
| VM degraded | `GET /v1/health` → `vms`; launch logs under `CORVUS_VM_STATE_DIR` |
| Rule surprise after edit | `make fixtures`; `POST /v1/rules/simulate` |

## Test & CI commands

```bash
make test       # pytest (CORVUS_USE_TCP=1)
make lint       # ruff
make fixtures   # policy YAML regression
```

Firecracker smoke (optional, requires KVM): `bash tools/vm-smoke.sh`.

**Black Rain Labs - Research & Development Division**

**Document:** OPERATIONS.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-07-12
**Related Documents:** ../architecture/hypervisor/MANAGEMENT-API.md, COMPONENT-STATUS.md, PHASES.md, ../../../CHANGES.md
**Must Update on Change:** ../../../CHANGES.md

# Corvus Operations Guide

Operator reference for running, observing, and regression-testing Corvus Hypervisor (Phase 6).

## Daily development (native TCP)

```bash
make install
make dev-up          # corvus-server + corvus-node
make dev-status
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

- Sign in at `/ui/login` with the Management API key (`CORVUS_API_KEY`). A signed
  HttpOnly session cookie is set; the raw key is not stored in the browser afterward.
- Left sidebar categories: **Summary** (live health), **Agents** (create / launch /
  stop / manifest / namespace quotas), **Tools & Skills** (catalogs), **Inference**
  (LLM providers, token quotas), **Memory** (namespaces, sweeper, encryption),
  **Users & Access**, **Security** (RBAC rules + dry-run simulator, grants,
  elevations, quotas, behavioral thresholds), **Audit** (filterable log browser),
  **System** (health, metrics, redacted server config).
- The console is a presentation layer: every action calls the same `/v1` endpoints
  in-process, so all validation and audit behavior is identical to direct API use.
  Environment-only settings are shown read-only under their category.

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORVUS_UI_ENABLED` | `1` | Set `0` to disable the console (routes return 404) |
| `CORVUS_UI_SESSION_SECRET` | random per process | HMAC secret for session cookies; set a stable value across restarts/replicas |
| `CORVUS_UI_PATH_PREFIX` | `/ui` | Base path the console mounts under |
| `CORVUS_API_RATE_LIMIT_PER_MINUTE` | `100` | Management API limit per API key (`0` disables); UI in-process calls are exempt |

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

Registry file (default `config/llm_providers.yaml`):

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

Public catalog: `GET /v1/catalog/llm-providers` returns `provider_id`, `supported_models`, `hosted_tools_allowed`, and `allowed_hosted_tools` (no secrets).

### Tool execution modes

**Local (default):** LLM function tools are defined in `tools_schema`, validated against manifest `engines.engine1.tools`, and executed in the agent VM by Engine 1 after server RBAC. Provider-native tool types are stripped upstream.

**Hybrid (opt-in):** Set manifest `engines.engine3.tool_execution_mode: hybrid` and list `provider_tools` (e.g. `openai:web_search`). The provider registry must set `hosted_tools_allowed: true` and include the tool in `allowed_hosted_tools`. Hybrid LLM requests require **admin** role per default RBAC. Audit events: `provider_tool_invocation`, `provider_tool_execution_opaque`.

Runtime env for local tool loop: `CORVUS_LLM_LOCAL_TOOLS=echo,terminal,file_read` (set automatically by `corvus-runtime --all-engines` when configured). `file_read` reads UTF-8 files under `CORVUS_TOOL_WORKSPACE_ROOT` (default `/workspace`); path traversal is denied. Rebuild the guest rootfs after adding tools to the catalog for Firecracker smokes.

Runtime env for LLM streaming: `CORVUS_LLM_STREAM=1` (Engine 3 sends `stream: true`). Compatible with local tools and hybrid provider-hosted tools.

Turn timeout: `CORVUS_TURN_TIMEOUT_SECONDS` (default **120**) bounds a single agent turn. The Agent Loop waits this long for a terminal phase (`DONE`/`ABORTED`) and Engine 1's COLLECT loop uses the same deadline as a backstop. On expiry the turn is aborted (terminal `ABORTED` phase) and the `--once` runtime exits cleanly — no stalled turn can hang the process, which keeps concurrent multi-agent runs reliable.

Correlation depth: multi-hop tool turns increment chain depth; default `CORVUS_MAX_CHAIN_DEPTH` is **16**.

### Local dummy LLM API (testing)

For manual or integration testing of the OpenAI-compatible HTTP path, run the bundled dummy server:

```bash
corvus-dummy-llm --port 8765
```

It serves `POST /v1/chat/completions` (JSON or SSE when `stream: true`) and returns a fixed success payload (`Success: simulated LLM response for testing.`). Point the `dummy-http` provider in `config/llm_providers.yaml` at `http://127.0.0.1:8765/v1` (default). Pytest starts an ephemeral instance automatically in `tests/test_llm_dummy_api.py` and `tests/test_llm_streaming.py`.

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

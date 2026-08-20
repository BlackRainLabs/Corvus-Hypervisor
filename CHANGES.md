# Architecture Changes Log

**Last Updated:** 2026-08-17
**Organization:** Black Rain Labs
**Division:** Research & Development Division

## [2026-08-17] - Fix Operator Console chat Alpine init

**Documents Modified:**
- `src/corvus/management/templates/chat.html`
- `tests/test_ui.py`

**Key Changes:**
- Chat config is no longer JSON inside a double-quoted `x-data` attribute (that truncated the Alpine expression so Send never ran). Config now lives in a JSON script tag; Alpine.data wires the component.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-13] - Operator chat + runnable test LLM

**Documents Modified:**
- `src/corvus/management/chat.py` (new), `api.py`, `ui.py`, `ui_client.py`, `ui_copy.py`
- `src/corvus/management/templates/chat.html` (new), `summary.html`, `corvus.css`
- `src/corvus/runtime/engines/engine2.py`, `tools/dev-stack.sh`, `tools/corvus.env.example`
- `tests/test_management.py`, `tests/test_ui.py`
- README, OPERATIONS, MANAGEMENT-API, PHASES, ROADMAP, COMPONENT-STATUS

**Key Changes:**
- Operator Console **Chat** page talks to an agent's allowed LLM through `POST /v1/agents/{id}/chat` (gateway + audit + token quotas; text-only, no tool/memory bypass).
- Seeded `test-agent-01` / `stub` echoes the operator message; `make dev-up` also starts `corvus-dummy-llm` on `:8765` for `dummy-http`.
- Engine 2 honors `CORVUS_CHAT_TEXT` on `make run-turn`. Sign-in: `admin-user` / `0000`.
- Chat agent dropdown is server-rendered (Alpine `<template>` inside `<select>` left the list empty in the browser).

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-13] - Phase 9.5: Operator Console UX polish

**Documents Modified:**
- `src/corvus/management/ui.py`, `ui_client.py`, `ui_copy.py`, templates, `corvus.css`
- `tests/test_ui.py`
- OPERATIONS, MANAGEMENT-API, PHASES, ROADMAP, COMPONENT-STATUS

**Key Changes:**
- Console pages use operator-facing labels, page leads, confirmations, catalog dropdowns, and hash-tab highlighting; JSON editors remain the day-2 control surface.
- Sidebar no longer shows Phase 9 taxonomy badges; login copy and ops docs match username + PIN/password (admin/operator).
- Agent create now applies self `launch_grants` from namespace permissions when the JSON box is empty; Launch/Stop are status-aware.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Operator Console: restore Phase 9 edit surfaces

**Documents Modified:**
- Management templates (tools/skills/workspaces/memory/inference/users), `ui.py`, `ui_client.py`, `corvus.css`
- `src/corvus/llm/registry.py` (public provider payload includes `api_base_url`)
- MANAGEMENT-API, OPERATIONS

**Key Changes:**
- Live GUI was briefly bound to a pre–Phase 9 process on `:8080`; Phase 9 stack is the active server again.
- Catalog/provider/group rows now have inline Edit/Delete; taxonomy badges no longer misuse `read-only` for status counts.
- Roles glossary tagged `informational`; LLM public catalog exposes `api_base_url` while still redacting credentials.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Phase 9.4: Runtime settings + LLM provider registry

**Documents Modified:**
- `src/corvus/server/settings_store.py`, `db.py` (`server_settings`), `bootstrap.py`
- `src/corvus/management/api.py` (`GET`/`PATCH /v1/settings`), `ui.py`, System/Inference/Memory/Security templates
- `src/corvus/llm/registry.py`, `catalog.py` (`api_base_url` on providers)
- `tests/test_phase9_config.py`, `tests/test_ui.py`
- OPERATIONS, MANAGEMENT-API, ROADMAP, PHASES, COMPONENT-STATUS

**Key Changes:**
- SQLite `server_settings` seeded from `ServerConfig`; GUI/API edit with secret redaction and `restart_required` for bind knobs.
- Env break-glass wins when explicitly set; otherwise DB applies in-process to live services.
- LLM providers CRUD in SQLite with in-process registry reload; YAML seeds once and is not rewritten over GUI edits.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Phase 9.3: Catalog CRUD

**Documents Modified:**
- `src/corvus/server/catalog_store.py`, `db.py` (`catalog_entries`)
- `src/corvus/management/api.py` (catalog POST/PUT/DELETE), Tools/Memory UI
- `src/corvus/memory/service.py` (binds live catalog)
- `tests/test_phase9_config.py`

**Key Changes:**
- Tools/skills/workspaces/memory namespaces persist in SQLite; seed from `DEFAULT_CATALOG` when empty.
- Management API write paths refresh `AppContext` catalog; unknown ids still rejected at resolve/launch.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Phase 9.2: Agent/user/group Management API + UI

**Documents Modified:**
- `src/corvus/management/api.py` (`PATCH` agents/users, `DELETE` users, groups CRUD)
- `src/corvus/server/db.py` (groups table, user deactivate/patch)
- Agent detail / Users templates + UI handlers
- `tests/test_phase9_config.py`, MANAGEMENT-API

**Key Changes:**
- Agent manifest PATCH re-resolves/re-hashes; blocks unsafe mid-flight changes while VM running.
- User PATCH + deactivate; groups table with membership CRUD and Users page panel.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Phase 9.1: Operator Console gaps on existing APIs

**Documents Modified:**
- `src/corvus/management/ui.py`, templates (`agents`, `users`, `user_detail`, `security`, `audit`, `inference`)
- `src/corvus/management/api.py` (audit `from` query alias; user upsert preserves credential)
- `tests/test_ui.py`

**Key Changes:**
- Agent create form covers platforms, tool_execution_mode, provider_tools, workspaces, rootfs, launch_grants JSON.
- Elevation approve supports optional `create_grant`; deny has pin/password parity.
- User aliases on create; user detail edit via POST upsert; audit from/to filters; inference quota save stays on Inference.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Phase 9.0: GUI configurability UX contract

**Documents Modified:**
- `corvus-docs/docs/planning/OPERATIONS.md`, `ROADMAP.md`, `PHASES.md`, `COMPONENT-STATUS.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`

**Key Changes:**
- Defined Phase 9 field taxonomy (`editable` / `informational` / `secret` / `restart_required`) and SQLite-backed settings/catalog product rule.
- Retired “env-only shown read-only” as the Operator Console default; env remains bootstrap/break-glass.
- Seeded near-term roadmap 9.1–9.4; documented planned writable Management API surfaces (catalog CRUD, settings, agent/user/group PATCH).

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Public release v0.8.0

**Documents Modified:**
- `pyproject.toml`, `src/corvus/__init__.py`
- `README.md`, `SECURITY.md` (new), `CONTRIBUTING.md`

**Key Changes:**
- Package version set to **0.8.0** to mark Phases 1–8 complete (operator console, LLM gateway with streaming + hybrid tools, elevation, behavioral monitoring, Firecracker/TCP paths, Management API, memory service).
- Public-facing README and SECURITY.md prepared for GitHub publication.
- This cut is a research / early-access release: skill runtime beyond placeholders, multi-host scaling, and a broader tool surface remain post-0.8 work.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Tool surface: registry runner + file_read

**Documents Modified:**
- `src/corvus/tools/registry.py` (new), `file_read.py` (new), `runner.py`
- `src/corvus/server/catalog.py`, `manifest.py` (full-capability tools list)
- `src/corvus/runtime/tool_schemas.py`
- `tests/test_file_read_tool.py`
- `corvus-docs/docs/planning/OPERATIONS.md`, `ROADMAP.md`

**Key Changes:**
- Engine 1 tool execution uses an explicit `TOOL_REGISTRY` instead of a private `_BUILTIN_TOOLS` map.
- Added catalog `file_read` tool: UTF-8 reads under `CORVUS_TOOL_WORKSPACE_ROOT` with traversal denial and 64 KiB cap.
- Full-capability test manifest includes `file_read`.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Ops honesty: tool_pattern_deviation, API rate limits, elevation HMAC

**Documents Modified:**
- `src/corvus/policy/behavioral.py`, `server/router.py`, `server/config.py`
- `src/corvus/management/rate_limit.py` (new), `api.py`, `ui_client.py`
- `src/corvus/server/elevation_notify.py`, `bootstrap.py`
- `config/default_rules.yaml`, `config/policy_fixtures/core.yaml`
- `tests/test_behavioral_monitor.py`, `test_api_rate_limit.py`, `test_elevation_webhook.py`
- RBAC-POLICY, MANAGEMENT-API, OPERATIONS, ROADMAP

**Key Changes:**
- Live `tool_pattern_deviation` from approved `tool_call` rate z-score (`CORVUS_BEHAVIORAL_TOOL_ZSCORE_THRESHOLD`); default elevate rule + fixture.
- Management API sliding-window rate limit (default 100/min, `0` disables); UI ASGI calls exempt via `X-Corvus-Internal: ui`.
- Elevation webhook optional HMAC (`CORVUS_ELEVATION_WEBHOOK_SECRET` → `X-Corvus-Signature`).

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Hygiene: ruff CI-green + OpenAPI venv + ROADMAP seed

**Documents Modified:**
- Multiple `src/` / `tests/` lint fixes (unused imports, import order, line length, E402/E731)
- `tools/export-openapi.sh` (prefer `.venv/bin/python`)
- `corvus-docs/docs/planning/COMPONENT-STATUS.md` (Phase 7.2 gate wording)
- `corvus-docs/docs/planning/ROADMAP.md` (near-term hygiene → ops → tools sequence)

**Key Changes:**
- Cleared pre-existing ruff debt so `ruff check src tests` passes for CI.
- OpenAPI export script prefers the project virtualenv when `PYTHON` is unset.
- Seeded near-term ROADMAP with hygiene, behavioral tool deviation, API rate limits, and tool-surface expansion.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-08-02] - Phase 7.2+: Streaming + provider-hosted (hybrid) tools

**Documents Modified:**
- `src/corvus/llm/service.py` (remove stream+hybrid prepare gates)
- `src/corvus/llm/providers/stub.py` (stream parity for `provider_tool_entries`)
- `tests/test_llm_streaming.py`
- `.github/workflows/ci.yml`, `.github/workflows/firecracker-smoke.yml` (repo-root working directory)
- `corvus-docs/docs/planning/ROADMAP.md`, `PHASES.md`, `COMPONENT-STATUS.md`, `OPERATIONS.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`
- `corvus-docs/docs/architecture/agent-vm/AGENT-WORKFLOW.md`
- `corvus-docs/README.md`

**Key Changes:**
- LLM gateway streaming now coexists with hybrid provider-hosted tools. `prepare()` no longer emits `LLM_STREAM_TOOLS_UNSUPPORTED` for `stream` + hybrid/`provider_tools`.
- Stub stream path mirrors non-stream `complete()`: hosted tool entries yield a terminal completion with `provider_tools_used` before local `tools_schema` tool_calls.
- Existing `iter_stream` / `finalize_stream` audit path (`provider_tool_invocation`, opaque detection, `trust_boundary`) applies unchanged to streamed hybrid completions.
- CI workflows run from the repository root (removed stale nested `working-directory`).
- ROADMAP medium/long terms refreshed to forward-looking work; Phase 7.2+ marked done.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-12] - Phase 8: Operator Console (sidebar-driven GUI)

**Documents Modified:**
- `src/corvus/management/ui.py` (new), `src/corvus/management/ui_client.py` (new)
- `src/corvus/management/templates/*.html` (new), `src/corvus/management/static/{corvus.css,htmx.min.js,alpine.min.js}` (new, vendored)
- `src/corvus/management/api.py` (mount UI in `create_app`), `src/corvus/server/config.py` (`CORVUS_UI_*`)
- `pyproject.toml` (jinja2 + python-multipart deps; wheel force-include for templates/static)
- `tests/test_ui.py` (new)
- `corvus-docs/docs/planning/PHASES.md`, `ROADMAP.md`, `COMPONENT-STATUS.md`, `OPERATIONS.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`, `README.md`

**Key Changes:**
- Added a server-rendered operator console mounted on the existing Management API, organized around a persistent left sidebar: Summary, Agents, Tools & Skills, Inference, Memory, Users & Access, Security, Audit, System.
- Zero build step: Jinja2 templates + HTMX (dashboard polling, live simulator) + Alpine.js (toasts), all vendored (no CDN) to preserve the offline/security posture. Ships in the same `corvus-server` process and Docker image.
- Presentation-layer only: UI handlers call the app's own `/v1` JSON endpoints in-process via an httpx `ASGITransport` client (`ApiClient`), injecting the server-held API key. All validation and audit are reused verbatim; GUI mutations are audited identically to API calls.
- Full read/write for API-mutable resources (agents create/launch/stop, namespace quotas, RBAC rules CRUD + dry-run simulator, grants, elevations approve/deny, quotas, users). Env-only settings (behavioral thresholds, TTLs/sweeper intervals, encryption, LLM provider registry, runtime settings) are surfaced read-only under their category.
- Auth: `/ui/login` validates the Management API key and sets a signed HttpOnly session cookie (stdlib `hmac`); the raw key is never stored in the browser after login. New config: `CORVUS_UI_ENABLED` (default `1`), `CORVUS_UI_SESSION_SECRET` (random per-process default), `CORVUS_UI_PATH_PREFIX` (default `/ui`).
- System page redacts `api_key` / `memory_master_key` / `ui_session_secret`.
- Tests: 17 UI tests (auth redirect, all nav routes, agent create/detail, rule create/delete + invalid JSON, simulator fragment, grant create/revoke, user create/detail, audit query, secret redaction, disabled-UI 404). Full suite 171 passing; ruff clean on new files.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-12] - Session routing keyed on (agent_id, vm_id): no VM collisions

**Documents Modified:**
- `src/corvus/server/transport.py`, `handshake.py`, `router.py`, `pending_replay.py`, `db.py`
- `src/corvus/memory/elevation_replay.py`
- `tests/test_transport.py` (new), `tests/test_pending_replay.py`, `tests/test_runtime_multiagent.py`, `tests/test_correlation.py`, `tests/test_elevation_replay.py`, `tests/test_engine4_memory_integration.py`, `tests/test_production_hardening.py`

**Key Changes:**
- `AgentTransport` now keys active connections on `(agent_id, vm_id)` instead of `agent_id` alone. Previously, when two VMs of the same agent handshook, the second overwrote the first's binding, so LLM stream chunks, `llm_response`, elevation replays, and grant notifications were misrouted to a single VM and one VM's disconnect could evict the other's binding. This was the root cause of the same-agent multi-VM turn stall observed during concurrency testing.
- Handshake binds `bind_agent(agent_id, vm_instance_id, connection_id)`; the router's handshake-ack reconnect flush is now VM-scoped (`flush_for_vm(agent_id, vm_id)`).
- The router's outbound LLM stream (`_run_llm_stream`) and Engine 4 elevation replay + grant-created notification deliver via `transport.deliver(agent_id, vm_id, message)`.
- Offline replay is VM-scoped end to end: `pending_replay` gains a `vm_id` column (idempotent migration + `(agent_id, vm_id, delivered_at, created_at)` index); `enqueue`/`list`/`count` and `PendingReplayQueue.enqueue`/`flush_for_vm` all carry `vm_id`, so a reconnecting VM only drains its own queued messages.
- Inbound hardening: after the existing `agent_id`-vs-session check, the router now also rejects any message whose `source.vm_id` does not match the session's `vm_id` (`SERVER_SESSION_INVALID`).
- Quota keys are intentionally unchanged: LLM tokens stay pooled per user, memory writes per agent (across an agent's VMs).
- Added `tests/test_transport.py` (VM-scoped routing, unbind isolation, no eviction on second VM bind), a same-agent two-VM concurrent streaming+tools integration test (the previously-stalling scenario, now reaching DONE for both VMs), and a VM-scoped pending-replay flush isolation test.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-11] - Turn-abort robustness: no stalled turns hang the runtime

**Documents Modified:**
- `src/corvus/runtime/coordinator.py`, `config.py`, `loop.py`, `supervisor.py`
- `src/corvus/runtime/engines/engine1.py`, `engine2.py`, `engine3.py`
- `tests/test_runtime_coordinator.py`, `tests/test_runtime_robustness.py`, `tests/test_runtime_multiagent.py`

**Key Changes:**
- Added a terminal `ABORTED` phase plus `TERMINAL_PHASES`, `await_phase_in`, `is_terminal`, and an idempotent `abort(reason, ...)` to the coordinator, so a failed or stalled turn deterministically unblocks every engine.
- Engine 1's COLLECT loop is now bounded: it exits when the turn leaves COLLECT (RESPOND/DONE/ABORTED), on a stop request, or when the configurable turn deadline lapses. Previously a stalled turn spun this loop forever and a `--once` runtime never exited.
- Engines 2 and 3 now call `abort(...)` on every failure/return path (dispatch/collect/respond timeouts, LLM failure, tool-batch timeout, max tool iterations, user_query / agent_response failures). Engine 2 waits for RESPOND-or-terminal instead of RESPOND-or-timeout.
- The agent loop awaits DONE-or-ABORTED (bounded by `turn_timeout_seconds`) and aborts on turn timeout, returning failure instead of hanging.
- Supervisor `--once` is now loop-authoritative: once the loop resolves the turn, engines are stopped and, after a short grace window for in-flight IPC, cancelled — a stalled engine can no longer hang the runtime (critical for concurrent multi-agent runs).
- New `CORVUS_TURN_TIMEOUT_SECONDS` (default 120s) drives both the loop deadline and Engine 1's COLLECT backstop.
- Added robustness tests (Engine 1 loop exits on deadline / abort / stop; coordinator abort + `await_phase_in` semantics) and a concurrent two-agent streaming+tools integration test sharing one user's quota counter.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-11] - Fix quota counter creation race under concurrent streaming

**Documents Modified:**
- `src/corvus/server/db.py`

**Key Changes:**
- `get_or_create_quota_counter` now performs an idempotent `INSERT ... ON CONFLICT(key) DO NOTHING` followed by a re-select, instead of a non-atomic SELECT-then-INSERT.
- Fixes an `IntegrityError: UNIQUE constraint failed: quota_counters.key` raised when two agents sharing a user streamed completions concurrently; the crash in the background `_run_llm_stream` task previously prevented the final `llm_response` from being delivered, stalling the affected agent's turn. Surfaced by a live two-agent simulation.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-11] - Phase 7.2b Streaming + tool_calls — Complete

**Documents Modified:**
- `src/corvus/llm/service.py`, `providers/stub.py`, `providers/openai_compat.py`, `dummy_server.py`
- `src/corvus/runtime/engines/engine3.py`, `runtime/llm_client.py`
- `tests/test_llm_streaming.py`
- `corvus-docs/docs/planning/PHASES.md`, `ROADMAP.md`, `COMPONENT-STATUS.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`, `agent-vm/AGENT-WORKFLOW.md`

**Key Changes:**
- LLM streaming now coexists with local-mode `tools_schema`. The gateway no longer rejects `stream` + local tools; only provider-hosted tools (hybrid `provider_tools` / `provider_tools_requested`) remain rejected with `LLM_STREAM_TOOLS_UNSUPPORTED`.
- Provider adapters surface `tool_calls` from streams: stub emits a terminal completion with deterministic tool calls (`finish_reason: tool_calls`); OpenAI-compatible adapter assembles `delta.tool_calls` fragments across SSE chunks.
- Engine 3 streams even when a tools schema is present and drives the Engine 1 tool loop from the final streamed `llm_response`; `collect_llm_stream` preserves `tool_calls`/`finish_reason` when text was also streamed.
- Dummy LLM server gained a streaming tool-call SSE mode for adapter tests.
- Streaming + provider-hosted (hybrid) tools remains deferred.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Default chat-only agent manifest

**Documents Modified:**
- `src/corvus/server/manifest.py`, `bootstrap.py`
- `config/default_rules.yaml`
- `tools/rootfs/manifest.json`, `tools/run-turn.sh`, `tools/corvus.env.example`
- `src/corvus/runtime/supervisor.py`
- `tests/conftest.py`, `tests/test_default_chat_manifest.py` (+ integration test updates)

**Key Changes:**
- Empty `AgentManifest()` now resolves to basic chat: Engine 2 `api` platform, Engine 3 `stub`/`stub-v1`, no tools, skills, or memory namespaces.
- Bootstrap registers `test-agent-01` with chat manifest; `FULL_TEST_MANIFEST` retained for tools/memory integration tests.
- `run-turn.sh` defaults to `--once` (Engine 2 + 3 only); tools/memory require explicit `--all-engines` and `CORVUS_LLM_LOCAL_TOOLS`.
- RBAC `allow-llm-request` includes `operator` role.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 7.2 LLM Streaming — Complete

**Documents Modified:**
- `src/corvus/llm/service.py`, `models.py`, `prepared.py`, `providers/*`, `dummy_server.py`
- `src/corvus/server/router.py`, `bootstrap.py`
- `src/corvus/runtime/llm_client.py`, `engines/engine3.py`, `config.py`
- `src/corvus/node/routing.py`
- `tests/test_llm_streaming.py`
- `corvus-docs/docs/planning/PHASES.md`, `ROADMAP.md`, `COMPONENT-STATUS.md`, `OPERATIONS.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`
- `tools/corvus.env.example`

**Key Changes:**
- `llm_request.stream` triggers sync `llm_stream_start`, async `llm_stream_chunk` events, and final `llm_response` via `AgentTransport.deliver`.
- Stub and OpenAI-compatible SSE adapters; dummy HTTP server supports `stream: true`.
- MVP rejects streaming with `tools_schema`; Engine 3 opt-in via `CORVUS_LLM_STREAM=1`.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 7.4 documentation sync

**Documents Modified:**
- `corvus-docs/docs/planning/ROADMAP.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`, `RBAC-POLICY.md`
- `corvus-docs/docs/architecture/agent-vm/ARCHITECTURE.md`
- `corvus-docs/README.md`, `README.md`, `AGENTS.md`
- `tools/corvus.env.example`, `tools/rootfs/manifest.json`, `tools/run-turn.sh`
- `config/policy_fixtures/llm.yaml`
- `src/corvus/policy/facts.py`, `src/corvus/tools/policy_fixtures.py`

**Key Changes:**
- Synced manifest schema, catalog, RBAC, env example, and rootfs manifest with Phase 7.4 tool execution policy fields.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 7.4 Tool Execution Policy — Complete

**Documents Modified:**
- `src/corvus/llm/tool_policy.py`, `service.py`, `models.py`, `registry.py`, `providers/*`
- `src/corvus/server/manifest.py`, `catalog.py`, `config.py`
- `src/corvus/runtime/engines/engine3.py`, `engine1.py`, `coordinator.py`, `tool_schemas.py`, `config.py`
- `src/corvus/policy/facts.py`, `models.py`, `config/default_rules.yaml`
- `config/llm_providers.yaml`
- `tests/test_tool_execution_policy.py`, `tests/conftest.py`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `OPERATIONS.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`, `agent-vm/AGENT-WORKFLOW.md`

**Key Changes:**
- **Local mode (default):** gateway filters `tools_schema` to manifest `engine1.tools`; strips provider-native tool types; Engine 3 loops LLM → coordinator → Engine 1 VM execution.
- **Hybrid mode (opt-in):** manifest `engine3.tool_execution_mode: hybrid` + `provider_tools` + registry `hosted_tools_allowed`; audit `provider_tool_invocation`.
- RBAC rules for hybrid LLM requests (admin-only); default `CORVUS_MAX_CHAIN_DEPTH` raised to 16 for multi-hop tool turns.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Tool Gateway: server approval, VM-local execution

**Documents Modified:**
- `src/corvus/tools/service.py`, `models.py`, `terminal.py`, `server/router.py`, `runtime/tool_client.py`, `runtime/engines/engine1.py`
- `tests/test_tool_gateway.py`, `tests/test_terminal_tool.py`
- `corvus-docs/docs/architecture/agent-vm/AGENT-WORKFLOW.md`

**Key Changes:**
- `ToolGatewayService` approves `tool_call` after RBAC + manifest gate; returns explicit `tool_call_response` with `approved: true` before Engine 1 runs anything.
- `terminal` tool runs subprocess inside the agent VM (allowlisted commands only); server never executes tools.
- Audit `tool_operation` events for call approval and result recording.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 7.3 Engine 1 Tool Loop — Complete

**Documents Modified:**
- `src/corvus/tools/echo.py`, `runner.py`, `runtime/tool_client.py`, `runtime/engines/engine1.py`
- `tests/test_tool_integration.py`, `tests/test_runtime_integration.py`
- `corvus-docs/docs/planning/PHASES.md`

**Key Changes:**
- Engine 1 participates in COLLECT: sends `tool_call` through Node → server RBAC, runs `echo` locally, sends `tool_result`.
- Removed once-mode idle skip for Engine 1.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 7.1 Server-Side LLM Gateway — Complete

**Documents Modified:**
- `config/llm_providers.yaml`, `config/policy_fixtures/llm.yaml`
- `src/corvus/llm/` (credentials, registry, service, OpenAI-compat + stub adapters)
- `src/corvus/server/bootstrap.py`, `router.py`, `config.py`, `manifest.py`
- `src/corvus/runtime/llm_client.py`, `runtime/engines/engine3.py`
- `src/corvus/audit/store.py`, `policy/quota.py`, `management/api.py`, `protocol/models.py`
- `tests/test_llm_*.py`, `tests/test_catalog_api.py`, `tests/conftest.py`, `tests/test_management.py`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `OPERATIONS.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`, `RBAC-POLICY.md`, `agent-vm/AGENT-WORKFLOW.md`

**Key Changes:**
- Server-side `LlmGatewayService` proxies `llm_request` to OpenAI-compatible endpoints; Engine 3 receives server-origin `llm_response` only.
- Provider registry (`config/llm_providers.yaml`); credentials resolved via `env:` and `file:` refs on server only — never in VM, manifest, handshake, or message payloads.
- Manifest + registry gates; audit `llm_completion` events; post-allow quota increment on `user:{id}:llm_tokens:daily`.
- Catalog API strips `credential_ref` and base URLs from `GET /v1/catalog/llm-providers`.

**Impact:**
- Phase 7.1 complete: typical agent-stack LLM flow with server-held secrets. Engine 3 no longer fabricates outbound `llm_response`.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 6 Tooling & Operations — Complete

**Documents Modified:**
- `src/corvus/server/metrics.py`, `src/corvus/management/api.py`
- `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/README.md`
- `tests/test_metrics.py`, `Makefile`, `README.md`, `.gitignore`
- `corvus-docs/docs/planning/OPERATIONS.md`, `PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`
- `corvus-docs/README.md`, `MANAGEMENT-API.md`, `AGENTS.md`

**Key Changes:**
- Added `GET /v1/metrics` Prometheus text exposition (health-derived gauges).
- Docker packaging for Corvus Server (`deploy/docker-compose.yml`) with persistent `/data` volume.
- Operator runbook: `corvus-docs/docs/planning/OPERATIONS.md` (dev stack, Docker, metrics, fixtures, elevation ops).
- Makefile targets: `docker-build`, `docker-up`, `docker-down`.

**Impact:**
- Phase 6 complete: policy fixture CI, dev tooling, OpenAPI export, structured logging, deployment packaging, metrics, operator docs. 97 tests passing.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 6 Tooling & Operations (start)

**Documents Modified:**
- `src/corvus/tools/policy_fixtures.py`, `src/corvus/server/logging_config.py`, `src/corvus/server/main.py`
- `config/policy_fixtures/core.yaml`, `Makefile`, `tools/dev-stack.sh`, `tools/corvus.env.example`, `tools/export-openapi.sh`
- `tests/test_policy_fixtures.py`, `.github/workflows/ci.yml`, `pyproject.toml`, `README.md`
- `corvus-docs/docs/planning/PHASES.md`, `RBAC-POLICY.md`

**Key Changes:**
- Added YAML policy fixture runner (`corvus-policy-fixtures`) with 8-case core regression suite; wired into CI.
- Dev stack helper (`tools/dev-stack.sh`) and Makefile targets for install/test/fixtures/dev-up/down.
- Optional structured JSON logging via `CORVUS_LOG_JSON=1`; offline OpenAPI export script.
- Management API interactive docs remain at `/docs` on a running server.

**Impact:**
- Rule changes can be gated by fixture suite before activation. Superseded by Phase 6 complete entry below.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 5.4 Production Hardening

**Documents Modified:**
- `src/corvus/policy/quota.py`, `src/corvus/memory/encryption.py`, `src/corvus/memory/service.py`
- `src/corvus/server/db.py`, `src/corvus/server/config.py`, `src/corvus/server/bootstrap.py`, `src/corvus/server/router.py`
- `src/corvus/memory/sweeper.py`, `src/corvus/server/elevation_sweeper.py`, `src/corvus/management/api.py`
- `pyproject.toml`, `tests/test_production_hardening.py`, `tests/test_management.py`, `tests/conftest.py`, `tests/test_correlation.py`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`, `agent-vm/AGENT-WORKFLOW.md`

**Key Changes:**
- `QuotaService.increment_memory_write` meters per-agent daily memory writes (`agent:{id}:memory_writes:daily`) on successful router `memory:write`.
- Optional AES-GCM at-rest encryption via `CORVUS_MEMORY_ENCRYPTION=1` and `CORVUS_MASTER_KEY`; content flagged with `metadata.encrypted`.
- Extended `GET /v1/health` with sweeper liveness, pending replay queue depth, and behavioral counter freshness.
- Sweeper `is_running` properties for memory and elevation background tasks.

**Impact:**
- Phase 5 core infrastructure complete: quota metering, encryption opt-in, ops health surface, restart-safe persistence verified.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 5.3 Behavioral Monitoring

**Documents Modified:**
- `src/corvus/policy/behavioral.py`, `src/corvus/policy/facts.py`, `src/corvus/policy/rules.py`, `src/corvus/policy/models.py`, `src/corvus/policy/combiner.py`, `src/corvus/policy/engine.py`
- `src/corvus/server/db.py`, `src/corvus/server/config.py`, `src/corvus/server/bootstrap.py`, `src/corvus/server/router.py`
- `config/default_rules.yaml`
- `tests/test_behavioral_monitor.py`, `tests/test_behavioral_policy_integration.py`, `tests/test_policy.py`, `tests/conftest.py`, `tests/test_correlation.py`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `RBAC-POLICY.md`

**Key Changes:**
- Added SQLite `behavioral_counters` table and `BehavioralMonitor` service with restart-safe sliding-window counters.
- Live `behavioral_signals` in `FactGatherer`: `message_rate_anomaly`, `repeated_grant_denials` (cross-agent `no_valid_grant` only), `cross_agent_scope_spike`, stub `tool_pattern_deviation`.
- Router records message hops before policy and grant-denial outcomes after policy; rule engine supports `{ gt: N }` signal comparators.
- Default safety rules: `deny-repeated-grant-denials` (priority 150), `deny-cross-agent-scope-spike`, `elevate-message-rate-anomaly`.
- Simulate API accepts `behavioral_signals` overrides in context.

**Impact:**
- 4 cross-agent grant failures within 10 minutes cause the 5th memory request to be denied by behavioral rule (not elevated). 88 tests passing.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 5.2 Elevation Workflows

**Documents Modified:**
- `src/corvus/server/db.py`, `src/corvus/server/pending_replay.py`, `src/corvus/server/elevation_sweeper.py`, `src/corvus/server/elevation_notify.py`
- `src/corvus/memory/elevation_replay.py`, `src/corvus/server/handshake.py`, `src/corvus/server/router.py`, `src/corvus/server/bootstrap.py`, `src/corvus/server/config.py`
- `src/corvus/management/api.py`, `src/corvus/node/ipc.py`, `src/corvus/node/main.py`
- `tests/test_pending_replay.py`, `tests/test_elevation_sweeper.py`, `tests/test_engine4_memory_integration.py`, `tests/test_elevation_replay.py`, `tests/test_correlation.py`, `tests/conftest.py`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `MANAGEMENT-API.md`

**Key Changes:**
- Added SQLite `pending_replay` table and `PendingReplayQueue`; undelivered elevation replay messages enqueue when agent transport is offline and flush on handshake ack after reconnect.
- `ElevationReplayService` returns `pending_replay_queued`; Management API surfaces it on approve responses.
- `ElevationSweeper` expires pending elevations past TTL (default 1h); approve rejects expired/non-pending elevations with HTTP 409.
- Router emits `elevation_pending` audit events; optional `CORVUS_ELEVATION_WEBHOOK_URL` dispatches non-blocking webhook POST.
- Node IPC buffers inbound server-push messages until engine clients subscribe (enables offline replay delivery on reconnect).
- `GET /v1/elevations` accepts `agent_id` and `status` filters.

**Impact:**
- Elevation control plane is complete: create → notify → approve → replay (including after agent reconnect) → expire. 80 tests passing.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 5.1 Full Turn + Correlation Traceability

**Documents Modified:**
- `src/corvus/audit/store.py`, `src/corvus/server/db.py`, `src/corvus/server/correlation.py`, `src/corvus/server/router.py`
- `src/corvus/management/api.py`, `src/corvus/vm/turn_wait.py`
- `tools/wait_vm_full_turn.py`, `tools/vm-smoke.sh`
- `tests/test_correlation.py`, `tests/test_turn_trace_integration.py`, `tests/test_vm_turn_wait.py`
- `tests/test_runtime_loop.py`, `tests/test_node_integration.py`, `tests/test_runtime_supervisor.py`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`, `MANAGEMENT-API.md`

**Key Changes:**
- Added `origin_correlation_id` column and index on `audit_log`; all message hops, policy decisions, and memory audit events record turn root.
- Management API `GET /v1/audit/logs` accepts `origin_correlation_id` filter.
- Correlation validation returns `SERVER_CORRELATION_EXPIRED` before purge; router passes `correlation_valid` to policy.
- Added `turn_state` SQLite table; `CorrelationStore` persists turn chains across server restart.
- Added `turn_wait.py` and `wait_vm_full_turn.py` — polls audit for user_query + llm + memory hops per turn.
- Extended `vm-smoke.sh` with full-turn gate (`CORVUS_VM_SMOKE_SKIP_FULL_TURN=1` to skip).
- Integration tests: correlation edge cases, TCP turn trace, vm turn waiter unit tests.

**Impact:**
- Full agent turns are traceable by turn root ID across Engine 2/3/4 server-side hops; Firecracker smoke validates end-to-end guest turn completion (`vm-smoke.sh` memory + full-turn audit gates passing on KVM).

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 4.5 Elevation Auto-Retry

**Documents Modified:**
- `src/corvus/memory/elevation_replay.py`, `src/corvus/server/transport.py`
- `src/corvus/server/handshake.py`, `src/corvus/server/vsock.py`, `src/corvus/server/router.py`
- `src/corvus/server/bootstrap.py`, `src/corvus/management/api.py`
- `src/corvus/runtime/memory_client.py`, `src/corvus/runtime/engines/engine4.py`, `src/corvus/runtime/ipc_client.py`
- `tests/test_elevation_replay.py`, `tests/test_engine4_memory_integration.py`
- `corvus-docs/docs/architecture/memory/ARCHITECTURE.md`, `PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`, `README.md`

**Key Changes:**
- `AgentTransport` tracks connected agents and enables server-initiated delivery after handshake.
- `ElevationReplayService` replays approved memory operations with the new grant and pushes `memory:*_response` plus `memory:grant_created` to Engine 4.
- `memory:grant_request` payloads may include `pending_replay`; router persists it in elevation context.
- Management API `POST /v1/elevations/{id}/approve` returns a `replay` summary; grant_request elevations auto-create grants when `create_grant` is omitted.
- IPC inbound handler fix: server-push messages invoke the handler without starving `submit_and_wait` responses.

**Impact:**
- Phase 4 memory elevation path is end-to-end: deny → approve → automatic replay to connected agent.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 4.3–4.4 Memory Semantic Search + TTL Sweeper

**Documents Modified:**
- `src/corvus/memory/embeddings.py`, `src/corvus/memory/vec_store.py`, `src/corvus/memory/sweeper.py`
- `src/corvus/memory/service.py`, `src/corvus/server/db.py`, `src/corvus/server/bootstrap.py`, `src/corvus/server/config.py`
- `pyproject.toml`, `tests/test_memory_embeddings.py`, `tests/test_memory_service.py`, `tests/test_memory_sweeper.py`
- `corvus-docs/docs/architecture/memory/ARCHITECTURE.md`, `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`, `README.md`

**Key Changes:**
- Added sqlite-vec `memory_embeddings` virtual table; writes index deterministic hash embeddings; `memory:query` semantic type uses cosine KNN.
- Background `MemoryRetentionSweeper` purges expired records and hard-deletes soft-deleted records after 24h (configurable).
- Dependency: `sqlite-vec>=0.1.6`.

**Impact:**
- Semantic memory search operational for key/list/semantic query types. Elevation auto-retry remains deferred (Phase 4.5).

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 4.2 Firecracker Smoke Verified (VSOCK UDS + Loop Race)

**Documents Modified:**
- `src/corvus/server/vsock.py`, `src/corvus/runtime/loop.py`
- `tools/vm-smoke.sh`, `tests/test_runtime_loop.py`
- `corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md`

**Key Changes:**
- Firecracker guest-initiated vsock connections require the host to listen on `{uds_path}_{port}` (e.g. `vsock-<vm_id>.sock_4040`), not the base Firecracker UDS path.
- `TransportGateway` watches VM state dir and binds per-VM port sockets; `vm-smoke.sh` stops stale `corvus-server` processes and uses a dedicated smoke DB.
- Agent Loop no longer clears coordinator `ready` on INIT, fixing a race when engine systemd units start before `corvus-loop.service`.
- Rebuilt rootfs and verified `bash tools/vm-smoke.sh` end-to-end (~10s to memory record).

**Impact:**
- Phase 4.2 exit gate met: guest Engine 4 memory write/query over VSOCK reaches server SQLite.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 4.2 Firecracker In-VM Memory Smoke

**Documents Modified:**
- `src/corvus/vm/memory_wait.py`, `tools/wait_vm_memory_turn.py`, `tools/vm-smoke.sh`
- `tools/rootfs/overlay/etc/systemd/system/corvus-engine4.service`
- `tests/test_vm_memory_wait.py`
- `corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`
- `README.md`, `corvus-docs/README.md`

**Key Changes:**
- Added host-side polling for Engine 4 turn-scoped memory records in server SQLite after VM launch.
- Extended `tools/vm-smoke.sh` to wait for a `turn-*` record with Engine 4 snapshot content (skippable via `CORVUS_VM_SMOKE_SKIP_MEMORY=1`).
- Renamed guest `corvus-engine4.service` description to Memory client.
- Added unit tests for memory wait helper (54 tests total).

**Impact:**
- Firecracker smoke now validates the full VSOCK path including guest Engine 4 write/query when rootfs is rebuilt post-Phase 4.1. Requires local KVM/vsock; semantic search, TTL sweeper, and elevation auto-retry remain deferred.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 4.1 Engine 4 Client + E2E Memory Turn Validation

**Documents Modified:**
- `src/corvus/runtime/coordinator.py`, `src/corvus/runtime/memory_client.py`
- `src/corvus/runtime/engines/base.py`, `src/corvus/runtime/engines/engine4.py`
- `tests/test_memory_client.py`, `tests/test_engine4_memory_integration.py`, `tests/test_runtime_integration.py`
- `README.md`, `corvus-docs/README.md`
- `corvus-docs/docs/architecture/memory/ARCHITECTURE.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`

**Key Changes:**
- Removed Engine 4 from once-mode idle skip; `MemoryEngine.serve()` runs during COLLECT.
- Added `Coordinator.merge_fields()` for turn-scoped state without phase transitions.
- Added `runtime/memory_client.py` with memory message builders and response/error parsing.
- Implemented own-namespace write + key query per turn with coordinator assertions (`memory_write_record_id`, `memory_query_hit`, `memory_query_content`).
- Added elevation/grant-request helper for cross-agent failures (manual retry; no auto-replay).
- Added integration tests: Node IPC write/query, full runtime turn, cross-agent query with grant, elevation path.
- Test count: 52 passing (`pytest`).

**Impact:**
- The vertical memory path is proven on the agent side over TCP: Engine 4 → Corvus Node → Corvus Server → Memory Service → response. Firecracker in-VM validation added in Phase 4.2. Semantic search (sqlite-vec), TTL sweeper, and elevation auto-retry remain follow-up work.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 4 Memory Service MVP

**Documents Modified:**
- `src/corvus/memory/models.py`, `src/corvus/memory/service.py`, `src/corvus/memory/__init__.py`
- `src/corvus/server/db.py`, `src/corvus/server/bootstrap.py`, `src/corvus/server/router.py`
- `src/corvus/audit/store.py`, `src/corvus/protocol/models.py`
- `tests/test_memory_service.py`, `tests/test_handshake.py`
- `README.md`, `corvus-docs/README.md`
- `corvus-docs/docs/architecture/memory/ARCHITECTURE.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`

**Key Changes:**
- Added server-side Memory Service with SQLite `memory_records` storage.
- Implemented `memory:write`, `memory:query` (`key`/`list`), and `memory:delete` with protocol-shaped responses.
- Routed memory messages through the server router after RBAC allow instead of generic ack stubs.
- Enforced namespace assignment, cross-agent grant invariants, namespace quota limits, TTL filtering, and soft delete.
- Added memory operation audit events (`memory_write`, `memory_query`, `memory_delete`).
- Added focused service and router integration tests.

**Impact:**
- Phase 4 Memory MVP is operational on the server path. Semantic search (sqlite-vec) and TTL sweeper remain follow-up work (Engine 4 client, TCP turn validation, and Firecracker memory smoke completed in Phases 4.1–4.2).

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Pre-Phase-4 Memory Contract Cleanup

**Documents Modified:**
- `src/corvus/server/catalog.py`, `src/corvus/server/db.py`
- `src/corvus/policy/facts.py`, `src/corvus/policy/rules.py`, `src/corvus/policy/engine.py`
- `src/corvus/management/api.py`
- `tests/test_policy.py`, `tests/test_management.py`
- `README.md`, `corvus-docs/README.md`
- `corvus-docs/docs/architecture/hypervisor/RBAC-POLICY.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`
- `corvus-docs/docs/architecture/memory/ARCHITECTURE.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`

**Key Changes:**
- Canonicalized memory namespace templates to `private` and `shared-knowledge`.
- Canonicalized memory payload fact gathering on `target_agent_id`, while preserving transitional `target_agent` alias support at boundaries.
- Added per-agent namespace quota config storage and Management API surfaces for namespace `GET`/`PATCH`.
- Added audit events for namespace quota mutations.
- Clarified RBAC grant evaluation versus Phase 4 Memory Service enforcement and documented elevation approval as grant creation plus agent retry.
- Added focused tests for namespace defaults, `target_agent_id` grant evaluation, namespace quota APIs, and audit entries.

**Impact:**
- Phase 4 Memory can start from aligned namespace, payload, quota, grant, elevation, and audit contracts. Memory Service, sqlite-vec storage, memory record tables, and cross-agent memory routes remain not started.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - RBAC Scope Alignment

**Documents Modified:**
- `src/corvus/policy/models.py`, `identity.py`, `grants.py`, `quota.py`
- `src/corvus/policy/facts.py`, `rules.py`, `engine.py`, `combiner.py`
- `src/corvus/server/db.py`, `bootstrap.py`, `handshake.py`, `router.py`
- `src/corvus/audit/store.py`, `src/corvus/management/api.py`
- `src/corvus/node/ipc.py`
- `config/default_rules.yaml`
- `tests/test_policy.py`, `tests/test_management.py`
- `corvus-docs/docs/architecture/hypervisor/RBAC-POLICY.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`

**Key Changes:**
- Added schema-validated RBAC rules and completed rule update/delete API paths.
- Added channel identity and alias resolution for CLI/API/chat channels, with CLI PIN/password verification stored as hashes.
- Added DB-backed grants and live `has_valid_grant` evaluation for `memory:*` RBAC gates.
- Added quota counter and elevation control-plane foundations, including elevation records and approval/denial APIs.
- Enforced elevation approval authority: admin role, elevation-approver group, or explicit approval privilege plus valid credentials.
- Added dangerous tool/shell action classification and a default elevation rule for high-risk tool calls.
- Derived Corvus Node handshake policy snapshots from active rules plus manifest capabilities while preserving node enforcement defaults.
- Expanded RBAC auditability with redaction, rule/grant/quota/elevation metadata, conflict traces, and audit filters.
- Added default engine4 memory rule requiring a valid grant and elevating otherwise.

**Impact:**
- RBAC is aligned with the project’s granular/configurable scope before Phase 4 Memory. Memory storage, sqlite-vec, and cross-agent memory routes remain not started.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 3.5 Control-Plane Hardening

**Documents Modified:**
- `src/corvus/server/catalog.py`, `src/corvus/server/manifest.py`, `src/corvus/server/bootstrap.py`
- `src/corvus/management/api.py`
- `src/corvus/vm/launcher.py`, `src/corvus/vm/registry.py`, `src/corvus/vm/spec.py`, `src/corvus/vm/main.py`
- `src/corvus/server/handshake.py`, `src/corvus/server/session.py`, `src/corvus/server/vsock.py`, `src/corvus/server/main.py`
- `tools/rootfs/build.sh`, `tools/rootfs/manifest.json`
- `tests/test_management.py`, `tests/test_vm_registry.py`, `tests/test_vm_launcher.py`, `tests/test_vm_spec.py`, `tests/test_handshake.py`
- `README.md`, `corvus-docs/README.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`, `ROADMAP.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`
- `corvus-docs/docs/architecture/agent-vm/ARCHITECTURE.md`, `FIRECRACKER.md`

**Key Changes:**
- Added typed launch manifest models with canonical manifest hashing and server-side catalog resolution.
- Added server-owned catalogs for tools, skills, LLM providers, workspaces, and memory namespace templates.
- Added GUI-ready Management API surfaces for catalogs, agent manifests, per-agent VM records, and health.
- Generated per-VM launch packages containing canonical `manifest.json` and env, and injected guest identity/hash/config through Firecracker boot arguments.
- Extended VM lifecycle records with manifest hash, timestamps, PID liveness, logs, launch package path, stop state, and last error.
- Hardened handshake/session readiness by validating registered engines against the launch manifest and unbinding server sessions on transport disconnect.
- Re-checked the Phase 4 gate: Memory Service remains not started; Phase 4 must build on the typed namespace/grant/quota launch contracts.

**Impact:**
- Corvus remains hypervisor-focused before Phase 4: Server owns catalogs/tools/skills/LLM/workspaces/memory namespace templates and packages selected capabilities into VMs at launch.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Firecracker Smoke Validation

**Documents Modified:**
- `src/corvus/server/vsock.py`
- `src/corvus/vm/config.py`, `src/corvus/vm/fc_client.py`, `src/corvus/vm/launcher.py`, `src/corvus/vm/registry.py`
- `tools/rootfs/fetch-kernel.sh`, `tools/rootfs/build.sh`, `tools/vm-smoke.sh`
- `.github/workflows/firecracker-smoke.yml`
- `README.md`, `corvus-docs/README.md`
- `corvus-docs/docs/planning/PHASES.md`, `COMPONENT-STATUS.md`
- `corvus-docs/docs/architecture/OVERVIEW.md`
- `corvus-docs/docs/architecture/hypervisor/ARCHITECTURE.md`, `FRAMEWORK-MESSAGE-PROTOCOL.md`, `RBAC-POLICY.md`, `MANAGEMENT-API.md`
- `corvus-docs/docs/architecture/agent-vm/ARCHITECTURE.md`, `CORVUS-NODE.md`
- `corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md`

**Key Changes:**
- Verified local Firecracker launch/registry/stop smoke with KVM and VSOCK available.
- Fixed AF_VSOCK server startup by binding an `AF_VSOCK` socket explicitly before passing it to `asyncio.start_server`.
- Updated Firecracker state paths to default to `/tmp/corvus-vms`, avoiding Unix socket path length failures.
- Improved Firecracker API errors with response-body details and persisted launch stdout/stderr logs.
- Refreshed VM registry reads from disk so separate server/API and CLI processes see current VM state.
- Hardened `tools/vm-smoke.sh` preflights and failure handling: KVM ACL checks, server liveness check, and required Management API `running` status before success.
- Updated rootfs tooling to use a current Firecracker kernel URL and a Python 3.12 Debian/systemd rootfs build.
- Updated the manual Firecracker smoke workflow to require a self-hosted Linux runner with KVM/VSOCK access.
- Reconciled implemented architecture document status headers with the current Phase 2/3 code state.
- Documented that temporary `/dev/kvm` ACL grants may need reapplying until permanent `kvm` group membership is active in a new login session.

**Impact:**
- Phase 3 Firecracker host-side smoke is now verified locally: Firecracker accepts configuration, starts a microVM, Management API reports the VM as `running`, and stop cleanup succeeds. Full in-VM agent turn validation remains future work.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 3 Stabilization

**Documents Modified:**
- `tests/conftest.py`, `tests/test_node_bus.py`, `tests/test_vm_launcher.py`
- `src/corvus/node/bus.py`, `src/corvus/node/main.py`
- `src/corvus/runtime/engines/base.py`
- `src/corvus/vm/launcher.py`
- `tools/rootfs/overlay/etc/systemd/system/corvus-*.service`, `tools/vm-smoke.sh`
- `README.md`, `AGENTS.md`, `corvus-docs/README.md`
- `corvus-docs/docs/planning/PHASES.md`, `ROADMAP.md`, `COMPONENT-STATUS.md`
- `corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md`

**Key Changes:**
- Fixed async pytest fixture registration for current pytest/pytest-asyncio.
- Added regression coverage for Node bus reconnect delivery and Firecracker partial-launch cleanup.
- Reworked Node bus reconnect to restart I/O loops and let `corvus-node` refresh its server session after reconnect.
- Hardened Firecracker launch so failed API configuration kills the unregistered process and removes transient sockets.
- Fixed guest service configuration: `corvus-node.service` now sets `PYTHONPATH=/opt/corvus`, and loop/engine units explicitly run in daemon mode.
- Kept daemon-mode engine processes alive after their serve cycle returns.
- Reconciled Phase 3 status docs and clarified that normal CI validates TCP while Firecracker smoke requires local KVM/VSOCK access.

**Impact:**
- Phase 3 is stabilized for the automated TCP path. `pytest` passes locally with 26 tests; Firecracker launch cleanup and guest service configuration are ready for local smoke validation.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Runtime Hang Fix

**Documents Modified:**
- `src/corvus/runtime/**`, `tests/test_runtime_*.py`, `pyproject.toml`, `README.md`

**Key Changes:**
- Added `--once` / `--daemon` run modes; loop exits cleanly after `DONE` in once mode.
- Added coordinator readiness gate (`mark_ready`, `await_engines_ready`) before DISPATCH.
- Improved IPC connect with `wait_for_socket`, configurable timeout, and progress logging.
- Added `corvus-runtime` supervisor CLI for in-process dev full-turn runs.

**Impact:**
- Manual runtime no longer appears hung after a successful turn; clear errors when engines are missing.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 3 Agent Runtime and Firecracker Integration

**Documents Modified:**
- `src/corvus/runtime/**`, `src/corvus/vm/**`, `tools/rootfs/**`, `tools/vm-smoke.sh`
- `tests/test_runtime_integration.py`, `tests/test_vm_*.py`, `tests/test_management.py`
- `src/corvus/server/config.py`, `src/corvus/node/config.py`, `src/corvus/management/api.py`
- `pyproject.toml`, `.github/workflows/firecracker-smoke.yml`
- `README.md`, `corvus-docs/docs/planning/COMPONENT-STATUS.md`, `PHASES.md`
- `corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md` (new)

**Key Changes:**
- Implemented Agent Runtime: Agent Loop state machine, 4 engine processes, shared Node IPC client.
- Fixed AF_VSOCK addressing: server listens on host CID 2 (`CORVUS_VSOCK_HOST_CID`); guest Node connects to CID 2.
- Implemented Firecracker launcher (`corvus-vm`), VM registry, spec builder, and Firecracker HTTP API client.
- Added rootfs build pipeline and `tools/vm-smoke.sh` driver.
- Extended Management API: `POST /v1/agents/{id}/launch`, `POST /v1/agents/{id}/stop`, agent VM status on list.
- Added optional `firecracker-smoke` GitHub workflow (manual dispatch, requires KVM).

**Impact:**
- Phase 3 exit criteria met. Full host-side runtime turn test passes over TCP; Firecracker path documented and scripted.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 3 Corvus Node Implementation

**Documents Modified:**
- `src/corvus/node/**`, `tests/test_node_*.py`, `pyproject.toml`
- `README.md`, `corvus-docs/docs/planning/COMPONENT-STATUS.md`

**Key Changes:**
- Implemented Corvus Node daemon under `src/corvus/node/` reusing `corvus.protocol`.
- Added Unix socket IPC (`subscribe_engine`, `submit_outbound`, `health_check`, `receive_inbound` push).
- Added outbound validation (origin attestation, capability checks, token-bucket rate limits).
- Added boot-time handshake, session/policy cache, AF_VSOCK/TCP bus client with reconnect/backoff.
- Added inbound routing per CORVUS-NODE Section 4 and `corvus-node` CLI entry point.
- Added 7 new pytest cases (14 total); end-to-end Node → Server → engine IPC path validated.

**Impact:**
- Phase 3 Corvus Node exit criteria met. Agent Runtime and Firecracker integration remain.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Documentation and Repository Housekeeping

**Documents Modified:**
- `LICENSE`
- `corvus-docs/README.md`
- `corvus-docs/docs/architecture/OVERVIEW.md`
- `corvus-docs/docs/planning/PHASES.md`, `ROADMAP.md`, `COMPONENT-STATUS.md`
- `README.md`, `AGENTS.md`

**Key Changes:**
- Added Apache 2.0 LICENSE file referenced by README files.
- Fixed changelog path references (`docs/CHANGES.md` → repository root `CHANGES.md`).
- Updated stale metadata (Last Updated dates, document status labels).
- Aligned OVERVIEW body status with frontmatter; added implementation pointers for Phase 3 return.

**Impact:**
- Repository is consistent and ready for Phase 3 (Agent Runtime) work.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 2 Core Hypervisor Implementation

**Documents Modified:**
- `pyproject.toml`, `src/corvus/**`, `config/default_rules.yaml`, `tests/**`, `.github/workflows/ci.yml`
- `README.md`, `corvus-docs/docs/planning/PHASES.md`, `ROADMAP.md`, `COMPONENT-STATUS.md`

**Key Changes:**
- Added Python package `corvus` with shared `corvus.protocol` (Pydantic models, NDJSON codec, error catalog).
- Implemented Corvus Server: AF_VSOCK/TCP gateway, handshake/session, correlation store, message router.
- Implemented RBAC PDP v1: YAML rules, fact gatherer, decision combiner, default-deny policy.
- Implemented append-only SQLite audit log and Management API v1 (agents, rules, simulate, audit logs).
- Added `corvus-fake-node` integration CLI and pytest suite (7 tests).

**Impact:**
- Phase 2 exit criteria met. End-to-end handshake + user_query + policy deny path validated via TCP.
- Phase 3 (Corvus Node + Firecracker) may proceed.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Changelog Review Attribution Standardization

**Documents Modified:**
- `CHANGES.md`
- `AGENTS.md`
- `corvus-docs/docs/architecture/hypervisor/RBAC-POLICY.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`

**Key Changes:**
- Replaced legacy review attribution entries with `Reviewed By: Black Rain Labs - R&D`.
- Removed third-party AI agent branding from `AGENTS.md` and example LLM provider references in architecture docs.

**Impact:**
- Consistent Black Rain Labs attribution and neutral documentation branding.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-07-05] - Phase 1 Architecture Completion

**Documents Modified:**
- `corvus-docs/docs/architecture/OVERVIEW.md`
- `corvus-docs/docs/architecture/hypervisor/ARCHITECTURE.md`
- `corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`
- `corvus-docs/docs/architecture/hypervisor/RBAC-POLICY.md`
- `corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md`
- `corvus-docs/docs/architecture/memory/ARCHITECTURE.md`
- `corvus-docs/docs/architecture/agent-vm/ARCHITECTURE.md`
- `corvus-docs/docs/architecture/agent-vm/CORVUS-NODE.md`
- `corvus-docs/docs/architecture/agent-vm/AGENT-WORKFLOW.md` (moved from `docs/architecture/agent-vm/`)
- `corvus-docs/docs/planning/COMPONENT-STATUS.md`
- `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, `corvus-docs/README.md`

**Key Changes:**
- Reconciled Internal Corvus merge: local validation is performed exclusively by Corvus Node across all docs.
- Canonicalized documentation under `corvus-docs/docs/`; moved AGENT-WORKFLOW.md and updated all entry-point links.
- Expanded FrameworkMessage Protocol to implementation-ready: Python dataclass model, payload schemas, correlation chain rules, handshake protocol, error catalog, serialization.
- Expanded Memory Architecture: data model, grant schema, operation flows, SQLite/sqlite-vec backend decision, retention and quotas.
- Finalized RBAC & Policy: conflict resolution, PDP evaluation pipeline, grant/quota/group/delegation models, simulation API contract, behavioral signal hooks.
- Completed Corvus Node interface contract: IPC spec, origin attestation, routing table, rate limits, error codes, module boundaries.
- Integration pass: hypervisor ARCHITECTURE, MANAGEMENT-API payload schemas, agent launch manifest, COMPONENT-STATUS marked Phase 1 complete.

**Impact:**
- Phase 1 (Architecture & Design) exit criteria met. Phase 2 (Core Hypervisor) implementation may proceed against stable specs.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-06-22] - Corvus Node Technical Expansion + Protocol Refinement

**Documents Modified:**
- `agent-vm/CORVUS-NODE.md`
- `hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md` (minor cross-reference updates)

**Key Changes:**
- Expanded Corvus Node with detailed technical responsibilities, message handling flows, local validation rules, error handling, and Python implementation guidance.
- Clarified relationship between Corvus Node and former Internal Corvus responsibilities.
- Kept changes consistent with the newly strengthened FrameworkMessage Protocol.

**Impact:**
- Corvus Node is now significantly more implementation-ready.
- Architecture remains consistent after the Internal Corvus merge.

**Reviewed By:** Black Rain Labs - R&D

---

## [2026-06-22] - Major FrameworkMessage Protocol Expansion

**Documents Modified:**
- `hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md`

**Key Changes:**
- Expanded to implementation-ready level with Python dataclass model.
- Added detailed header fields, routing logic, validation layers, error handling, versioning, and security notes.
- Made protocol significantly more robust and adaptable.
- Included concrete examples ready for development.

**Impact:**
- This is now the authoritative reference for implementing the messaging layer.
- Corvus Node and Server development can proceed against this spec.

**Reviewed By:** Black Rain Labs - R&D

**Black Rain Labs - Research & Development Division**

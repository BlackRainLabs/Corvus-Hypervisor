**Document:** PHASES.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-13
**Related Documents:** CHANGES.md
**Must Update on Change:** CHANGES.md

# Development Phases

## Phase 1: Architecture & Design — Complete
- Finalize core architecture documents
- Define FrameworkMessage Protocol in detail
- Define RBAC/Policy model
- Define Corvus Node interface

## Phase 2: Core Hypervisor — Complete
- Corvus Server skeleton
- Basic message routing
- Simple RBAC enforcement
- Audit logging foundation
- Management API v1
- Fake Node integration client

## Phase 3: Agent Runtime — Stabilized
- Firecracker microVM boot flow
- 4-engine model inside VM
- Corvus Node implementation
- Internal bus and validation
- TCP regression suite passing
- Firecracker launch/registry/stop smoke verified locally; Engine 4 memory turn validated in Phase 4.2; full multi-engine turn trace validated in Phase 5.1

## Phase 3.5: Control-Plane Hardening — Implemented
- Typed launch manifests and canonical manifest hashing
- Server-owned catalogs for tools, skills, LLM providers, workspaces, and memory namespace templates
- Per-VM launch package generation and identity/config injection
- Multi-VM lifecycle records with liveness, logs, errors, and session cleanup
- GUI-ready catalog, manifest, VM lifecycle, and health API surfaces

## Phase 3.6: RBAC Scope Alignment — Implemented
- Typed, schema-validated RBAC rules
- Rule CRUD, user aliases, grants, quotas, elevations, and RBAC audit API surfaces
- Channel identity assurance for CLI/API and chat aliases
- Live grant evaluation for `memory:*` policy gates
- Quota/elevation control-plane foundations
- RBAC audit/log correlation

## Pre-Phase-4: Memory Contract Cleanup — Implemented
- Canonical memory namespaces: `private` and `shared-knowledge`
- Canonical memory payload field: `target_agent_id` with transitional boundary alias support
- Per-agent namespace quota control-plane API/config and audit events
- Grant/elevation semantics clarified as RBAC grant evaluation plus agent retry

## Phase 4: Memory System — MVP Implemented
- Central Memory Service with SQLite-backed records
- Router dispatch for `memory:query`, `memory:write`, and `memory:delete`
- Namespace quota enforcement and memory operation audit events
- Key/list query support; semantic search deferred to sqlite-vec slice

## Phase 4.1: Engine 4 Client + E2E Validation — Implemented
- `MemoryEngine.serve()` during COLLECT (own-namespace write + key query per turn)
- `runtime/memory_client.py` message builders and response parsing
- `Coordinator.merge_fields()` for turn-scoped coordinator assertions
- Integration tests: Node IPC, full runtime turn, cross-agent grant, elevation path

## Phase 4.2: Firecracker In-VM Memory Smoke — Implemented
- `vm-smoke.sh` polls server DB for Engine 4 `turn-*` memory records after guest launch
- `src/corvus/vm/memory_wait.py` host-side wait helper
- Requires rebuilt rootfs (Phase 4.1 engine4 client baked in); skippable with `CORVUS_VM_SMOKE_SKIP_MEMORY=1`

## Phase 4.3: Semantic Search (sqlite-vec) — Implemented
- Deterministic hash embeddings indexed on write via sqlite-vec `memory_embeddings` vec0 table
- `memory:query` with `query_type: semantic` and `query.text`

## Phase 4.4: TTL Retention Sweeper — Implemented
- Background sweeper purges expired records and hard-deletes soft-deleted records after 24h
- Config: `CORVUS_MEMORY_SWEEP_INTERVAL_SECONDS` (default 900), `CORVUS_MEMORY_SOFT_DELETE_RETENTION_HOURS` (default 24)

## Phase 4.5: Elevation Auto-Retry — Implemented
- Server replays approved memory operations with new grants via `ElevationReplayService`
- Delivers `memory:*_response` and `memory:grant_created` to connected agents over active transport
- `memory:grant_request` supports `pending_replay` for chained grant + operation replay

## Phase 5.1: Full Turn + Correlation Traceability — Implemented
- `origin_correlation_id` column on audit log; query by turn root via Management API
- SQLite-backed `turn_state` table for `CorrelationStore` (survives server restart)
- Correlation edge-case tests (invalid, expired, max depth, persistence)
- TCP turn-trace integration test (user_query → memory hops auditable)
- Firecracker full-turn smoke waiter (`wait_vm_full_turn.py`)

## Phase 5.2: Elevation Workflows — Implemented
- SQLite `pending_replay` queue for offline elevation replay delivery on agent reconnect
- `ElevationSweeper` expires pending elevations (1h default TTL)
- `elevation_pending` audit events + optional `CORVUS_ELEVATION_WEBHOOK_URL`
- Management API approve guard for expired elevations; `pending_replay_queued` response field
- Node IPC buffers server-push until engine subscribe (reconnect replay path)

## Phase 5.3: Behavioral Monitoring — Implemented
- `BehavioralMonitor` with SQLite `behavioral_counters` (restart-safe sliding windows)
- Live `behavioral_signals` in policy facts: rate anomaly z-score, cross-agent grant denials, scope spike
- Default deny/elevate safety rules wired into `default_rules.yaml`
- Exit gate: 5th cross-agent grant failure denied by `deny-repeated-grant-denials`

## Phase 5.4: Production Hardening — Implemented
- Per-agent daily memory write quota metering on successful `memory:write`
- Optional AES-GCM memory encryption at rest (`CORVUS_MEMORY_ENCRYPTION`, `CORVUS_MASTER_KEY`)
- Health API ops metrics: sweeper liveness, pending replay depth, behavioral counter freshness
- Restart persistence verified for quota counters, pending replay, and behavioral state

## Phase 5: Advanced Features — Complete

## Phase 6: Tooling & Operations — Complete
- Policy fixture CI runner (`corvus-policy-fixtures`, `config/policy_fixtures/`)
- Dev stack script (`tools/dev-stack.sh`) + Makefile targets + env example
- Structured JSON logging (`CORVUS_LOG_JSON=1`) and OpenAPI export (`tools/export-openapi.sh`)
- CI runs policy fixtures alongside pytest
- Docker deployment packaging (`deploy/docker-compose.yml`)
- Prometheus metrics endpoint (`GET /v1/metrics`)
- Operator runbook (`corvus-docs/docs/planning/OPERATIONS.md`)

## Phase 7: Product Backends

### Phase 7.1 — Server-Side LLM Gateway (implemented)
- `LlmGatewayService` with manifest/registry gates, stub + OpenAI-compatible adapters
- Credentials via `env:` / `file:` refs on server; catalog API redacts secrets
- Engine 3 `llm_client.py`; server-origin `llm_response` only
- Audit `llm_completion`; quota increment on successful completions

### Phase 7.2 — Server-Side LLM Streaming (implemented)
- `llm_request` with `stream: true`; sync ack `llm_stream_start`; chunks via `llm_stream_chunk`; final `llm_response`
- Stub + OpenAI-compatible SSE adapters; transport push on active agent connection
- Opt-in runtime via `CORVUS_LLM_STREAM=1` in Engine 3

### Phase 7.2b — Streaming + tool_calls (implemented)
- Streaming now supports local-mode `tools_schema`: gateway accepts `stream` + local tools
- Provider adapters surface `tool_calls` from streams: stub emits a terminal completion with deterministic tool calls; OpenAI-compat assembles `delta.tool_calls` fragments across SSE chunks
- Engine 3 streams even when a tools schema is present and drives the Engine 1 tool loop from the final streamed `llm_response`; `collect_llm_stream` preserves `tool_calls`/`finish_reason`

### Default agent capabilities (implemented)
- Empty launch manifest → chat-only: `user_query` → stub LLM → `agent_response`; no tools, skills, or memory namespaces required
- Opt-in full stack: manifest tools/memory/skills + `corvus-runtime --all-engines` + `CORVUS_LLM_LOCAL_TOOLS`

### Phase 7.2+ — Streaming + provider-hosted (hybrid) tools (implemented)
- Gateway accepts `stream: true` with hybrid `provider_tools` / hosted tool forwarding (no `LLM_STREAM_TOOLS_UNSUPPORTED`)
- Stub stream path mirrors non-stream hosted-tool completions (`provider_tools_used`)
- `finalize_stream` audit parity with non-stream hybrid (`provider_tool_invocation`, opaque detection, `trust_boundary`)

### Phase 7.3 — Engine 1 Tool Loop (implemented)
- `corvus.tools.echo` + `run_tool()` runner
- Engine 1 COLLECT: `tool_call` → server RBAC → local execute → `tool_result` → server RBAC
- `runtime/tool_client.py`; full turn validates `tool_echo_text` in coordinator

### Phase 7.4 — Tool Execution Policy (implemented)
- **Local mode (default):** LLM `tool_calls` executed in VM via Engine 1 after server RBAC; gateway filters `tools_schema` to manifest allowlist
- **Hybrid mode (opt-in):** manifest `engine3.tool_execution_mode: hybrid` + `provider_tools` + provider registry `hosted_tools_allowed`
- Engine 3 ↔ Engine 1 coordination via coordinator `pending_tool_calls` / `tool_results`
- RBAC: hybrid LLM requests require admin role; audit `provider_tool_invocation` for provider-hosted tools

### Runtime turn-abort robustness (implemented)
- Terminal `ABORTED` coordinator phase + `abort(reason)`, `await_phase_in`, `is_terminal`; `DONE`/`ABORTED` are the two terminal phases
- Engines 2/3 abort on every failure path (timeouts, LLM failure, tool-batch timeout, max iterations, `user_query`/`agent_response` failures); Engine 2 waits for RESPOND-or-terminal
- Engine 1 COLLECT loop is bounded (turn deadline + stop event) and terminal-aware — no more infinite spin
- Agent Loop awaits `DONE`-or-`ABORTED` bounded by `CORVUS_TURN_TIMEOUT_SECONDS` (default 120s) and aborts on timeout
- Supervisor `--once` is loop-authoritative: engines are stopped and cancelled after the turn resolves, so a stalled engine can't hang the runtime (makes concurrent multi-agent runs reliable)
- Follows the earlier race-safe quota-counter fix (`INSERT ... ON CONFLICT DO NOTHING`)

## Phase 8: Operator Console — Implemented
- Server-rendered operator GUI mounted on the Management API (`/ui`), organized around a persistent left sidebar: Summary, Agents, Tools & Skills, Inference, Memory, Users & Access, Security, Audit, System
- Zero-build stack: Jinja2 + HTMX (dashboard polling, live rule simulator) + Alpine.js, all vendored (no CDN)
- Presentation layer only: UI handlers call the server's own `/v1` endpoints in-process (httpx `ASGITransport` + server-held API key), reusing all validation and audit
- Full read/write for API-mutable resources (agents launch/stop + create, namespace quotas, RBAC rules CRUD + simulator, grants, elevations approve/deny, quotas, users); Phase 8 left remaining knobs env-only (superseded by Phase 9)
- Signed HttpOnly session cookie login against admin/operator username + PIN/password; secrets redacted on the System page; toggles via `CORVUS_UI_ENABLED`, `CORVUS_UI_SESSION_SECRET`, `CORVUS_UI_PATH_PREFIX`

## Phase 9: GUI Full Configurability — Implemented
- **Product rule:** mutable control-plane state is editable in the GUI; informational/secret/restart_required taxonomy in OPERATIONS.md
- **9.0** Inventory & UX contract (docs/roadmap)
- **9.1** UI gaps on existing APIs (full agent create, elevation `create_grant`, user aliases/detail edit, audit `from`/`to`, inference quota redirect)
- **9.2** `PATCH /v1/agents/{id}`, user PATCH/DELETE (deactivate), groups CRUD
- **9.3** SQLite-backed catalog CRUD + Tools/Memory editors; Memory Service binds live `CatalogStore`
- **9.4** `server_settings` + `/v1/settings`, LLM provider CRUD/reload, System/Inference/Memory/Security edit forms; bind changes require operator restart (no UI auto-kill)

## Phase 9.5: Operator Console UX polish — Implemented
- Operator-facing labels, page leads, confirmations, catalog-backed dropdowns, hash-tab highlighting; JSON editors remain primary
- Sidebar taxonomy badges removed; login/docs match username + PIN/password
- Agent create applies self launch grants from namespace permissions when launch-grants JSON is empty

**Black Rain Labs - Research & Development Division**

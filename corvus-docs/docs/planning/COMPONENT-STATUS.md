**Document:** COMPONENT-STATUS.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** CHANGES.md
**Must Update on Change:** CHANGES.md

# Component Status

## Architecture Documents

| Component                    | Status                    | Notes |
|-----------------------------|---------------------------|-------|
| Overview                    | Implemented — Current     | Core principles authoritative |
| Hypervisor Architecture     | Implemented — Current     | Subsystems aligned with RBAC, Memory, Protocol |
| FrameworkMessage Protocol   | Implemented — Current     | Payload schemas, correlation, handshake, errors |
| RBAC & Policy               | Phase 5.4 Implemented   | Typed rules, aliases, grants, quota metering, elevations, audit, behavioral monitoring, optional memory encryption |
| Agent VM Architecture       | Implemented — Current     | 4-engine model + launch manifest |
| Agent Workflow Rules        | Current                 | Elevation + behavioral workflow sections finalized |
| Corvus Node                 | Implemented — Current     | IPC contract, routing, error catalog |
| Memory Architecture         | Phase 5.2 Implemented   | SQLite + sqlite-vec semantic search, key/list/delete, quota enforcement, TTL sweeper, elevation auto-replay, offline pending replay queue |
| Management API              | Phase 9.6 Implemented   | Agents/users/groups PATCH; catalog CRUD; `/v1/settings`; `/v1/agents/{id}/chat`; health/metrics/audit |
| LLM Gateway                 | Phase 7.2+ Implemented  | Server-side proxy, streaming (local tool_calls + hybrid hosted tools), local/hybrid tool policy, provider registry (SQLite + reload) |
| Operator Console            | Phase 9.6 Implemented   | Sidebar GUI + Chat playground; catalogs/settings/providers editable (DB-backed); operator UX polish; informational surfaces remain read-only |

**Phase 1 (Architecture & Design): Complete.**

## Implementation

| Component             | Status      | Notes |
|-----------------------|-------------|-------|
| Corvus Server         | Phase 2 Done (multi-VM session routing hardened) | AF_VSOCK/TCP gateway, handshake, routing, RBAC v1, audit; session binding + all server-initiated delivery and offline replay scoped to `(agent_id, vm_id)` so multiple VMs of one agent no longer collide |
| corvus.protocol       | Phase 2 Done| Pydantic models, NDJSON codec, error catalog |
| Management API        | Phase 9.6 Done | agents/users/groups CRUD+PATCH, catalog writes, `/v1/settings`, `/v1/agents/{id}/chat`, rules, simulate, audit, health, `/v1/metrics`, OpenAPI |
| Operator Console      | Phase 9.6 Done | `/ui` sidebar GUI + Chat; DB-backed catalogs/settings/providers editable; operator UX polish; secrets redacted; restart_required bind knobs |
| Fake Node client      | Phase 2 Done| `corvus-fake-node` CLI for integration testing |
| Corvus Node           | Phase 3 Stabilized| IPC socket, validation, handshake, routing, reconnect, `corvus-node` CLI |
| Agent Runtime         | Phase 4.1 Implemented (turn-abort hardened) | Loop + 4 engines; Engine 4 memory client during COLLECT; Engine 3 server LLM client; terminal `ABORTED` phase + bounded engine waits + loop-authoritative `--once` teardown so stalled/failed turns never hang; `corvus-loop`, `corvus-engine`, `corvus-runtime` |
| LLM Gateway           | Phase 7.2+ Done     | Streaming (local tool_calls + hybrid hosted tools) + local/hybrid tool execution policy, Engine 3→1 coordinator loop |
| Tool Gateway          | Phase 7.3 Done      | RBAC + manifest approval; VM-local execution only |
| Engine 4 Memory Client | MVP Implemented | Own-namespace write/query via Node IPC; cross-agent + elevation covered in integration tests |
| Memory Service        | MVP Implemented | SQLite records, router dispatch, quota enforcement, audit |
| Firecracker Integration | Phase 4.2 Hardened| Launch/registry/stop smoke + Engine 4 memory turn DB validation in `vm-smoke.sh` |
| Control-Plane Hardening | Phase 3.5 Implemented | Typed manifests, server-owned catalogs, per-VM config injection, VM health/lifecycle APIs |
| RBAC Scope Alignment | Phase 3.6 Implemented | Schema-validated rules, channel aliases, live grants, quota/elevation foundations, audit filters |
| Memory Contract Cleanup | Pre-Phase-4 Implemented | Canonical namespaces, `target_agent_id` payloads, namespace quota config, grant/elevation semantics |

**Phase 3.5 (Control-Plane Hardening): Implemented.** The server now owns capability catalogs and resolves typed launch manifests before persistence or VM launch. VM records expose lifecycle, liveness, launch logs, errors, per-VM package paths, and session cleanup state through API surfaces suitable for future GUI clients.

**Phase 4 MVP Gate:** Memory Service MVP is implemented with SQLite record storage, router dispatch, namespace quota enforcement, and memory audit events.

**Phase 4.1 Gate:** Engine 4 client and TCP full-turn memory validation are implemented.

**Phase 4.5 Gate:** Elevation approval auto-replays memory operations and notifies Engine 4 when the agent transport is connected.

**Phase 5.1 Gate:** Turn-root audit linkage via `origin_correlation_id`, SQLite-backed correlation store, correlation edge-case tests, TCP turn-trace integration, and Firecracker full-turn smoke waiter.

**RBAC Gate:** Re-checked after Phase 3.6. RBAC grant evaluation, channel identity assurance, rule validation, quota/elevation foundations, and auditable API surfaces remain aligned with Memory Service enforcement.

**Phase 6 Gate:** Policy fixture CI, dev stack tooling, Docker server packaging, Prometheus metrics, operator runbook (`OPERATIONS.md`), OpenAPI export.

**Phase 7.1 Gate:** Server-side LLM gateway; Engine 3 receives `llm_response` from server; credentials never exposed to VM; catalog API redacts provider secrets; audit + quota metering on completions.

**Phase 7.2 Gate:** LLM streaming with `llm_stream_start` sync ack, `llm_stream_chunk` transport push, final `llm_response`; stub + OpenAI SSE adapters. Local/hybrid tool coexistence covered by Phase 7.2b / 7.2+.

**Phase 7.4 Gate:** Tool execution policy (local default, hybrid opt-in); gateway `tools_schema` filtering; Engine 3 LLM tool loop via coordinator; provider-hosted tool audit warnings.

**Phase 7.2b Gate:** Streaming coexists with local-mode tool_calls; provider adapters surface `tool_calls` from streams; Engine 3 drives the Engine 1 tool loop from streamed responses.

**Phase 7.2+ Gate:** Streaming coexists with hybrid provider-hosted tools; gateway forwards registry-approved hosted tools on stream requests; stub/OpenAI adapters and `finalize_stream` record `provider_tools_used` / `trust_boundary` with hybrid audit parity.

**Phase 8 Gate:** Operator console at `/ui` renders every sidebar category; login gates all pages via signed cookie; API-mutable resources are editable through the console (reusing `/v1` validation + audit); System page redacts secrets; 17 UI tests plus full-suite green.

**Phase 9 Gate:** DB-backed catalogs + runtime settings + LLM provider registry editable via GUI/`/v1`; env/YAML bootstrap + break-glass only; bind host/port/transport marked restart_required (no UI auto-restart); health/metrics/audit bodies/resolved manifest remain informational.

**Phase 9.5 Gate:** Operator Console pages use human labels, confirmations, catalog dropdowns, and hash-tab highlighting; JSON editors remain the day-2 control surface; login/docs describe username + PIN/password.

**Phase 9.6 Gate:** Operator Chat at `/ui/chat` uses `POST /v1/agents/{id}/chat` through the LLM gateway (stub/dummy test providers); `make dev-up` starts dummy LLM; Engine 2 `CORVUS_CHAT_TEXT` for runtime turns.

**Black Rain Labs - Research & Development Division**

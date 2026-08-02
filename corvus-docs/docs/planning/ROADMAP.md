**Document:** ROADMAP.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-02
**Related Documents:** CHANGES.md
**Must Update on Change:** CHANGES.md

# Corvus Roadmap

## Near Term (Next 1-2 Months)
- ~~Complete core architecture documents~~ (Phase 1 done)
- ~~Prototype Corvus Server message routing~~ (Phase 2 done)
- ~~Implement Corvus Node + Firecracker smoke test~~ (Phase 3 stabilized)
- ~~Harden control plane before Memory~~ (Phase 3.5 implemented)
- ~~Memory Service foundation (Phase 4 start; gated on typed namespace/grant/quota contracts)~~ Phase 4 MVP implemented
- ~~Engine 4 client + TCP memory turn validation (Phase 4.1)~~ implemented
- ~~Firecracker in-VM memory smoke (Phase 4.2)~~ implemented
- ~~Phase 4 memory core (4.3–4.5 semantic search, TTL sweeper, elevation auto-replay)~~ implemented
- ~~Phase 5.1 full turn + correlation traceability (audit linkage, Firecracker full-turn smoke)~~ implemented
- ~~Phase 5 advanced features (elevation workflows, behavioral monitoring, production hardening)~~ implemented
- ~~Phase 6 tooling & operations (policy fixture CI, dev stack, Docker deploy, metrics, operator docs)~~ implemented
- ~~Phase 7.1–7.4 product backends (LLM gateway, Engine 1 tools, tool execution policy)~~ implemented
- ~~Phase 7.2 LLM streaming (`llm_stream_start` / `llm_stream_chunk`)~~ implemented
- ~~Phase 7.2b streaming + local tool_calls~~ implemented
- ~~Runtime turn-abort robustness (terminal `ABORTED` phase, bounded engine waits, loop-authoritative `--once` teardown, race-safe quota counter) so stalled/failed and concurrent multi-agent turns never hang~~ implemented
- ~~Phase 8 operator console (sidebar-driven GUI over the Management API)~~ implemented
- ~~Phase 7.2+ streaming + provider-hosted (hybrid) tools~~ implemented
- ~~Hygiene: CI-green ruff, refreshed editable install, OpenAPI export prefers `.venv`~~ implemented
- ~~Implement behavioral `tool_pattern_deviation` (tool-call rate z-score)~~ implemented
- ~~Management API rate limiting (100 req/min default) + harden elevation webhook (HMAC + tests)~~ implemented
- ~~Expand Engine 1 tool surface: registry-driven runner + `file_read` (skills/workspace mounts deferred)~~ implemented
- Skill runtime beyond catalog placeholders; Firecracker workspace drive mounts (next)

## Medium Term (3-6 Months)
- Skill runtime beyond catalog placeholders; Firecracker workspace drive mounts
- Fuller audit-event webhook taxonomy beyond elevation
- Production Firecracker ops discipline (rootfs rebuild cadence, self-hosted smoke, kvm group persistence)
- Additional catalog tools beyond echo/terminal/`file_read`

## Longer Term
- Multi-host / multi-control-plane scaling beyond single-node SQLite coordinator state
- Richer observability (per-agent SLO dashboards, anomaly playbooks)
- Broader provider adapters and hosted-tool coverage under hybrid streaming
- Hardened supply-chain and artifact provenance for rootfs/kernel builds

**Black Rain Labs - Research & Development Division**

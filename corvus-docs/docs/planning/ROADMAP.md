**Document:** ROADMAP.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** CHANGES.md, PHASES.md, PHASE-10-SKILLS.md
**Must Update on Change:** CHANGES.md

# Corvus Roadmap

## Near Term (Next 1-2 Months) — ordered

1. **Phase 10 — Secure skill runtime + open library** — Engine 1 skill tools; gated Agent Skills (`SKILL.md`) install from allowlisted sources; launch bake. See [PHASE-10-SKILLS.md](PHASE-10-SKILLS.md).
2. **Phase 11 — Firecracker workspace mounts** — Honor manifest `workspaces` as secondary drives (`vm/spec.py`, `vm/launcher.py`); GUI already assigns mounts.
3. **Phase 12 — Tool + ops depth** — Additional catalog tools beyond echo/terminal/`file_read`; fuller audit-event webhook taxonomy; FC ops cadence / optional self-hosted smoke.

## Medium Term (3-6 Months)

- Pluggable / higher-quality embeddings (replace hash bag-of-words)
- Live OpenAI-compatible hybrid/stream soak beyond stub parity
- Settings vs env break-glass operator matrix hardening (docs + UX clarity)
- Production Firecracker ops discipline (rootfs rebuild cadence, kvm group persistence)

## Longer Term

- Multi-host / multi-control-plane scaling beyond single-node SQLite coordinator state
- Richer observability (per-agent SLO dashboards, anomaly playbooks)
- Broader provider adapters and hosted-tool coverage under hybrid streaming
- Hardened supply-chain and artifact provenance for rootfs/kernel builds
- OAuth2, live bus inspector, RBAC condition plugins (explicitly deferred)

Completed Phases 1–9 (through GUI full configurability and operator chat) are recorded in [PHASES.md](PHASES.md) and [CHANGES.md](../../../CHANGES.md). Post–Phase 9 baseline (intentional thin spots + do-not-reopen) lives in PHASES.md.

**Black Rain Labs - Research & Development Division**

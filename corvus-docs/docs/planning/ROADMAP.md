**Document:** ROADMAP.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-27
**Related Documents:** CHANGES.md, PHASES.md, PHASE-10-SKILLS.md
**Must Update on Change:** CHANGES.md

# Corvus Roadmap

## Product split

| Now | Later |
|-----|-------|
| **Corvus-Node** — host Node, four engines in one Firecracker guest, vsock, RBAC. New repo, from scratch. | This hypervisor as the **central control plane / fleet dash** for many Corvus-Node instances |
| One-turn slice, then workspace mounts + memory, then real LLM | Fleet routing, grants, catalogs, Operator Console as dash |

Do not add fleet/hypervisor features here as the next slice. Use this tree as a **read-only reference** for protocol, Node, engines, policy, audit, LLM gateway, and memory when building Corvus-Node.

## Near Term (Next 1-2 Months) — ordered

1. **Corvus-Node** — New repository. One agent identity. 4-engine workflow, deterministic RBAC, audit of every hop, Engine 3 never calls tools or memory. First shippable: Firecracker guest over vsock, `user_query` → stub LLM → optional Engine 1 `echo` after RBAC → audit → response.
2. **Corvus-Node — memory + real tools** — Node-owned `private` namespace; workspace mounts; terminal / file_read; then skills.
3. **Corvus-Node — production rootfs** — Bake the guest image; keep vsock-only (no TCP product mode).

## Medium Term (3-6 Months)

- Revisit this hypervisor as the supervisor dash (Operator Console already themed) once a single Corvus-Node instance is useful
- Pluggable / higher-quality embeddings (replace hash bag-of-words) when memory returns to the control plane
- Production Firecracker ops discipline (rootfs rebuild cadence, kvm group persistence)

## Longer Term

- Multi-host / multi-control-plane scaling
- Richer observability (per-agent SLO dashboards, anomaly playbooks)
- Fleet grants, elevations, and catalogs — only after Corvus-Node is the agent runtime
- OAuth2, live bus inspector, RBAC condition plugins (explicitly deferred)

## Frozen here (not the next slice)

Phase 11 Firecracker workspace mounts and Phase 12 catalog-tool/ops depth stay **deferred** in this repo. Completed Phases 1–10d (through skill browse) remain recorded in [PHASES.md](PHASES.md) and [CHANGES.md](../../../CHANGES.md).

**Black Rain Labs - Research & Development Division**

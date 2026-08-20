**Document:** PHASE-10-SKILLS.md
**Status:** Draft — implementation plan (docs only until kickoff)
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** PHASES.md, ROADMAP.md, AGENT-WORKFLOW.md, OVERVIEW.md, CHANGES.md
**Must Update on Change:** CHANGES.md

# Phase 10 — Skill Runtime (implementation plan)

## Goal

Make catalog skills **executable** inside the agent microVM via Engine 1 after Corvus Server RBAC approval—without violating Core Principles (star topology; Engine 3 never calls tools/skills/memory directly; launch-time capability baking).

## Current baseline (inventory)

| Surface | State |
|---------|--------|
| Catalog | `SkillCatalogEntry` + default `base-runtime` in `server/catalog.py` |
| Manifest | `skills: list[str]` validated against catalog |
| GUI / API | Skills CRUD and agent skill selection |
| Runtime | **No** skill loader; Engine 1 only runs `TOOL_REGISTRY` tools (`echo`, `terminal`, `file_read`) |

## Invariants (non-negotiable)

1. Skills execute only in Engine 1 (or a subprocess Engine 1 owns), never from Engine 3.
2. Every skill invocation crosses the server as a mediated message (reuse `tool_call` / `tool_result` path or a sibling `skill_*` type with the same RBAC + audit pattern).
3. Only skills listed on the resolved launch manifest may run.
4. Prefer baking skill packages into rootfs / launch package at VM start (immutable rootfs).

## Proposed scope (MVP)

1. **Skill runner contract** — Define how a skill is invoked (name, args schema, timeout, stdout/structured result). Start with one builtin skill package that wraps an existing tool pattern (e.g. `base-runtime` exposes a no-op or echo-like health skill) to prove the loop.
2. **Engine 1 dispatch** — Extend Engine 1 (or coordinator batch types) so approved skill calls resolve via a `SKILL_REGISTRY` parallel to `TOOL_REGISTRY`, still after server allow.
3. **Server gates** — Manifest allowlist + catalog presence; audit events for skill allow/deny/execute (mirror `tool_operation`).
4. **Docs / rootfs** — Update AGENT-WORKFLOW, OPERATIONS; rebuild guest rootfs when skill packages are baked.
5. **Tests** — Unit registry + TCP integration turn that completes a skill call end-to-end.

## Explicit non-goals for Phase 10

- Firecracker secondary workspace mounts (Phase 11)
- Large new tool surface (Phase 12)
- Arbitrary untrusted skill download at runtime (supply-chain risk)
- Engine 3 direct skill invocation
- Version bump decision until MVP exit gate (then consider 0.9.0)

## Suggested exit gate

- At least one catalog skill runs through Engine 1 with server RBAC + audit on TCP path
- AGENT-WORKFLOW documents the skill path alongside tools
- Full suite green; no regression to local/hybrid tool policy
- CHANGES + PHASES mark Phase 10 MVP implemented

## Kickoff order

1. Lock message/schema choice (`tool_call` reuse vs `skill_call`) against PROTOCOL + RBAC docs
2. Implement registry + Engine 1 path with stub skill
3. Wire manifest/catalog checks and audit
4. Tests + docs + rootfs if required

**Black Rain Labs - Research & Development Division**

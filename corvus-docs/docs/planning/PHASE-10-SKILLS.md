**Document:** PHASE-10-SKILLS.md
**Status:** Active — Phase 10a–c implementation
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** PHASES.md, ROADMAP.md, AGENT-WORKFLOW.md, OVERVIEW.md, SECURITY.md, CHANGES.md
**Must Update on Change:** CHANGES.md

# Phase 10 — Secure Skill Runtime & Open Library

## Goal

1. Execute approved catalog skills inside the agent microVM via Engine 1 after Corvus Server RBAC.
2. Import [Agent Skills](https://agentskills.io) (`SKILL.md`) packages from **allowlisted** open sources into the server-owned skill catalog with admin review, pin, and hash — then **bake** them at launch.

## Trust model

- Skills are **untrusted** until an **admin** installs them into the catalog (control plane only).
- **No** guest/runtime fetch of skills mid-turn.
- `SKILL.md` body → instruction pack via mediated `skill_read` (Engine 1 after approval).
- Bundled `scripts/` → Engine 1 `skill_run` only when `allow_scripts=true` on the catalog entry.
- Engine 3 never calls skills/tools directly.

## Security controls

| Control | Behavior |
|---------|----------|
| Source allowlist | `CORVUS_SKILL_SOURCE_ALLOWLIST` (comma-separated URL prefixes). Empty = deny all remote installs. |
| Pin + hash | Install requires pin (tag/commit/version label) and **sha256** of the package bytes. |
| Validate | Strict `SKILL.md` frontmatter; reject traversal, symlinks, oversized trees. |
| Scripts | Default deny; admin opt-in `allow_scripts`. |
| Audit | `skill_install` / `skill_deny` via API mutation details; tool phases for `skill_read` / `skill_run`. |

## Sub-phases

| Gate | Criteria |
|------|----------|
| **10a** | Builtin `base-runtime` + `skill_read` / `skill_run` tools; catalog provenance fields |
| **10b** | `POST /v1/catalog/skills/install` dry-run + commit; Console install form |
| **10c** | Launch package `skills/` bake; adversarial import tests |

## Non-goals

- Auto-install without allowlist; guest mid-turn download; Engine 3 direct skill execution; marketplace UI; Phase 11 mounts / Phase 12 tools.

**Black Rain Labs - Research & Development Division**

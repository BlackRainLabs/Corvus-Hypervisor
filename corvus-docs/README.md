**Document:** README.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** docs/architecture/OVERVIEW.md, ../CHANGES.md, ../README.md
**Must Update on Change:** ../CHANGES.md

# Corvus Hypervisor

Corvus Hypervisor is a security-first, centrally mediated multi-agent hypervisor designed for high-assurance agentic systems. Agents run inside isolated Firecracker microVMs, and **every action** must pass through the Corvus Server for validation, policy enforcement, and auditing.

## Core Philosophy

- Everything crosses the Corvus Server
- No direct LLM-to-tool execution paths
- Every hop is auditable and traceable
- Deterministic, metadata-driven validation (no LLM inspection in the hypervisor)
- Launch-time capability baking with immutable rootfs
- Memory is centrally mediated with explicit grants

## Documentation Structure

- [Architecture Overview](docs/architecture/OVERVIEW.md)
- [Hypervisor Architecture](docs/architecture/hypervisor/ARCHITECTURE.md)
- [FrameworkMessage Protocol](docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md)
- [RBAC & Policy](docs/architecture/hypervisor/RBAC-POLICY.md)
- [Agent VM Architecture](docs/architecture/agent-vm/ARCHITECTURE.md)
- [Corvus Node](docs/architecture/agent-vm/CORVUS-NODE.md)
- [Memory Architecture](docs/architecture/memory/ARCHITECTURE.md)
- [Agent Workflow Rules](docs/architecture/agent-vm/AGENT-WORKFLOW.md)
- [Planning & Roadmap](docs/planning/)
- [Development Phases](docs/planning/PHASES.md)
- [Phase 10 — Skill Runtime plan](docs/planning/PHASE-10-SKILLS.md)
- [Operations Guide](docs/planning/OPERATIONS.md)
- [Component Status](docs/planning/COMPONENT-STATUS.md)

## Implementation

Phases 1–9 are implemented (architecture through operator console GUI configurability and chat). See the [repository root README](../README.md) for setup, `make dev-up`, Docker deploy, tests, and Firecracker smoke.

**Current phase:** Phase 9.6 complete (baseline closed). Next: Phase 10 skill runtime — see [PHASE-10-SKILLS.md](docs/planning/PHASE-10-SKILLS.md) and [ROADMAP.md](docs/planning/ROADMAP.md).

## Changelog

All changes are recorded in [CHANGES.md](../CHANGES.md) at the repository root.

## License

Apache 2.0 — see [LICENSE](../LICENSE).

**Black Rain Labs - Research & Development Division**

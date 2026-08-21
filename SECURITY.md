# Security Policy

## Supported versions

Corvus Hypervisor **v0.8.x** is an early public / research release. Security fixes are applied on a best-effort basis for the latest published tag on the default branch.

## Reporting a vulnerability

Please report security issues privately. Prefer opening a GitHub security advisory on this repository (or contacting Black Rain Labs through the channel listed on the project page) rather than filing a public issue with exploit details.

Include:

- Affected version / commit
- Description of the issue and impact
- Reproduction steps or a minimal proof of concept when possible

We will acknowledge receipt when we can and coordinate disclosure after a fix or mitigation is available.

## Important operational notes

Corvus is designed as a **security-first control plane**, but this release ships with **development defaults** that must not be used in production:

- Management API key defaults to `dev-api-key`
- Bootstrap PIN values are well-known development constants
- TCP transport (`CORVUS_USE_TCP=1`) is for local development and CI; production isolation expects AF_VSOCK + Firecracker on Linux with KVM

Before any real deployment:

1. Set strong, unique API keys and session secrets (`CORVUS_*` env vars — see `tools/corvus.env.example` and `OPERATIONS.md`)
2. Rotate bootstrap credentials and elevation webhook secrets
3. Prefer Firecracker / vsock over TCP
4. Treat agent workloads as untrusted; do not weaken star-topology or RBAC invariants
5. Keep LLM provider credentials on the server only (never inside guest VMs)
6. Treat **skills** like untrusted dependencies: install only from allowlisted sources with pin + sha256; review `SKILL.md` and scripts before approving; never enable `allow_scripts` without review; never fetch skills from inside the guest mid-turn (see `PHASE-10-SKILLS.md`)

## Skill library threat model (Phase 10)

| Threat | Mitigation |
|--------|------------|
| Malicious open-source skill (prompt injection / exfil) | Admin-only install; dry-run preview; deny-by-default source allowlist; pin + content hash |
| Path traversal / zip slip in package | Validated extract under content-addressed store; reject `..`, absolute paths, symlinks |
| Unreviewed script execution | `allow_scripts` defaults false; scripts run only via Engine 1 after RBAC |
| Supply-chain drift | Refuse floating `latest`; require sha256 match |
| Guest escape via skill network | Install fetch is server-side only; guest has no skill registry access |

## Scope

In scope: the Corvus Server, Node, protocol, policy engine, Management API / operator console, and related tooling in this repository.

Out of scope unless clearly caused by Corvus: third-party LLM providers, host kernel/KVM misconfiguration, and unmodified Firecracker / guest OS vulnerabilities.

**Black Rain Labs - Research & Development Division**

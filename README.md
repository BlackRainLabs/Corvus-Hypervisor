# Corvus Hypervisor

Security-first, centrally mediated multi-agent hypervisor for high-assurance agentic systems.

Corvus treats agents as potentially untrusted workloads. Every message and action crosses a single control plane—the **Corvus Server**—which enforces RBAC, audits every hop, and mediates tools, memory, and LLM access. Production isolation uses [Firecracker](https://firecracker-microvm.github.io/) microVMs; TCP mode supports local development and CI.

**Version:** 0.8.0 · **License:** [Apache 2.0](LICENSE) · **Org:** Black Rain Labs — Research & Development Division

## Why Corvus

Most agent stacks trust the runtime. Corvus does the opposite:

- **Star topology** — agents never talk to each other or the outside world directly
- **No LLM-to-tool bypass** — Engine 3 (inference) cannot call tools or memory without server validation
- **Deterministic policy** — structured RBAC, grants, quotas, and correlation IDs; no LLM-based semantic inspection in the control plane
- **Strong isolation** — one Firecracker microVM per agent, with a narrow Corvus Node interface

## Architecture

```
                        Operator
               (Console /ui · Management API)
                              |
                              v
  +------------------------- Host --------------------------+
  |   +-------------------+         +-------------------+   |
  |   |  Corvus Server    |-------> |  Memory Service   |   |
  |   |  RBAC · Audit     |         +-------------------+   |
  |   |  LLM Gateway      |                                 |
  |   +---------^---------+                                 |
  +-------------|-------------------------------------------+
                |
           AF_VSOCK / TCP
                |
  +-------------|------------- Agent MicroVM ---------------+
  |   +---------v---------+                                 |
  |   |   Corvus Node     |   sole VM exit / entry          |
  |   +--+----+----+----+-+                                 |
  |      |    |    |    |                                   |
  |     E1   E2   E3   E4                                   |
  |   Tools Chan LLM  Mem                                   |
  +---------------------------------------------------------+
```

| Layer | Role |
|-------|------|
| **Corvus Server** | Routing, RBAC, audit, elevation, LLM gateway, memory mediation |
| **Corvus Node** | In-VM gateway: IPC, validation, reconnect |
| **4 engines** | Tools, channels, LLM client, memory client — strict separation |
| **Management API + `/ui`** | Operators manage agents, policy, security, health, and chat |

Deep dive: [Architecture Overview](corvus-docs/docs/architecture/OVERVIEW.md)

## Status (v0.8.0)

Phases **1–9** are complete: protocol and control plane, Firecracker/Node path, memory service, elevation and behavioral monitoring, ops tooling and Docker, LLM gateway (streaming + hybrid tools), the operator console, and GUI full configurability with operator chat (Phase 9.6).

This is an early public release, not 1.0. Still ahead: skill runtime beyond catalog placeholders, Firecracker workspace mounts, a broader tool surface, multi-host scaling, and richer observability. See [ROADMAP](corvus-docs/docs/planning/ROADMAP.md) and [COMPONENT-STATUS](corvus-docs/docs/planning/COMPONENT-STATUS.md).

## Requirements

- Python **≥ 3.12**
- Linux (recommended)
- Optional for production VMs: KVM, `/dev/vsock`, Docker (rootfs build), Firecracker

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

make test          # pytest (TCP path)
make fixtures      # RBAC policy regression suite
make lint
```

Copy and adjust [`tools/corvus.env.example`](tools/corvus.env.example) as needed.

### Dev stack (TCP)

```bash
make dev-up
make run-turn      # one agent turn (all engines)
make dev-down
```

| Surface | URL / note |
|---------|------------|
| Management API | `http://127.0.0.1:8080` · header `X-API-Key: dev-api-key` |
| Operator Console | `http://127.0.0.1:8080/ui` · sign in `admin-user` / `0000` |
| Chat | `http://127.0.0.1:8080/ui/chat` · seeded `test-agent-01` uses stub LLM |
| OpenAPI | `http://127.0.0.1:8080/docs` (while server is running) |

```bash
make openapi       # export openapi.json offline
```

### Docker (server only)

```bash
make docker-build && make docker-up
curl -H "X-API-Key: dev-api-key" http://127.0.0.1:8080/v1/health
```

See [`deploy/README.md`](deploy/README.md).

### Firecracker (production transport)

```bash
bash tools/rootfs/fetch-kernel.sh
bash tools/rootfs/build.sh
export CORVUS_USE_TCP=0
bash tools/vm-smoke.sh
```

Details: [FIRECRACKER.md](corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md) and [OPERATIONS.md](corvus-docs/docs/planning/OPERATIONS.md).

## Documentation

| Doc | Purpose |
|-----|---------|
| [OVERVIEW](corvus-docs/docs/architecture/OVERVIEW.md) | Core principles and invariants |
| [MANAGEMENT-API](corvus-docs/docs/architecture/hypervisor/MANAGEMENT-API.md) | HTTP API and Operator Console contract |
| [OPERATIONS](corvus-docs/docs/planning/OPERATIONS.md) | Dev stack, Docker, metrics, fixtures |
| [COMPONENT-STATUS](corvus-docs/docs/planning/COMPONENT-STATUS.md) | What is implemented |
| [FrameworkMessage Protocol](corvus-docs/docs/architecture/hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md) | Wire protocol |
| [FIRECRACKER](corvus-docs/docs/architecture/agent-vm/FIRECRACKER.md) | MicroVM path |
| [CHANGES](CHANGES.md) | Changelog |
| [AGENTS](AGENTS.md) | Notes for AI coding agents |
| [CONTRIBUTING](CONTRIBUTING.md) | Contribution guidelines |

## Security

Default API key (`dev-api-key`) and bootstrap PINs are **development defaults only**. Do not use them in production. Rotate keys, pins, and webhook secrets; prefer AF_VSOCK over TCP for real deployments.

See [SECURITY.md](SECURITY.md) for reporting and hardening expectations.

## License

Licensed under the Apache License, Version 2.0 — see [LICENSE](LICENSE).

**Black Rain Labs - Research & Development Division**

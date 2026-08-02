---
**Document:** agent-vm/ARCHITECTURE.md
**Status:** Implemented — Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-07-05
**Related Documents:** OVERVIEW.md, hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md, agent-vm/CORVUS-NODE.md, agent-vm/AGENT-WORKFLOW.md, CHANGES.md
**Must Update on Change:** CHANGES.md
**AI Instruction:** When revising this document, review Core Principles & Invariants in OVERVIEW.md, update CHANGES.md, and ensure consistency with related documents. Do not contradict core fundamentals.
---

# Agent VM Architecture

**Status:** Implemented — Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division

## Overview

Each agent runs inside its own Firecracker microVM with a read-only rootfs. The internal architecture follows a strict **4-engine model** with strong separation of concerns and no direct cross-engine communication.

## 4-Engine Model (Detailed)

| Engine | Name                    | Responsibility                                                                 | Trust Level | Key Constraints |
|--------|-------------------------|--------------------------------------------------------------------------------|-------------|-----------------|
| **1**  | Tools & Skills          | Local tool execution (filesystem, shell, web, custom skills)                   | Untrusted   | Only local execution. Never performs memory or external actions directly. |
| **2**  | Gateway / Channels      | External message formatting, platform-specific handling, session state         | Untrusted   | Only communicates via Corvus Node. Formats responses for external platforms. |
| **3**  | LLM / Inference         | LLM provider calls, reasoning, tool schema generation, multi-turn logic        | Untrusted   | Cannot directly call tools or memory. Must go through bus + Corvus Server. |
| **4**  | Memory                  | Initiates all memory operations (query, write, etc.)                           | Untrusted   | Only engine allowed to emit `memory:*` messages. All operations mediated by Corvus Server. |

## Communication Rules (Strict)

- Engines communicate **only** via the internal bus.
- No direct engine-to-engine communication is allowed.
- No direct engine-to-Agent Loop communication after initial dispatch.
- All outbound traffic must go through the **Corvus Node**.
- All results and side effects flow back through the **Corvus Server** for validation and auditing.

## Agent Loop (Kernel.py)

Lightweight state machine responsible for:
- Turn lifecycle management (INIT → RECEIVE → DISPATCH → COLLECT → RESPOND → DONE)
- Dispatching work to the internal bus
- Not acting as a central message router between engines

## Corvus Node (Local Validation)

The Corvus Node is the sole external interface of the microVM. It performs local structural validation (engine origin, capability tags, correlation presence) before messages leave the VM or after they arrive from the Corvus Server. See [CORVUS-NODE.md](CORVUS-NODE.md) for the full interface contract.

## Launch Manifest

Capabilities are declared at launch and baked into the immutable rootfs. The manifest schema is defined in [MANAGEMENT-API.md](../hypervisor/MANAGEMENT-API.md) (`POST /v1/agents`).

**Key manifest sections:**
- `engines.engine1.tools` — allowed tool names (must exist in rootfs)
- `skills` — server-owned skill catalog IDs selected for launch
- `workspaces` — server-owned workspace mounts selected for launch
- `engines.engine3.allowed_providers/models` — LLM constraints enforced by RBAC
- `engines.engine3.tool_execution_mode` — `local` (default) or `hybrid` (opt-in provider-hosted tools)
- `engines.engine3.provider_tools` — hybrid only; entries like `openai:web_search`
- `engines.engine4.namespaces` — memory namespaces available to the agent
- `launch_grants` — pre-approved cross-agent memory grants (see [memory/ARCHITECTURE.md](../memory/ARCHITECTURE.md))

Corvus Server owns the tool, skill, LLM provider, workspace, and memory namespace catalogs. Agent manifests select catalog entries; the server resolves and canonicalizes the manifest before storing it, hashing it, packaging it for launch, and attesting it during Corvus Node handshake. Runtime changes to baked capabilities require a new microVM launch.

## Rootfs Immutability

Tools, skills, and engine capabilities are selected at launch time in the manifest and baked into the read-only rootfs. Any change to capabilities requires a new microVM launch.


---
**Black Rain Labs - Research & Development Division**

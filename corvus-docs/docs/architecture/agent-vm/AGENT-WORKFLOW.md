**Document:** AGENT-WORKFLOW.md
**Status:** Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-08-20
**Related Documents:** agent-vm/ARCHITECTURE.md, agent-vm/CORVUS-NODE.md, hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md, OVERVIEW.md, CHANGES.md
**Must Update on Change:** CHANGES.md
**AI Instruction:** When revising this document, review Core Principles & Invariants in OVERVIEW.md, ensure strict adherence to the 4-Engine Model and Corvus Node mediation rules. Update CHANGES.md.

# Agent Workflow Rules

## Purpose

This document defines the **mandatory workflow rules** that every agent running inside a Corvus microVM must follow. These rules enforce security, isolation, auditability, and correct separation of concerns.

All agents are considered potentially untrusted. The rules below are enforced through a combination of:

- Architectural design (4-Engine Model + internal bus)
- Corvus Node local validation
- Corvus Server authoritative validation and policy enforcement

## Core Workflow Principles

1. **All external actions are mediated** — No direct tool calls, memory access, or external communication from Engine 3 (LLM).
2. **Strict engine separation** — Engines communicate **only** via the internal bus. No direct engine-to-engine calls.
3. **Corvus Node is the sole exit point** — Every outbound message must pass through the Corvus Node for local structural validation before leaving the VM.
4. **Deterministic validation first** — Validation is based on metadata, correlation chains, capability tags, and origin enforcement — never on LLM semantic judgment inside the hypervisor.
5. **Full traceability** — Every action must carry a valid correlation chain back to user intent or system trigger.

## Agent Turn Lifecycle (Agent Loop)

The Agent Loop acts as a lightweight state machine with the following mandatory phases:

| Phase     | Description                                                                 | Allowed Actions |
|-----------|-----------------------------------------------------------------------------|-----------------|
| **INIT**      | VM boot, handshake with Corvus Server via Corvus Node                      | System handshake only |
| **RECEIVE**   | Receive inbound message from Corvus Server (via Corvus Node)               | Validate origin & correlation |
| **DISPATCH**  | Route work to the appropriate engine(s) via internal bus                   | Only to correct engine based on message type |
| **COLLECT**   | Gather results from engines                                                | Enforce engine separation rules |
| **RESPOND**   | Format and send response outward through Corvus Node                       | Must include valid correlation ID |
| **DONE**      | Turn complete, state cleanup                                               | Prepare for next turn |
| **ABORTED**   | Terminal failure state — a turn that failed or stalled is torn down safely | No further engine work; runtime exits |

`DONE` and `ABORTED` are the two **terminal** phases; every turn ends in exactly one of them.

**Rules:**
- The Agent Loop **must not** act as a central message router between engines after initial dispatch.
- Engines must not communicate directly with each other or with the Agent Loop after dispatch.
- All side effects (tool calls, memory operations, external messages) must flow back through the Corvus Server for validation.

**Turn-abort robustness:**
- Any engine that fails or times out (LLM failure, tool-batch timeout, max tool iterations, dispatch/collect/respond timeouts, or a rejected `user_query`/`agent_response`) moves the turn to the terminal `ABORTED` phase via the coordinator's idempotent `abort(reason)`.
- Engines waiting on a phase (e.g. Engine 1's COLLECT loop, Engine 2's wait for RESPOND) treat any terminal phase as a stop signal and exit promptly instead of waiting out their individual timeouts.
- The Agent Loop awaits `DONE`-or-`ABORTED` bounded by `CORVUS_TURN_TIMEOUT_SECONDS` (default 120s); on timeout it aborts the turn itself. (Server-side correlation uses a separate knob, `CORVUS_TURN_TIMEOUT`, default 300s — see OPERATIONS.md.)
- Engine 1's COLLECT loop is bounded by the same turn deadline and honors a stop request, so a stalled turn can never spin an engine forever.
- Under `--once`, the supervisor is loop-authoritative: once the loop resolves the turn it stops the engines and, after a short grace window for in-flight IPC, cancels any stragglers — a stalled engine cannot hang the runtime. This is what keeps concurrent multi-agent runs reliable.

## Engine-Specific Workflow Rules

### Engine 1 – Tools & Skills
- May only execute tools/skills that were baked into the immutable rootfs at launch **and** listed in the agent manifest.
- Must send `tool_call` through Corvus Node → Corvus Server; **must not execute** until inbound `tool_call_response` has `approved: true`.
- Execution is **local to the agent VM** (e.g. `terminal`, `echo`); the server never runs tool code.
- Must report outcomes via `tool_result` back through the server for audit.

### Engine 2 – Gateway / Channels
- Responsible for platform-specific formatting of responses.
- May only communicate externally via the Corvus Node.
- Maintains session state for external platforms (e.g., chat sessions).

### Engine 3 – LLM / Inference (Highly Restricted)
- **Cannot directly**:
  - Call tools
  - Access memory
  - Send messages outside the VM
  - Hold LLM provider API keys or base URLs (server gateway resolves credentials)
- Must request inference by emitting `llm_request` on the internal bus; the server returns `llm_response` inbound.
- All tool use and memory access must be mediated by the Corvus Server after correlation validation.
- When `llm_response` includes `tool_calls`, Engine 3 writes `pending_tool_calls` to the coordinator; Engine 1 executes locally after server approval (see Tool Execution Modes below).

## Tool Execution Modes

Corvus distinguishes **local tools** (VM execution after RBAC) from **provider-hosted tools** (inference provider infrastructure).

| Mode | Manifest | Who executes | Audit |
|------|----------|--------------|-------|
| **local** (default) | `engine3.tool_execution_mode: local` | Engine 1 in VM after `tool_call_response.approved` | Full `tool_operation` chain |
| **hybrid** (opt-in) | `tool_execution_mode: hybrid` + `provider_tools: [provider:tool]` | Local tools as above; listed provider tools on provider infra | `provider_tool_invocation` + partial upstream audit |

**Rules:**
- Default is **local only**. Provider-native tool types (e.g. `web_search`, `code_interpreter`) are stripped from upstream requests in local mode.
- Hybrid mode requires both manifest selection **and** provider registry `hosted_tools_allowed: true` for each tool.
- The Corvus Server **never** executes agent tool code on the host.
- Engine 3 dispatches LLM `tool_calls` to Engine 1 via coordinator fields, not direct engine messages.
- Set `CORVUS_LLM_LOCAL_TOOLS=echo,terminal,file_read` (or manifest-equivalent) to enable the Engine 3 → Engine 1 tool loop at runtime.
- Streaming (`CORVUS_LLM_STREAM=1`) is compatible with local tools (Phase 7.2b) and hybrid provider-hosted tools (Phase 7.2+): Engine 3 streams text deltas, drives the Engine 1 tool loop when the final streamed `llm_response` carries local `tool_calls`, and records `provider_tools_used` when hosted tools run on provider infrastructure.

### Engine 4 – Memory (Privileged for Memory Operations)
- **Only** engine permitted to originate `memory:*` message types.
- All memory operations (query, write, grant requests) must be sent to the Corvus Server via Corvus Node.
- Must include valid grants for any cross-agent memory access.

## Corvus Node Workflow Rules

The Corvus Node enforces these rules on every message:

### Outbound (from VM to Server)
- Perform structural validation:
  - Required header fields present and correctly typed
  - `source.engine` matches the registered originating engine (anti-spoofing)
  - Capability tags consistent with engine (e.g., only Engine 4 may use `memory:*`)
  - Valid correlation chain where applicable
- Rate limiting per engine
- Boot-time handshake must complete successfully before normal operation

### Inbound (from Server to VM)
- Validate origin (must come from Corvus Server)
- Validate correlation ID consistency
- Route to correct engine or Agent Loop based on `destination.target` or `type`

## Message & Correlation Rules

- Every request that expects a response **must** carry a `correlation_id`.
- Tool calls and memory operations must trace back to a recent user-initiated turn via the correlation chain.
- Messages with `may_leave_vm: true` receive additional server-side scrutiny.
- Unknown or mismatched capability tags result in rejection.

## Error Handling & Recovery Rules

- On validation failure inside Corvus Node: Generate a structured `error` message and return it to the originator without crashing the VM.
- On transient AF_VSOCK failure: Implement exponential backoff reconnection.
- Critical or repeated failures must be reported to the Corvus Server.
- The Agent Loop must be able to recover and continue to the next turn where possible.

## Enforcement & Audit

- These rules are enforced at multiple layers:
  1. Architectural (engine separation + internal bus)
  2. Corvus Node (local structural validation)
  3. Corvus Server (RBAC, policy engine, correlation validation, behavioral monitoring)
- Every hop is logged with full correlation context for auditability.

## Elevation Workflow (Server-Mediated)

When policy returns `elevate` (for example cross-agent memory without a grant, or behavioral rate anomaly):

1. **Engine 4** sends `memory:*` (or other gated operation) through Corvus Node with a valid correlation chain.
2. **Corvus Server** evaluates RBAC + behavioral signals; on `elevate`, creates a pending elevation record and returns `SERVER_ELEVATION_REQUIRED` with `elevation_id`.
3. **Management API** (`POST /v1/elevations/{id}/approve`) allows an authorized operator to approve; the server replays the original request with an issued grant.
4. If the agent VM is offline, replay responses are queued in `pending_replay` and delivered on the next successful handshake ack after reconnect.
5. **ElevationSweeper** expires unapproved elevations after TTL (default 1 hour).

Agents must treat elevation responses as recoverable: retry only after approval, not by bypassing Corvus Node.

## Behavioral Monitoring (Server-Side)

The server maintains sliding-window counters per agent (persisted in SQLite, survive restart):

| Signal | Meaning |
|--------|---------|
| `repeated_grant_denials` | Cross-agent memory operations denied for missing grant within the window |
| `cross_agent_scope_spike` | Unusual volume of cross-agent memory ops in a short window |
| `message_rate_anomaly` | Z-score spike vs. longer baseline message rate |

Policy rules in `default_rules.yaml` can **deny** or **elevate** based on these signals. Engine 4 does not compute them locally; they are authoritative server facts attached at policy evaluation time.

## Summary for AI Agents & Implementers

When implementing or modifying agent behavior:

- Never allow Engine 3 to bypass the bus or Corvus Node.
- Never allow direct memory access from any engine except Engine 4.
- Always maintain strict correlation and origin tracking.
- Design the Agent Loop as a thin orchestrator, not a central router.
- All capabilities are declared at launch time and baked into the immutable rootfs.

Violations of these workflow rules break the security model of Corvus Hypervisor.

**Black Rain Labs - Research & Development Division**

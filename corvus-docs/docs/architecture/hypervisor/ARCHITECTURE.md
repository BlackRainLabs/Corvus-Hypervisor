**Document:** ARCHITECTURE.md
**Status:** Implemented — Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-07-05
**Related Documents:** OVERVIEW.md, hypervisor/RBAC-POLICY.md, hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md, memory/ARCHITECTURE.md, CHANGES.md
**Must Update on Change:** CHANGES.md

# Hypervisor Architecture (Corvus Server)

## Overview

The Corvus Server is the central command and control authority in the system. It is responsible for routing, policy enforcement, validation, auditing, and coordination across all agents.

It performs no LLM inference itself.

## Core Responsibilities

- User and alias resolution
- RBAC and capability enforcement via Policy Decision Point
- FrameworkMessage routing and validation
- Session and turn state management (correlation chains)
- Memory Service and Grant Engine
- Behavioral monitoring and anomaly detection (Phase 5)
- Elevation workflow management
- Comprehensive audit logging

## Key Subsystems

### RBAC & Policy Engine

The Policy Decision Point evaluates every inbound FrameworkMessage from agent microVMs. See [RBAC-POLICY.md](RBAC-POLICY.md).

**Evaluation summary:**
1. Fact Gatherer assembles context (user, agent, message, correlation, grants, quotas)
2. Rule Engine matches declarative rules by priority
3. Decision Combiner applies default-deny with first-match-wins semantics
4. Auditor logs full decision trace

Outcomes: **allow** (route/execute), **deny** (return error), **elevate** (queue for human approval).

### Messaging Layer

Central bus over AF_VSOCK from Corvus Nodes. All messages use the FrameworkMessage envelope. See [FRAMEWORK-MESSAGE-PROTOCOL.md](FRAMEWORK-MESSAGE-PROTOCOL.md).

**Server-side validation (after Node local checks):**
- Session token validity
- Correlation chain integrity and turn timeout
- RBAC policy decision
- Grant evaluation for cross-agent memory operations
- Quota enforcement for LLM requests

### Memory Service & Grant Engine

Owns all per-agent memory stores outside microVMs. See [memory/ARCHITECTURE.md](../memory/ARCHITECTURE.md).

**Components:**
- **Memory Service** — CRUD on agent-scoped records (SQLite + sqlite-vec in Phase 2)
- **Grant Engine** — Evaluates cross-agent grant schema; creates/revokes grants via elevation or Management API
- **Retention sweeper** — TTL enforcement and namespace quotas

Private-by-default: owner-agent access requires no grant; all other access requires valid grant evaluated during PDP `has_valid_grant` condition.

### Audit Engine

Append-only, correlated logging of:
- Every FrameworkMessage hop (Node ↔ Server)
- Policy decisions with matched rule IDs and explanation trace
- Memory operations (read/write/delete/grant)
- Elevation lifecycle events
- Management API mutations

Audit entries reference `correlation_id` for end-to-end traceability.

### Elevation Queue

Pending human approvals for sensitive actions. Integrates with RBAC `elevate` outcomes and `memory:grant_request` messages. Approvals may create runtime grants or delegations.

## Interaction with Agents

All agents communicate exclusively through the Corvus Server via their Corvus Node (AF_VSOCK). There are no direct agent-to-agent channels.

**Boot flow:** Corvus Node handshake → session token + policy snapshot → normal message traffic.

## Trust Model

The hypervisor treats all agent-internal components (especially Engine 3 — the LLM) as untrusted. Validation is deterministic and metadata-driven. Corvus Node provides first-layer structural checks; Corvus Server is authoritative for policy and grants.

**Black Rain Labs - Research & Development Division**

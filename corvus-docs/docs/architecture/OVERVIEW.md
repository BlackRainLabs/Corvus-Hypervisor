---
**Document:** OVERVIEW.md
**Status:** Implemented — Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division
**Last Updated:** 2026-07-05
**Related Documents:** hypervisor/ARCHITECTURE.md, hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md, agent-vm/ARCHITECTURE.md, CHANGES.md
**Must Update on Change:** CHANGES.md (repository root)
**AI Instruction:** When revising this document, review Core Principles & Invariants here, update CHANGES.md, and ensure consistency with related documents. Do not contradict core fundamentals.
**API Caution:** Any changes must consider impact on the Management API surface (see hypervisor/MANAGEMENT-API.md). Maintain backward compatibility where possible and document breaking changes.
---

# Corvus Architecture Overview

**Status:** Implemented — Current
**Organization:** Black Rain Labs
**Division:** Research & Development Division

## Core Principles & Invariants (Authoritative)

These principles must be respected across all documents:

1. **Everything crosses the Corvus Server** — No bypass paths. All messages and actions are mediated by the central hypervisor.
2. **Strict Star Topology** — Agents have no direct external or inter-agent communication. Everything routes through the Corvus Server.
3. **No Direct LLM-to-Tool Execution** — Engine 3 (LLM) cannot directly call tools or access memory. All actions must route through the Corvus Server for validation.
4. **Deterministic Validation Only** — The hypervisor performs **no LLM-based semantic inspection**. Validation uses structured metadata, correlation chains, capability tags, and state machines.
5. **Launch-time Immutability** — Tools, skills, and engine capabilities are selected at launch and baked into a read-only rootfs.
6. **Centrally Mediated Memory** — Persistent memory lives outside agent microVMs. Cross-agent access requires explicit grants evaluated by the Corvus Server.
7. **Full Auditability of Every Hop** — Every message is logged with correlation IDs for complete traceability.
8. **4-Engine Model** — Every agent microVM contains exactly four engines with strict separation of concerns (see Agent VM Architecture).

## Vision

Corvus is a security-first multi-agent hypervisor that treats agents as potentially untrusted workloads. It provides strong isolation using Firecracker microVMs and enforces centralized mediation through the Corvus Server.

## Major Components

### Hypervisor Layer (Corvus Server)
- Central command and control
- RBAC and policy engine
- FrameworkMessage routing and validation
- Memory Service + Grant Engine
- Audit logging
- Behavioral monitoring

### Agent Layer (MicroVMs)
- Isolated Firecracker microVM per agent
- 4-engine model (Tools & Skills, Gateway/Channels, LLM/Inference, Memory)
- Corvus Node as the narrow external interface and local structural validator

### Cross-Cutting
- FrameworkMessage Protocol
- Correlation and traceability model
- Capability system (launch-time + runtime grants)

## Document Index

- [Hypervisor Architecture](hypervisor/ARCHITECTURE.md)
- [FrameworkMessage Protocol](hypervisor/FRAMEWORK-MESSAGE-PROTOCOL.md)
- [RBAC & Policy](hypervisor/RBAC-POLICY.md)
- [Agent VM Architecture](agent-vm/ARCHITECTURE.md)
- [Corvus Node](agent-vm/CORVUS-NODE.md)
- [Memory Architecture](memory/ARCHITECTURE.md)
- [Agent Workflow Rules](agent-vm/AGENT-WORKFLOW.md)


---
**Black Rain Labs - Research & Development Division**

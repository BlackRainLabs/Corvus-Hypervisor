# AGENTS.md — Instructions for AI Coding Agents

**Project:** Corvus Hypervisor  
**Purpose:** High-assurance, security-first multi-agent hypervisor using Firecracker microVMs.

## Critical Rules

1. **Start with these documents**:
   - `corvus-docs/docs/architecture/OVERVIEW.md` (Core Principles & Invariants — authoritative)
   - Root `CHANGES.md` (latest changes and usage instructions)
   - `corvus-docs/docs/planning/OPERATIONS.md` (dev stack, Docker, metrics, policy fixtures)
   - `corvus-docs/docs/architecture/agent-vm/AGENT-WORKFLOW.md` (runtime agent behavior rules)
   - Root `README.md` (setup: server, node, runtime, tests, Firecracker smoke)

2. **Implementation code** lives under `src/corvus/` (`protocol`, `server`, `policy`, `audit`, `llm`, `memory`, `management`, `node`, `runtime`, `vm`, `tools`).

3. **Changelog is Mandatory**:
   - Every change must be recorded in root `CHANGES.md` with proper format and date.

4. **Runtime Agent Workflow**:
   - The rules in `AGENT-WORKFLOW.md` are binding for any implementation or modification of agent behavior inside microVMs.
   - Respect the 4-Engine Model strictly.
   - Engine 3 (LLM) must never directly call tools or memory.
   - Tool execution policy: local mode (default) runs LLM `tool_calls` in Engine 1 after server RBAC; hybrid mode is opt-in per manifest — see `AGENT-WORKFLOW.md`.

5. **Documentation Standards**:
   - Update "Last Updated" dates.
   - Maintain Related Documents and "Must Update on Change: CHANGES.md".
   - Avoid `---` frontmatter separators.

See the full workflow rules in `corvus-docs/docs/architecture/agent-vm/AGENT-WORKFLOW.md`.

**Black Rain Labs - Research & Development Division**

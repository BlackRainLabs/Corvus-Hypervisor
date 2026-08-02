# Contributing to Corvus Hypervisor

Thanks for your interest in Corvus. Contributions should preserve the security invariants in the architecture docs.

## Before you change code

1. Read [`corvus-docs/docs/architecture/OVERVIEW.md`](corvus-docs/docs/architecture/OVERVIEW.md) (Core Principles).
2. For agent runtime behavior, follow [`AGENT-WORKFLOW.md`](corvus-docs/docs/architecture/agent-vm/AGENT-WORKFLOW.md).
3. For AI-assisted work, follow [`AGENTS.md`](AGENTS.md).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make test
make fixtures
make lint
```

## Pull requests

1. Keep changes focused and consistent with existing style.
2. Update root [`CHANGES.md`](CHANGES.md) for every meaningful change.
3. Follow documentation header standards in `corvus-docs/`.
4. Prefer TCP-mode tests for CI; document any Firecracker-only validation.

## Security

Do not commit secrets, production credentials, or local databases. See [`SECURITY.md`](SECURITY.md).

**Black Rain Labs - Research & Development Division**

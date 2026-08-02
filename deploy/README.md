# Corvus Server — Docker deployment (TCP dev/prototype)

Runs **Corvus Server only** (transport + Management API). Run Corvus Node and agent runtime on the host, pointing at the published TCP port.

## Quick start

From the repository root:

```bash
docker compose -f deploy/docker-compose.yml up --build -d
curl -H "X-API-Key: dev-api-key" http://127.0.0.1:8080/v1/health
```

On the host (with venv active):

```bash
export CORVUS_USE_TCP=1
export CORVUS_TCP_HOST=127.0.0.1
export CORVUS_TCP_PORT=4040
export CORVUS_NODE_SOCK=/tmp/corvus-node.sock
corvus-node
corvus-runtime --once
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORVUS_API_KEY` | `dev-api-key` | Management API auth |
| `CORVUS_TCP_PORT` | `4040` | Host port for agent transport |
| `CORVUS_MGMT_PORT` | `8080` | Host port for Management API |
| `CORVUS_LOG_JSON` | `0` | Set `1` for structured JSON logs |

Data persists in the `corvus-data` Docker volume (`/data/corvus.db`).

See [OPERATIONS.md](../corvus-docs/docs/planning/OPERATIONS.md) for the full operator guide.

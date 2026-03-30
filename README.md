# pggraphrag-mcp

`pggraphrag-mcp` is a remote MCP server skeleton for GraphRAG on PostgreSQL.

This repository is structured around five local-development milestones:

1. Compose skeleton
2. Database baseline
3. Authentication gateway
4. Minimal MCP HTTP app
5. Smoke test

The current implementation targets a local Docker Compose workflow with:

- `Traefik` as the HTTPS reverse proxy
- a small bearer-token auth gateway
- a private FastAPI-based MCP app
- PostgreSQL 17 with `pgvector` and `Apache AGE`

## Repository layout

- `docker/`
  - `auth/`
  - `private-app/`
  - `postgres-age/`
    - `initdb/`
  - `traefik/`
  - `docker-compose.yml`
  - `docker-compose.small-auth.yml`
- `docs/`
- `schemas/`
- `scripts/`
- `src/`
  - `pggraphrag_mcp/`
- `tests/`
- `.env.example`
- `.env.production.example`
- `Makefile`
- `pyproject.toml`

## What is included

### Compose skeleton
- the private app and database are only exposed on the internal network
- only the reverse proxy publishes a host port
- the compose files are split into:
  - core app + db
  - proxy + auth overlay

### Database baseline
- a repository-owned PostgreSQL image
- `pgvector` extension support
- `Apache AGE` extension support
- init SQL for:
  - extension availability
  - canonical relational tables
  - AGE graph bootstrap

### Auth gateway
- validates a bearer token
- injects an authenticated identity header
- sits in front of the private app

### Minimal MCP app
- FastAPI + uvicorn
- `GET /readyz`
- `GET /mcp`
- `POST /mcp`
- minimal tools:
  - `health_check`
  - `index_status`
  - `graph_status`

### Smoke test
- unauthenticated request must fail
- authenticated health check must pass
- authenticated minimal tool invocation must pass

## Prerequisites

Install the following locally:

- Docker
- Docker Compose
- Python 3.12+
- `uv`

You also need a local TLS certificate pair for Traefik.

## Quick start

### 1. Copy the environment file

Use:

`cp .env.example .env`

Then edit `.env` as needed.

At minimum, verify these values:

- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN`
- `PGGRAPHRAG_MCP_DB_PASSWORD`
- `PGGRAPHRAG_MCP_DATABASE_URL`

### 2. Prepare local TLS files

The compose stack expects certificate files that Traefik can read.

For a simple local setup, create a self-signed certificate and make sure these paths match your environment:

- `PGGRAPHRAG_MCP_TLS_CERT_FILE`
- `PGGRAPHRAG_MCP_TLS_KEY_FILE`

If you mount `/certs/dev.crt` and `/certs/dev.key` inside the proxy container, place the corresponding files where that mount can read them.

Example self-signed generation on macOS/Linux:

`mkdir -p docker/traefik/certs`

`openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout docker/traefik/certs/dev.key -out docker/traefik/certs/dev.crt -subj "/CN=localhost"`

If you use this approach, make sure the Traefik config and compose volume mapping point at the same files.

### 3. Build and start the stack

Run:

`COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-up`

This starts:

- `pggraphrag-db`
- `pggraphrag-mcp-private`
- `pggraphrag-mcp-auth`
- `pggraphrag-mcp-proxy`

### 4. Inspect logs

Run:

`make compose-logs`

### 5. Run the smoke test

Run:

`uv run python scripts/mcp_http_smoke.py --base-url https://localhost:8443 --mcp-path /mcp --bearer-token change-me-local-token --insecure`

If everything is healthy, the script exits successfully and prints a JSON summary.

## Local development commands

### Python package

- `uv sync`
- `uv run pggraphrag-mcp print-config`

### Run the app outside Compose

- `uv run pggraphrag-mcp serve --reload`

### Lint

- `make lint`

### Test

- `make test`

### Smoke

- `make smoke`

### Stop the stack

- `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-down`

## MCP endpoint behavior

### Public entrypoint
- `https://localhost:8443/mcp`

### Access pattern
- the client calls the proxy over HTTPS
- the proxy forwards the auth check to the auth gateway
- the auth gateway validates the bearer token
- the proxy forwards the authenticated request to the private app
- the private app requires the authenticated identity header

### Minimal tool calls

The app currently supports a JSON-RPC style request body.

Example `health_check` request payload:

`{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}`

Example `curl`:

`curl -k https://localhost:8443/mcp -H "Authorization: Bearer change-me-local-token" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}'`

The current `POST /mcp` response shape is JSON-RPC. Successful calls return:

- `jsonrpc`
- `id`
- `result`

Failed calls return:

- `jsonrpc`
- `id`
- `error`

## Environment variables

All application settings use the `PGGRAPHRAG_MCP_` prefix.

Common local settings include:

### App
- `PGGRAPHRAG_MCP_APP_NAME`
- `PGGRAPHRAG_MCP_APP_VERSION`
- `PGGRAPHRAG_MCP_ENV`
- `PGGRAPHRAG_MCP_HTTP_HOST`
- `PGGRAPHRAG_MCP_HTTP_PORT`
- `PGGRAPHRAG_MCP_HTTP_PATH`
- `PGGRAPHRAG_MCP_PUBLIC_BASE_URL`
- `PGGRAPHRAG_MCP_LOG_LEVEL`
- `PGGRAPHRAG_MCP_ENABLE_DEBUG_ENDPOINTS`

### Auth
- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN`
- `PGGRAPHRAG_MCP_AUTH_HEADER_NAME`
- `PGGRAPHRAG_MCP_AUTH_IDENTITY`

### Database
- `PGGRAPHRAG_MCP_DB_NAME`
- `PGGRAPHRAG_MCP_DB_USER`
- `PGGRAPHRAG_MCP_DB_PASSWORD`
- `PGGRAPHRAG_MCP_DATABASE_URL`
- `PGGRAPHRAG_MCP_AGE_GRAPH_NAME`

### Retrieval and limits
- `PGGRAPHRAG_MCP_MAX_VECTOR_CANDIDATES`
- `PGGRAPHRAG_MCP_MAX_GRAPH_HOPS`
- `PGGRAPHRAG_MCP_MAX_RETURN_CHUNKS`
- `PGGRAPHRAG_MCP_MAX_RETURN_ENTITIES`

### Compose project naming
- set `COMPOSE_PROJECT_NAME=pggraphrag_mcp` when running the small compose stack
- this avoids collisions with other stacks that would otherwise appear under a generic `docker` project name
- example:
  - `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-up`
  - `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-down`

## Acceptance targets for the local stack

The local stack is considered healthy when these conditions are met.

### Startup
- `docker compose` starts all services
- the private app and db are not directly exposed
- `/mcp` is reachable over HTTPS

### Auth
- `/mcp` is rejected without a bearer token
- `/mcp` succeeds with a bearer token

### Persistence baseline
- `vector` extension is available
- `age` extension is available
- the relational schema exists
- AGE graph bootstrap is repeatable

### App behavior
- `health_check` responds
- `index_status` responds
- `graph_status` responds

### Operations
- the smoke script passes
- structured logs are emitted

## Notes and limitations

This is still a skeleton implementation.

What is intentionally minimal right now:

- document ingestion pipeline
- embedding generation
- entity and relation extraction
- graph refresh from relational state
- naive, local-graph, and hybrid retrieval
- source trace resources

Those are planned next layers on top of the current foundation.

## Troubleshooting

### Proxy is up but `/mcp` returns `401`
- verify the `Authorization: Bearer ...` header
- verify that `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN` matches what the auth service expects

### App readiness is failing
- verify that the database container is healthy
- verify `PGGRAPHRAG_MCP_DATABASE_URL`
- inspect logs with `make compose-logs`

### TLS handshake issues
- use `--insecure` for the local smoke script when using self-signed certs
- verify certificate and key paths
- verify the Traefik mounts

### Database init issues
If the persisted volume contains an incompatible old state, rebuild from scratch:

- `make compose-down`
- `docker volume rm pggraphrag_db_data`
- `make compose-up`

## Next implementation areas

After local skeleton validation, the next major steps are:

1. ingest pipeline
2. embeddings integration
3. entity and relation extraction
4. graph refresh
5. naive, local-graph, and hybrid retrieval
6. source trace
7. integration tests

## License

Add your project license here.
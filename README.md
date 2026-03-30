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

The repository also includes CI validation for clean-checkout test execution with Python 3.12 and `uv`.

It now also includes explicit operational scripts for schema application and graph bootstrap / rebuild flows.

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
  - schema and graph operation scripts
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

### Explicit operations
- schema application can be run explicitly
- graph bootstrap and rebuild can be run explicitly
- these operations are repeatable and intended for operator use

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

The verified local default public endpoint is:

- `https://localhost:9443/mcp`

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

`uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token change-me-local-token --insecure`

If everything is healthy, the script exits successfully and prints a JSON summary covering:

- unauthorized rejection
- authenticated `health_check`
- authenticated `index_status`
- seeded `document_ingest`
- authenticated `retrieve_hybrid`
- authenticated `source_trace`

## Local development commands

### Python package

- `uv sync`
- `uv run pggraphrag-mcp print-config`

### Run the app outside Compose

- `uv run pggraphrag-mcp serve --reload`

### Lint

- `make lint`
- `uv run ruff check .`

### Test

- `make test`

### Smoke

- `make smoke`

### Explicit schema and graph operations

Use the explicit scripts under `scripts/` for operator-driven maintenance tasks.

Recommended operations:
- schema apply
- AGE bootstrap
- graph refresh by document
- full graph rebuild

Concrete examples:

- apply the repository-owned SQL files to a target database
  - `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose`

- validate the schema apply plan without executing SQL
  - `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --check-only`

- inspect current graph projection status
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --status --pretty`

- rebuild the full AGE graph projection
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --full-rebuild --pretty`

- rebuild projection for one document only
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --document-id "<document-uuid>" --pretty`

These operations should be treated as explicit maintenance flows rather than implicit side effects of unrelated commands.

### CI-equivalent local validation

- `uv run ruff check .`
- `python -m compileall src scripts tests`
- `uv run pytest`

### Stop the stack

- `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-down`

## MCP endpoint behavior

### Public entrypoint
- `https://localhost:9443/mcp`

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

`curl -k https://localhost:9443/mcp -H "Authorization: Bearer change-me-local-token" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"example-1","method":"tools/call","params":{"name":"health_check","arguments":{}}}'`

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

### Embeddings
- `PGGRAPHRAG_MCP_EMBEDDING_PROVIDER`
- `PGGRAPHRAG_MCP_EMBEDDING_MODEL`
- `PGGRAPHRAG_MCP_EMBEDDING_DIMENSIONS`
- `OPENAI_API_KEY`

Remote embedding behavior:
- when `PGGRAPHRAG_MCP_EMBEDDING_PROVIDER=openai`, the app uses the OpenAI-compatible provider path
- when `OPENAI_API_KEY` is available, that provider can use the configured OpenAI-backed mode
- when `OPENAI_API_KEY` is missing or remote mode is unavailable, the app falls back to the local deterministic-compatible mode
- the fallback keeps ingest and retrieval working in local development and test environments
- response payloads and logs still report the configured embedding provider and model so you can tell which path is active

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
- schema application is available through an explicit script
- graph bootstrap is available through an explicit script
- graph rebuild is repeatable
- the smoke script passes
- structured logs are emitted
- the README documents concrete schema-apply and graph-bootstrap commands

## Structured log fields

The app emits JSON logs to make request tracing possible without Grafana.

Core fields include:

- `timestamp`
- `level`
- `logger`
- `message`

Request and correlation fields include:

- `request_id`
- `authenticated_identity`
- `event`
- `method`
- `path`
- `query`
- `status_code`
- `duration_ms`
- `client_host`

Tool execution logs additionally include:

- `tool_name`
- `tool_arguments`

Database bootstrap and startup logs additionally include:

- `database_url` (redacted)
- `age_graph_name`

Recommended operator workflow for debugging one request:

1. find the `request_id`
2. follow auth acceptance or rejection in the auth service logs
3. follow HTTP and tool execution logs in the private app logs
4. correlate retrieval or ingest behavior with DB-backed status responses

## Notes and limitations

This is still an initial implementation milestone, but it now includes working end-to-end flows for:

- document ingestion into canonical PostgreSQL tables
- embedding-backed retrieval
- heuristic entity and relation extraction
- AGE graph projection refresh
- naive, local-graph, and hybrid retrieval
- source trace responses

What remains intentionally lightweight right now:

- OpenAI-compatible embedding support includes a local fallback path for environments without `OPENAI_API_KEY`
- entity extraction and relation typing are heuristic rather than model-driven
- graph refresh is functional but still a simple projection path

Those are the next areas for improvement on top of the current milestone.

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
- verify you are testing against `https://localhost:9443`

### Database init issues
If the persisted volume contains an incompatible old state, rebuild from scratch:

- `make compose-down`
- `docker volume rm pggraphrag_db_data`
- `make compose-up`

### Schema and graph operation issues
If relational schema or graph projection state becomes inconsistent:

- run the explicit schema-apply script
  - `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose`
- inspect graph status
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --status --pretty`
- run the explicit graph bootstrap or rebuild script
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --full-rebuild --pretty`
- if only one document needs repair, refresh that document instead
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --document-id "<document-uuid>" --pretty`
- re-run the smoke test after maintenance completes

## Release readiness checklist

Use this checklist before tagging `v0.1.0`.

### Clean environment validation
- copy `.env.example` to `.env`
- provide valid local TLS certificate and key files
- run `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-up`
- verify all services become healthy
- run the smoke test successfully against `https://localhost:9443/mcp`
- verify the same clean-environment path also works after recreating the database volume
- verify explicit maintenance commands work in the same environment:
  - `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --check-only`
  - `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --status --pretty`

### Verification
- run `python -m compileall src scripts tests`
- run `uv run pytest`
- verify authenticated `health_check`
- verify authenticated `index_status`
- verify `document_ingest`
- verify `retrieve_hybrid`
- verify `source_trace`
- verify AGE projection counts are non-zero after ingest
- verify schema application can be executed explicitly
- verify graph bootstrap can be executed explicitly
- verify graph rebuild remains repeatable after explicit maintenance
- verify the current suite includes hardening / release-readiness coverage in addition to HTTP and GraphRAG flow coverage
- verify embedding configuration behaves as expected in both cases:
  - with `OPENAI_API_KEY` present
  - without `OPENAI_API_KEY`, using the documented fallback path

### CI validation workflow

The repository is intended to validate clean-checkout behavior in CI with two jobs:

#### `lint`
- Python 3.12
- `uv`-based dependency setup
- `uv run ruff check .`

#### `test`
- Python 3.12
- `uv`-based dependency setup
- bytecode / import compilation via `python -m compileall src scripts tests`
- test execution via `uv run pytest`

The CI scope is intentionally lightweight:
- it validates repository correctness without requiring a live Azure environment
- it does not require a remote embedding API key for the default local test path
- it mirrors the recommended local validation commands before a release or major merge

### Public surface freeze
Freeze these tool names for `v0.1.0`:

- `health_check`
- `index_status`
- `graph_status`
- `document_ingest`
- `document_reingest`
- `document_delete`
- `graph_refresh`
- `rebuild_embeddings`
- `retrieve_naive`
- `entity_search`
- `entity_expand`
- `retrieve_local_graph`
- `retrieve_hybrid`
- `source_trace`

### Operational review
- verify structured logs contain `request_id`
- verify auth logs and app logs can be correlated for one request
- verify database URLs remain redacted in logs
- verify private app and database are not directly exposed on the host
- verify only the proxy publishes the external HTTPS port
- verify schema apply and graph bootstrap / rebuild procedures are documented and executable as explicit operator actions

### Packaging and repository hygiene
- remove local artifacts such as `.DS_Store`
- ensure generated placeholder certificates are replaced or clearly documented for local-only use
- confirm README quick start matches the actual compose and smoke commands
- confirm commit history and working tree are clean before release tagging

## Next implementation areas

After this milestone, the next major steps are:

1. remote embedding provider implementation
2. higher-quality entity and relation extraction
3. graph refresh diffing and rebuild recovery
4. retrieval scoring and reranking improvements
5. broader integration and release automation

## License

Add your project license here.
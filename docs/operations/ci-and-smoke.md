# CI and Smoke Operator Guide

This guide covers the verified validation paths for `pggraphrag-mcp` in both local development and CI.

## Scope

Use this guide when you want to:

- validate a clean checkout
- run the lightweight repository checks
- run the heavier compose-based HTTPS smoke flow
- understand what the CI jobs are expected to do
- troubleshoot smoke failures

## Validation layers

The repository currently uses three validation layers:

1. **Lint**
   - static validation with `ruff`

2. **Test**
   - Python test suite
   - source compilation check

3. **Smoke**
   - full Docker Compose stack
   - HTTPS endpoint validation
   - authenticated MCP flow validation

These layers are intentionally separated so that:
- fast failures appear early
- heavy runtime validation stays isolated
- operator troubleshooting is easier

## CI job overview

### `lint`
Purpose:
- catch style and static issues early

Expected checks:
- `uv run ruff check .`

### `test`
Purpose:
- validate repository correctness without a running compose stack

Expected checks:
- `python -m compileall src scripts tests`
- `uv run pytest`

### `smoke`
Purpose:
- validate the end-to-end runtime behavior of the compose stack over HTTPS

Expected actions:
- prepare `.env`
- generate local TLS assets
- build and start compose services
- run `scripts/mcp_http_smoke.py`
- collect logs on failure
- tear down the stack

## Verified local validation flow

This is the recommended local sequence before a release or major merge.

### 1. Lint
```/dev/null/sh#L1-1
uv run ruff check .
```

### 2. Compile check
```/dev/null/sh#L1-1
python -m compileall src scripts tests
```

### 3. Test suite
```/dev/null/sh#L1-1
uv run pytest
```

### 4. Clean-volume compose smoke
This is the verified heavy validation path.

#### Stop the stack
```/dev/null/sh#L1-1
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml down --remove-orphans
```

#### Recreate the database volume
```/dev/null/sh#L1-1
docker volume rm pggraphrag_db_data
```

#### Start the full stack
```/dev/null/sh#L1-1
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml up -d --build
```

#### Run the smoke script
```/dev/null/sh#L1-1
uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token change-me-local-token --insecure
```

## Verified smoke coverage

The current smoke flow verifies:

- unauthorized request rejection
- authenticated `health_check`
- authenticated `index_status`
- seeded `document_ingest`
- authenticated `retrieve_hybrid`
- authenticated `source_trace`

This means the smoke path exercises:

- reverse proxy routing
- auth gateway validation
- MCP app endpoint behavior
- PostgreSQL persistence
- retrieval flow
- source trace flow
- AGE projection counts during ingest

## CI smoke prerequisites

The smoke job assumes:

- Docker is available
- Docker Compose is available
- Python 3.12 is available
- `uv` is available
- the repository can create local TLS files under `docker/traefik/certs`
- the repository can write a local `.env` file for CI execution

## CI smoke environment expectations

The smoke job should provide values equivalent to:

```/dev/null/env#L1-6
COMPOSE_PROJECT_NAME=pggraphrag_mcp
PGGRAPHRAG_MCP_PROXY_PORT=9443
PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN=change-me-local-token
PGGRAPHRAG_MCP_DB_PASSWORD=change-me-db-password
PGGRAPHRAG_MCP_DATABASE_URL=postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag
OPENAI_API_KEY=
```

## CI smoke TLS generation

The smoke path uses local self-signed TLS assets for Traefik.

Equivalent local command:

```/dev/null/sh#L1-2
mkdir -p docker/traefik/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout docker/traefik/certs/dev.key -out docker/traefik/certs/dev.crt -subj "/CN=localhost"
```

## CI smoke execution flow

A correct smoke job should follow this order:

1. check out repository
2. set up Python 3.12
3. set up `uv`
4. prepare `.env`
5. generate TLS certificate and key
6. install dependencies
7. start compose stack
8. wait briefly for services to become healthy
9. run smoke script
10. collect compose logs on failure
11. tear down compose stack

## Expected public endpoint

The verified local public endpoint is:

```/dev/null/text#L1-1
https://localhost:9443/mcp
```

## Failure investigation

### If lint fails
Focus on:
- import ordering
- unused imports
- syntax issues
- static rule violations

Run locally:
```/dev/null/sh#L1-1
uv run ruff check .
```

### If compile check fails
Focus on:
- syntax errors
- broken imports
- invalid Python files

Run locally:
```/dev/null/sh#L1-1
python -m compileall src scripts tests
```

### If tests fail
Focus on:
- behavior regressions
- schema or payload shape changes
- fixture expectations

Run locally:
```/dev/null/sh#L1-1
uv run pytest
```

### If smoke fails
Focus on:
- proxy/auth/app routing
- missing TLS assets
- missing or incorrect `.env`
- compose service health
- DB init/bootstrap issues

Recommended commands:
```/dev/null/sh#L1-1
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml ps
```

```/dev/null/sh#L1-1
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml logs --no-color
```

## Common smoke failure patterns

### `401 Unauthorized`
Likely causes:
- missing bearer token
- wrong bearer token
- auth gateway mismatch with `.env`

Check:
- `PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN`
- smoke command bearer token value

### `502 Bad Gateway`
Likely causes:
- private app not healthy yet
- auth service not healthy yet
- proxy started with invalid runtime config
- partial restart during validation

Preferred recovery:
- perform a full compose down/up
- avoid validating against a partially restarted stack

### DB initialization errors
Likely causes:
- stale incompatible database volume
- init SQL mismatch
- AGE bootstrap syntax issues

Preferred recovery:
- remove the database volume
- rebuild from a clean volume
- rerun the full smoke path

## Operator recommendations

- use `lint` and `test` for fast feedback
- use the clean-volume smoke path before release tagging
- do not rely on partial stack restarts for final validation
- when smoke fails, always inspect compose logs before retrying
- keep the verified endpoint and token values aligned with `.env`

## Release-oriented validation checklist

Before calling the implementation release-ready, confirm:

- lint passes
- compile check passes
- pytest passes
- compose config validates
- clean-volume full compose startup succeeds
- smoke passes against `https://localhost:9443/mcp`
- explicit schema apply and graph bootstrap flows remain usable
- logs are sufficient to trace proxy, auth, app, and DB behavior
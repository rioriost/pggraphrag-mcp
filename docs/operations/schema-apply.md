# Schema apply operator guide

This guide explains how to run the repository-owned schema application flow explicitly.

Use this when you want to:

- initialize a fresh database
- re-apply extensions and schema objects intentionally
- validate the SQL execution plan before touching the database
- recover from drift between the expected schema and the actual database state

## What the schema apply script does

The script applies the repository-owned SQL files in a fixed order:

1. `docker/postgres-age/initdb/00-init-extensions.sql`
2. `docker/postgres-age/initdb/01-schema.sql`
3. `docker/postgres-age/initdb/02-age-bootstrap.sql`

This covers:

- `pgvector` and `Apache AGE` extension availability
- canonical relational tables such as:
  - `document`
  - `chunk`
  - `entity`
  - `chunk_entity`
  - `relation_fact`
  - `ingestion_job`
  - `retrieval_log`
  - `graph_refresh_log`
- initial AGE graph bootstrap for `pggraphrag_memory`

## Prerequisites

You need:

- Python 3.12+
- `uv`
- reachability to the target PostgreSQL instance
- a valid PostgreSQL connection string

Typical local database URL:

`postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag`

## Recommended safety checks

Before applying schema changes:

- verify the target database URL points to the intended environment
- verify the database is reachable
- prefer `--check-only` first
- make sure no conflicting manual migration is currently running

## Basic usage

### Check the plan only

This prints the SQL execution plan and file hashes without executing SQL.

```/dev/null/sh#L1-1
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --check-only
```

### Apply the default repository-owned schema set

```/dev/null/sh#L1-1
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose
```

### Apply specific SQL files explicitly

Use this when you want to override the default ordered set.

```/dev/null/sh#L1-1
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --sql-file docker/postgres-age/initdb/00-init-extensions.sql --sql-file docker/postgres-age/initdb/01-schema.sql --sql-file docker/postgres-age/initdb/02-age-bootstrap.sql --verbose
```

### Resolve paths from a specific project root

```/dev/null/sh#L1-1
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --project-root . --verbose
```

## Important flags

### `--check-only`

- validates file existence
- reads the SQL
- prints the execution plan
- does not execute any SQL

### `--continue-on-error`

Default behavior stops on the first failing file.

If you want to continue through later files even after a failure:

```/dev/null/sh#L1-1
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --continue-on-error --verbose
```

Use this only when you intentionally want a full error inventory.

### `--application-name`

Lets you tag the DB session clearly.

```/dev/null/sh#L1-1
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --application-name "pggraphrag-manual-schema-apply" --verbose
```

## Expected success output

On success, you should see:

- a printed plan with the ordered SQL files
- short SHA-256 digests for each file
- `Schema apply completed successfully.`

If `--check-only` is used, you should instead see:

- the same plan
- `Check-only mode: no SQL was executed.`

## Operational guidance

### Fresh local environment

For a fresh local stack, a common sequence is:

1. start the database
2. apply schema explicitly
3. verify graph status
4. run the smoke test

Example flow:

```/dev/null/sh#L1-4
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml up -d pggraphrag-db
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose
PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --status --pretty
uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token change-me-local-token --insecure
```

### Recovering from schema drift

If you suspect the database is behind the repository state:

1. run `--check-only`
2. run full schema apply
3. run graph bootstrap status
4. run smoke again

### Clean-volume rebuild

If the database volume contains inconsistent local state, recreate it and re-apply.

Typical local recovery:

```/dev/null/sh#L1-4
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml down --remove-orphans
docker volume rm pggraphrag_db_data
COMPOSE_PROJECT_NAME=pggraphrag_mcp docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.small-auth.yml up -d --build
uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose
```

## Failure handling

If the script fails:

- read the failing file path from stderr
- inspect the exact SQL file
- confirm the target database version and extension state
- confirm the connection string points to the correct database
- rerun with `--check-only` if you need to validate file resolution
- use `--continue-on-error` only if you need a broader error inventory

The script exits non-zero when:

- a SQL file is missing
- a SQL file is empty
- database connection fails
- SQL execution fails
- one or more files fail during apply

## Known scope

This script is intended for explicit operator use.

It is not meant to:

- hide schema changes implicitly inside unrelated commands
- replace judgment around production migration windows
- execute arbitrary SQL outside the repository-owned SQL set unless you explicitly point it at custom files

## Related guides

- `docs/operations/graph-bootstrap.md`
- `docs/operations/ci-and-smoke.md`
- `docs/release-checklist.md`

# Graph bootstrap and rebuild operations

This guide covers explicit operator actions for inspecting, bootstrapping, and rebuilding the Apache AGE graph projection used by `pggraphrag-mcp`.

The relational PostgreSQL tables remain the canonical system of record.
The AGE graph is a derived projection and can be rebuilt.

## Purpose

Use the graph bootstrap script when you need to:

- inspect current graph projection status
- create the graph if it does not exist
- rebuild the full graph after schema or extraction changes
- refresh one document projection after targeted repair
- recover from projection drift while preserving canonical relational data

## Prerequisites

Before running any command, make sure:

- the database is reachable
- `PGGRAPHRAG_MCP_DATABASE_URL` points at the correct PostgreSQL instance
- `PGGRAPHRAG_MCP_AGE_GRAPH_NAME` is set if you want a non-default graph name
- the relational schema already exists
- the `age` extension is available in the database image

Default graph name:

- `pggraphrag_memory`

## Script location

The operator script lives here:

- `scripts/bootstrap_graph.py`

## Supported operations

The script supports three main actions:

1. show graph status
2. refresh one document projection
3. rebuild the full graph projection

## Environment variables

The script reads these values from the environment:

- `PGGRAPHRAG_MCP_DATABASE_URL`
- `PGGRAPHRAG_MCP_AGE_GRAPH_NAME`
- `PGGRAPHRAG_MCP_APP_NAME`
- `PGGRAPHRAG_MCP_LOG_LEVEL`

Minimum required variable:

- `PGGRAPHRAG_MCP_DATABASE_URL`

## Status check

Use this command to inspect the current graph state:

`PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --status --pretty`

Typical output includes:

- `graph_name`
- `graph_exists`
- `node_count`
- `edge_count`
- `latest_refresh`

Use this first when you suspect projection drift or after maintenance.

## Full graph bootstrap

Use a full bootstrap when:

- the graph does not exist yet
- you changed extraction logic
- you changed projection structure
- you want to repopulate AGE from canonical relational state

Command:

`PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --pretty`

Behavior:

- ensures the AGE extension is loaded
- ensures the graph exists
- projects all current relational document, chunk, entity, mention, and relation rows into AGE
- writes a refresh record into `graph_refresh_log`

Expected result fields:

- `status`
- `graph_name`
- `scope`
- `projected_documents`
- `projected_chunks`
- `projected_entities`
- `projected_relations`
- `projected_mentions`
- `node_count`
- `edge_count`

## Full rebuild

Use a full rebuild when you want to clear all current AGE nodes and edges first.

Command:

`PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --full-rebuild --pretty`

Behavior:

- truncates the current AGE graph
- recreates the full projection from relational state
- records the rebuild in `graph_refresh_log`

Use this when the graph may contain stale or incompatible projection data.

## Single-document refresh

Use a document-scoped refresh when one document needs targeted repair.

Command:

`PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --document-id "<document-uuid>" --pretty`

Behavior:

- removes the projected graph nodes and edges for the target document
- reprojects only that document and its related graph data
- records the document refresh in `graph_refresh_log`

Use this after reingest or when investigating one document’s graph state.

## Operational sequencing

Recommended order for manual recovery:

1. inspect graph status
2. confirm relational data exists
3. choose document refresh or full rebuild
4. run the graph script
5. rerun smoke or retrieval verification
6. inspect graph status again

## Relationship to schema application

Graph bootstrap does not replace schema application.

If relational schema or extension state is uncertain, first run the schema apply operation:

`uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose`

Then run graph bootstrap or rebuild.

## Verification after bootstrap

After a successful graph operation, verify all of the following:

- `graph_exists` is `true`
- `node_count` is greater than zero after seeded ingest
- `edge_count` is greater than zero after seeded ingest
- `latest_refresh.status` is `completed`
- retrieval flows still pass smoke validation

Example smoke verification:

`uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token change-me-local-token --insecure`

## Logging and observability

The script emits JSON-style operator logs to stderr for major events.

Common events include:

- `graph_created`
- `graph_truncated`
- `graph_bootstrap_completed`
- `graph_document_bootstrap_completed`
- `graph_status_checked`

Important fields include:

- `graph_name`
- `scope`
- `document_id`
- `projected_documents`
- `projected_chunks`
- `projected_entities`
- `projected_relations`
- `projected_mentions`
- `node_count`
- `edge_count`
- `graph_refresh_id`

## Failure modes

### Missing database URL

Symptom:
- script exits immediately with configuration failure

Action:
- set `PGGRAPHRAG_MCP_DATABASE_URL`

### Document not found

Symptom:
- document-scoped refresh fails

Action:
- confirm the UUID exists in `document`
- verify you are targeting the correct database

### AGE projection mismatch after code change

Symptom:
- retrieval still works from relational state but graph counts look wrong
- local graph or hybrid results look incomplete

Action:
- run `--full-rebuild`
- verify counts again
- rerun smoke

### Clean-volume bootstrap failure

Symptom:
- graph setup fails on first initialization

Action:
- verify the database image includes `age`
- verify the bootstrap SQL files are present
- rerun schema apply if necessary
- retry graph bootstrap

## Safety notes

- do not treat AGE as canonical truth
- do not manually mutate AGE and relational state independently
- prefer full rebuild after projection logic changes
- use document refresh only for narrow corrective work
- always verify smoke after explicit maintenance

## Recommended operator defaults

Best default actions:

- use `--status` before maintenance
- use document refresh for one-document repair
- use `--full-rebuild` after extraction or projection code changes
- rerun smoke after any explicit graph maintenance

## Release-readiness expectations

For release validation, graph operations are considered ready when:

- the graph can be inspected explicitly
- the graph can be bootstrapped explicitly
- the graph can be fully rebuilt explicitly
- the graph can be refreshed by document explicitly
- clean-volume startup followed by graph projection succeeds
- smoke still passes after rebuild
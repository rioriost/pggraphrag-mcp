# Graph bootstrap and rebuild operations

This guide covers explicit operator actions for inspecting, bootstrapping, rebuilding, and operationally validating the Apache AGE graph projection used by `pggraphrag-mcp`.

The relational PostgreSQL tables remain the canonical system of record.
The AGE graph is a derived projection and can be rebuilt.

For higher-level operator flows, the repository also provides `scripts/ops_automation.py` and the packaged entrypoint `pggraphrag-mcp-ops`.
These wrap graph status, bootstrap, and readiness checks into more repeatable maintenance sequences.

## Purpose

Use the graph bootstrap script when you need to:

- inspect current graph projection status
- create the graph if it does not exist
- rebuild the full graph after schema or extraction changes
- refresh one document projection after targeted repair
- recover from projection drift while preserving canonical relational data

Use the ops automation workflow when you want to:

- run graph status and readiness checks with one consistent operator interface
- bootstrap the graph and then wait until it is ready
- execute a small multi-step maintenance plan without manually chaining commands

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

The operator scripts live here:

- `scripts/bootstrap_graph.py`
- `scripts/ops_automation.py`

Packaged CLI entrypoint:

- `pggraphrag-mcp-ops`

## Supported operations

The bootstrap script supports three main actions:

1. show graph status
2. refresh one document projection
3. rebuild the full graph projection

The ops automation script supports higher-level actions:

1. show graph status
2. bootstrap the graph
3. bootstrap one document projection
4. evaluate graph readiness
5. wait until graph readiness checks pass
6. execute an ordered maintenance plan

## Environment variables

The scripts read these values from the environment:

- `PGGRAPHRAG_MCP_DATABASE_URL`
- `PGGRAPHRAG_MCP_AGE_GRAPH_NAME`
- `PGGRAPHRAG_MCP_APP_NAME`
- `PGGRAPHRAG_MCP_LOG_LEVEL`

The ops automation script also accepts local execution controls through flags, including polling interval, timeout, project root, and Python executable selection.

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

## Ops automation workflow

For repeatable operator flows, prefer the higher-level automation CLI when you want status, bootstrap, and readiness checks to be coordinated.

### Where to run the automation CLI

There are two valid execution contexts:

1. **inside the compose-connected runtime**
   - recommended when your database hostname is only resolvable on the compose network
   - this is the safest default for local operator validation

2. **from the host shell**
   - valid only when `PGGRAPHRAG_MCP_DATABASE_URL` points to a PostgreSQL endpoint that is reachable from the host
   - do not use a compose-internal hostname such as `pggraphrag-db` from the host shell unless your environment explicitly resolves it there

### In-network examples

Run these from inside a compose-connected container such as `pggraphrag-mcp-private`:

- `uv run pggraphrag-mcp-ops status`
- `uv run pggraphrag-mcp-ops ensure-ready`
- `uv run pggraphrag-mcp-ops wait-ready`
- `uv run pggraphrag-mcp-ops bootstrap --wait-ready`
- `uv run pggraphrag-mcp-ops bootstrap --full-rebuild --wait-ready`
- `uv run pggraphrag-mcp-ops bootstrap-document --document-id "<document-uuid>" --wait-ready`
- `uv run pggraphrag-mcp-ops plan --actions status bootstrap ensure-ready --wait-ready`

### Host-side examples

Run these from the host only when the DSN is host-reachable:

- `PGGRAPHRAG_MCP_DATABASE_URL="<host-reachable-postgres-dsn>" uv run pggraphrag-mcp-ops status`
- `PGGRAPHRAG_MCP_DATABASE_URL="<host-reachable-postgres-dsn>" uv run pggraphrag-mcp-ops bootstrap --wait-ready`

If the database is only reachable on the compose network, prefer executing the same commands inside the compose-connected runtime instead.

### Readiness behavior

The readiness-oriented commands are intended to answer a narrow operational question:
is the derived graph projection currently usable?

Current readiness checks verify:

- the graph exists
- the graph has at least one node
- the latest recorded graph refresh completed successfully

Use `ensure-ready` for a one-time evaluation.
Use `wait-ready` when a preceding maintenance step may take time to become observable.

These checks only succeed if the CLI can actually reach the database from its current runtime context.
If readiness fails immediately with hostname or connection errors, confirm whether you are running from the host or from inside the compose network, then verify that the configured `PGGRAPHRAG_MCP_DATABASE_URL` matches that execution context.

### Recommended automation sequences

For normal post-maintenance verification:

1. run `status`
2. run `bootstrap --wait-ready` when rebuilding is needed
3. run the HTTPS smoke flow
4. run `status` again if you want to confirm post-maintenance counts

For targeted document repair:

1. run `status`
2. run `bootstrap-document --document-id "<document-uuid>" --wait-ready`
3. rerun retrieval or smoke validation
4. confirm status if needed

For local compose-based validation, prefer this pattern:

1. execute the automation command inside `pggraphrag-mcp-private` or another compose-connected runtime
2. keep the compose-internal database hostname in the DSN for that in-network execution
3. run the HTTPS smoke flow from the host against `https://localhost:9443/mcp`

### Plan mode

Use `plan` when you want a compact operator command that executes several actions in order.

Example:

`uv run pggraphrag-mcp-ops plan --actions status bootstrap ensure-ready --wait-ready`

This is useful for:

- local recovery runbooks
- release-readiness verification
- repeated manual maintenance where command sequencing should stay consistent

## Logging and observability

The scripts emit JSON-style operator logs to stderr for major events.

Common bootstrap events include:

- `graph_created`
- `graph_truncated`
- `graph_bootstrap_completed`
- `graph_document_bootstrap_completed`
- `graph_status_checked`

Common ops automation events include:

- `ops_automation_status_completed`
- `ops_automation_bootstrap_completed`
- `ops_automation_document_bootstrap_completed`
- `ops_automation_ensure_ready_completed`
- `ops_automation_wait_ready_completed`
- `ops_automation_plan_completed`

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

When troubleshooting host-side execution failures, also inspect:

- the effective `PGGRAPHRAG_MCP_DATABASE_URL`
- whether the hostname in that DSN is resolvable from the current runtime
- whether the PostgreSQL port is reachable from the current runtime

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
- use `bootstrap --wait-ready` when you want one command to rebuild and then confirm readiness
- use `plan` when you want a repeatable operator sequence
- rerun smoke after any explicit graph maintenance
- when working locally, prefer running the automation CLI inside the compose-connected runtime unless you have explicitly provided a host-reachable PostgreSQL DSN

## Release-readiness expectations

For release validation, graph operations are considered ready when:

- the graph can be inspected explicitly
- the graph can be bootstrapped explicitly
- the graph can be fully rebuilt explicitly
- the graph can be refreshed by document explicitly
- clean-volume startup followed by graph projection succeeds
- smoke still passes after rebuild
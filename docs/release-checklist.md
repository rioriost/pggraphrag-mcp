# Release readiness checklist

This document is the standalone release checklist for `pggraphrag-mcp`.

Target milestone:

- `v0.1.0`

Use this checklist before creating a release tag or declaring the repository ready for wider use.

---

## 1. Repository hygiene

- [ ] working tree is clean
- [ ] no accidental local artifacts are present
  - [ ] `.DS_Store`
  - [ ] temporary notes
  - [ ] local scratch files
- [x] committed files match the intended public milestone
- [x] placeholder or local-only assets are clearly identified
- [x] docs reflect the current implemented behavior

---

## 2. Environment preparation

- [ ] `.env.example` is current
- [ ] `.env.production.example` is current
- [x] required environment variables are documented
- [x] local TLS certificate instructions are valid
- [x] local compose project naming is documented
  - [x] `COMPOSE_PROJECT_NAME=pggraphrag_mcp`
- [x] verified local public endpoint is documented
  - [x] `https://localhost:9443/mcp`

---

## 3. Build and static validation

Run these checks from a clean checkout.

- [x] `uv run ruff check .`
- [x] `python -m compileall src scripts tests`
- [x] `uv run pytest`

Expected result:

- [x] all lint checks pass
- [x] all imports compile
- [x] full test suite passes

---

## 4. CI validation

- [x] CI workflow file exists
  - [x] `.github/workflows/ci.yml`
- [x] CI has a dedicated `lint` job
- [x] CI has a dedicated `test` job
- [x] CI has a dedicated `smoke` job
- [x] CI uses Python 3.12
- [x] CI uses `uv`
- [x] CI job structure matches repository docs

Expected result:

- [ ] lint workflow is green
- [ ] test workflow is green
- [x] smoke workflow configuration is valid

---

## 5. Clean environment bring-up

Validate from a clean local environment.

- [x] copy environment file
  - [x] `cp .env.example .env`
- [x] generate or provide local TLS certificate and key
- [x] remove stale database volume when testing a clean bring-up
  - [x] `docker volume rm pggraphrag_db_data`
- [x] start the full stack
  - [x] `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-up`

Expected result:

- [x] all services start
- [x] all services become healthy
- [x] proxy is reachable
- [x] private app is not directly exposed
- [x] database is not directly exposed

---

## 6. Authentication verification

- [x] unauthenticated `/mcp` request is rejected
- [x] authenticated `/mcp` request is accepted
- [ ] forwarded auth headers are present as expected
- [x] auth logs can be correlated with app logs via request context

Expected result:

- [x] bearer token missing -> reject
- [x] bearer token valid -> allow

---

## 7. Database and schema verification

- [x] schema apply script exists
  - [x] `scripts/apply_schema.py`
- [ ] schema apply dry-run / check-only path works
- [ ] explicit schema apply path works
- [x] `pgvector` extension is available
- [x] `Apache AGE` extension is available
- [x] canonical relational tables exist
  - [x] `document`
  - [x] `chunk`
  - [x] `entity`
  - [x] `chunk_entity`
  - [x] `relation_fact`
  - [x] `ingestion_job`
  - [x] `retrieval_log`
  - [x] `graph_refresh_log`

Recommended verification commands:

- [ ] `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --check-only`
- [ ] `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose`

---

## 8. Graph bootstrap and rebuild verification

- [x] graph bootstrap / rebuild script exists
  - [x] `scripts/bootstrap_graph.py`
- [x] ops automation script exists
  - [x] `scripts/ops_automation.py`
- [x] packaged ops automation entrypoint exists
  - [x] `pggraphrag-mcp-ops`
  - [x] packaging/runtime import issue is resolved for `uv run pggraphrag-mcp-ops`
  - [x] host-runtime caveat is documented: the packaged CLI still needs a host-reachable `PGGRAPHRAG_MCP_DATABASE_URL` when run outside the compose network
- [x] graph status command works
- [ ] document-scoped graph refresh works
- [x] full graph rebuild works
- [ ] full graph rebuild is repeatable
- [x] graph refresh metadata is recorded
- [x] ops automation status command works
- [ ] ops automation readiness check works
- [ ] ops automation wait-ready flow works
- [x] ops automation bootstrap with readiness wait works
- [ ] ops automation plan mode works for ordered maintenance steps

Recommended verification commands:

- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --status --pretty`
- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --full-rebuild --pretty`
- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run python scripts/bootstrap_graph.py --document-id "<document-uuid>" --pretty`
- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="<host-reachable-postgres-dsn>" uv run pggraphrag-mcp-ops status`
- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="<host-reachable-postgres-dsn>" uv run pggraphrag-mcp-ops ensure-ready`
- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="<host-reachable-postgres-dsn>" uv run pggraphrag-mcp-ops bootstrap --wait-ready`
- [ ] `PGGRAPHRAG_MCP_DATABASE_URL="<host-reachable-postgres-dsn>" uv run pggraphrag-mcp-ops plan --actions status bootstrap ensure-ready --wait-ready`
- [x] packaged entrypoint help path works
  - [x] `PGGRAPHRAG_MCP_DATABASE_URL="postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" uv run pggraphrag-mcp-ops --help`
- [x] direct script fallback works for the same automation flow
  - [x] `uv run python scripts/ops_automation.py bootstrap --wait-ready`

Expected result:

- [x] graph exists
- [x] projected node counts are non-zero after ingest
- [x] projected edge counts are non-zero after ingest
- [x] readiness checks report the graph as ready after successful bootstrap
- [x] operator automation can run status, bootstrap, and readiness validation without manual command stitching
- [ ] packaged host-side automation uses a DSN that is valid from the host runtime, not only from inside compose

---

## 9. Retrieval and trace verification

Verify the public GraphRAG flows end to end.

- [x] `retrieve_naive` works
- [x] `retrieve_local_graph` works
- [x] `retrieve_hybrid` works
- [x] `entity_search` works
- [x] `entity_expand` works
- [x] `source_trace` works
- [x] responses remain JSON-safe
- [x] responses include bounded payloads
- [x] score breakdowns are present where expected

Expected result:

- [x] supporting chunks are returned
- [x] entities are returned
- [x] relationships are returned
- [x] sources are returned
- [x] `retrieval_id` is returned
- [x] source trace can be resolved from `retrieval_id`

---

## 10. Smoke validation

- [x] smoke script exists
  - [x] `scripts/mcp_http_smoke.py`
- [x] smoke test runs successfully against the verified local endpoint

Recommended command:

- [x] `uv run python scripts/mcp_http_smoke.py --base-url https://localhost:9443 --mcp-path /mcp --bearer-token change-me-local-token --insecure`

Expected smoke coverage:

- [x] unauthorized rejection
- [x] authenticated `health_check`
- [x] authenticated `index_status`
- [x] seeded `document_ingest`
- [x] authenticated `retrieve_hybrid`
- [x] authenticated `source_trace`
- [x] compose-backed smoke evidence captured locally against `https://localhost:9443/mcp`

---

## 11. Embedding validation

- [x] configured embedding provider is documented
- [x] local fallback behavior is documented
- [x] remote embedding provider behavior is documented
- [x] remote mode requires API key as expected
- [x] fallback mode keeps ingest and retrieval usable without a remote key

Expected result:

- [x] local / deterministic-compatible path works
- [x] OpenAI-compatible local path works
- [x] remote OpenAI path behavior is tested
- [x] provider mode is visible in metadata and logs where relevant

---

## 12. Extraction quality verification

- [x] heuristic entity extraction is stable
- [x] generic alias noise is reduced
- [x] phrase trimming rules behave as intended
- [x] relation extraction prefers explicit pattern matches
- [x] cross-sentence relation mixing is suppressed
- [x] fallback adjacency relations remain weaker than explicit matches

Expected result:

- [x] entity aliases look reasonable
- [x] relation types match expected patterns
- [x] obvious false positives are not produced in regression tests

---

## 13. Retrieval quality verification

- [x] reranking is active
- [x] naive reranking is stable
- [x] local graph reranking is stable
- [x] hybrid reranking is stable
- [x] score breakdown metadata is present
- [x] relation-supported chunks outrank weaker unsupported chunks when appropriate

Expected result:

- [x] ranking is explainable
- [x] relation evidence influences hybrid ranking
- [x] payload limits remain enforced

---

## 14. Limits and safety controls

- [x] max vector candidates are enforced
- [x] max graph hops are enforced
- [x] max return chunk count is enforced
- [x] max return entity count is enforced
- [x] malformed requests fail predictably
- [x] invalid UUID inputs fail predictably
- [x] oversized strings fail predictably
- [x] metadata validation rejects unsupported structures
- [x] no arbitrary SQL execution surface is exposed
- [x] no arbitrary Cypher execution surface is exposed

Expected result:

- [x] bounded cost for retrieval operations
- [x] bounded response size
- [x] safe failure behavior for malformed input

---

## 15. Logging and observability

- [x] structured JSON logs are enabled
- [x] request correlation fields are present
- [x] auth and app logs can be followed for a single request
- [x] DB operation spans are logged where expected
- [x] sensitive values remain redacted

Expected log fields include:

- [x] `timestamp`
- [x] `level`
- [x] `logger`
- [x] `message`
- [x] `request_id`
- [x] `authenticated_identity`
- [x] `event`
- [ ] `duration_ms`

---

## 16. Public surface freeze

Freeze these tool names for `v0.1.0`:

- [x] `health_check`
- [x] `index_status`
- [x] `graph_status`
- [x] `document_ingest`
- [x] `document_reingest`
- [x] `document_delete`
- [x] `graph_refresh`
- [x] `retrieve_naive`
- [x] `entity_search`
- [x] `entity_expand`
- [x] `retrieve_local_graph`
- [x] `retrieve_hybrid`
- [x] `source_trace`

Freeze these resource URI templates for `v0.1.0`:

- [ ] `graphrag://document/{document_id}`
- [ ] `graphrag://chunk/{chunk_id}`
- [ ] `graphrag://entity/{entity_id}`
- [ ] `graphrag://retrieval/{retrieval_id}`
- [ ] `graphrag://graph/status`

- [x] schema snapshot file exists
  - [x] `schemas/mcp/public-surface.v0.1.0.json`
- [x] runtime tool listing matches frozen snapshot
- [x] runtime auth header expectations match frozen snapshot

---

## 17. Final sign-off

Release is ready only if all of the following are true:

- [x] lint is green
- [x] tests are green
- [x] clean-volume compose startup is green
- [x] smoke is green
- [x] explicit schema apply is available
- [x] explicit graph bootstrap / rebuild is available
- [x] AGE projection is working
- [x] retrieval and trace flows are working
- [x] docs match verified commands
- [x] public tool/resource surface is frozen

If any box above is unchecked, do not tag `v0.1.0`.
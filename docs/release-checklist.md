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
- [ ] committed files match the intended public milestone
- [ ] placeholder or local-only assets are clearly identified
- [ ] docs reflect the current implemented behavior

---

## 2. Environment preparation

- [ ] `.env.example` is current
- [ ] `.env.production.example` is current
- [ ] required environment variables are documented
- [ ] local TLS certificate instructions are valid
- [ ] local compose project naming is documented
  - [ ] `COMPOSE_PROJECT_NAME=pggraphrag_mcp`
- [ ] verified local public endpoint is documented
  - [ ] `https://localhost:9443/mcp`

---

## 3. Build and static validation

Run these checks from a clean checkout.

- [ ] `uv run ruff check .`
- [ ] `python -m compileall src scripts tests`
- [ ] `uv run pytest`

Expected result:

- [ ] all lint checks pass
- [ ] all imports compile
- [ ] full test suite passes

---

## 4. CI validation

- [ ] CI workflow file exists
  - [ ] `.github/workflows/ci.yml`
- [ ] CI has a dedicated `lint` job
- [ ] CI has a dedicated `test` job
- [ ] CI has a dedicated `smoke` job
- [ ] CI uses Python 3.12
- [ ] CI uses `uv`
- [ ] CI job structure matches repository docs

Expected result:

- [ ] lint workflow is green
- [ ] test workflow is green
- [ ] smoke workflow configuration is valid

---

## 5. Clean environment bring-up

Validate from a clean local environment.

- [ ] copy environment file
  - [ ] `cp .env.example .env`
- [ ] generate or provide local TLS certificate and key
- [ ] remove stale database volume when testing a clean bring-up
  - [ ] `docker volume rm pggraphrag_db_data`
- [ ] start the full stack
  - [ ] `COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-up`

Expected result:

- [ ] all services start
- [ ] all services become healthy
- [ ] proxy is reachable
- [ ] private app is not directly exposed
- [ ] database is not directly exposed

---

## 6. Authentication verification

- [ ] unauthenticated `/mcp` request is rejected
- [ ] authenticated `/mcp` request is accepted
- [ ] forwarded auth headers are present as expected
- [ ] auth logs can be correlated with app logs via request context

Expected result:

- [ ] bearer token missing -> reject
- [ ] bearer token valid -> allow

---

## 7. Database and schema verification

- [ ] schema apply script exists
  - [ ] `scripts/apply_schema.py`
- [ ] schema apply dry-run / check-only path works
- [ ] explicit schema apply path works
- [ ] `pgvector` extension is available
- [ ] `Apache AGE` extension is available
- [ ] canonical relational tables exist
  - [ ] `document`
  - [ ] `chunk`
  - [ ] `entity`
  - [ ] `chunk_entity`
  - [ ] `relation_fact`
  - [ ] `ingestion_job`
  - [ ] `retrieval_log`
  - [ ] `graph_refresh_log`

Recommended verification commands:

- [ ] `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --check-only`
- [ ] `uv run python scripts/apply_schema.py --database-url "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag" --verbose`

---

## 8. Graph bootstrap and rebuild verification

- [ ] graph bootstrap / rebuild script exists
  - [ ] `scripts/bootstrap_graph.py`
- [ ] ops automation script exists
  - [ ] `scripts/ops_automation.py`
- [x] packaged ops automation entrypoint exists
  - [x] `pggraphrag-mcp-ops`
  - [x] packaging/runtime import issue is resolved for `uv run pggraphrag-mcp-ops`
  - [ ] host-runtime caveat is documented: the packaged CLI still needs a host-reachable `PGGRAPHRAG_MCP_DATABASE_URL` when run outside the compose network
- [ ] graph status command works
- [ ] document-scoped graph refresh works
- [ ] full graph rebuild works
- [ ] full graph rebuild is repeatable
- [ ] graph refresh metadata is recorded
- [ ] ops automation status command works
- [ ] ops automation readiness check works
- [ ] ops automation wait-ready flow works
- [ ] ops automation bootstrap with readiness wait works
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

- [ ] graph exists
- [ ] projected node counts are non-zero after ingest
- [ ] projected edge counts are non-zero after ingest
- [ ] readiness checks report the graph as ready after successful bootstrap
- [ ] operator automation can run status, bootstrap, and readiness validation without manual command stitching
- [ ] packaged host-side automation uses a DSN that is valid from the host runtime, not only from inside compose

---

## 9. Retrieval and trace verification

Verify the public GraphRAG flows end to end.

- [ ] `retrieve_naive` works
- [ ] `retrieve_local_graph` works
- [ ] `retrieve_hybrid` works
- [ ] `entity_search` works
- [ ] `entity_expand` works
- [ ] `source_trace` works
- [ ] responses remain JSON-safe
- [ ] responses include bounded payloads
- [ ] score breakdowns are present where expected

Expected result:

- [ ] supporting chunks are returned
- [ ] entities are returned
- [ ] relationships are returned
- [ ] sources are returned
- [ ] `retrieval_id` is returned
- [ ] source trace can be resolved from `retrieval_id`

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

- [ ] configured embedding provider is documented
- [ ] local fallback behavior is documented
- [ ] remote embedding provider behavior is documented
- [ ] remote mode requires API key as expected
- [ ] fallback mode keeps ingest and retrieval usable without a remote key

Expected result:

- [ ] local / deterministic-compatible path works
- [ ] OpenAI-compatible local path works
- [ ] remote OpenAI path behavior is tested
- [ ] provider mode is visible in metadata and logs where relevant

---

## 12. Extraction quality verification

- [ ] heuristic entity extraction is stable
- [ ] generic alias noise is reduced
- [ ] phrase trimming rules behave as intended
- [ ] relation extraction prefers explicit pattern matches
- [ ] cross-sentence relation mixing is suppressed
- [ ] fallback adjacency relations remain weaker than explicit matches

Expected result:

- [ ] entity aliases look reasonable
- [ ] relation types match expected patterns
- [ ] obvious false positives are not produced in regression tests

---

## 13. Retrieval quality verification

- [ ] reranking is active
- [ ] naive reranking is stable
- [ ] local graph reranking is stable
- [ ] hybrid reranking is stable
- [ ] score breakdown metadata is present
- [ ] relation-supported chunks outrank weaker unsupported chunks when appropriate

Expected result:

- [ ] ranking is explainable
- [ ] relation evidence influences hybrid ranking
- [ ] payload limits remain enforced

---

## 14. Limits and safety controls

- [ ] max vector candidates are enforced
- [ ] max graph hops are enforced
- [ ] max return chunk count is enforced
- [ ] max return entity count is enforced
- [ ] malformed requests fail predictably
- [ ] invalid UUID inputs fail predictably
- [ ] oversized strings fail predictably
- [ ] metadata validation rejects unsupported structures
- [ ] no arbitrary SQL execution surface is exposed
- [ ] no arbitrary Cypher execution surface is exposed

Expected result:

- [ ] bounded cost for retrieval operations
- [ ] bounded response size
- [ ] safe failure behavior for malformed input

---

## 15. Logging and observability

- [ ] structured JSON logs are enabled
- [ ] request correlation fields are present
- [ ] auth and app logs can be followed for a single request
- [ ] DB operation spans are logged where expected
- [ ] sensitive values remain redacted

Expected log fields include:

- [ ] `timestamp`
- [ ] `level`
- [ ] `logger`
- [ ] `message`
- [ ] `request_id`
- [ ] `authenticated_identity`
- [ ] `event`
- [ ] `duration_ms`

---

## 16. Public surface freeze

Freeze these tool names for `v0.1.0`:

- [ ] `health_check`
- [ ] `index_status`
- [ ] `graph_status`
- [ ] `document_ingest`
- [ ] `document_reingest`
- [ ] `document_delete`
- [ ] `graph_refresh`
- [ ] `rebuild_embeddings`
- [ ] `retrieve_naive`
- [ ] `entity_search`
- [ ] `entity_expand`
- [ ] `retrieve_local_graph`
- [ ] `retrieve_hybrid`
- [ ] `source_trace`

Freeze these resource URI templates for `v0.1.0`:

- [ ] `graphrag://document/{document_id}`
- [ ] `graphrag://chunk/{chunk_id}`
- [ ] `graphrag://entity/{entity_id}`
- [ ] `graphrag://retrieval/{retrieval_id}`
- [ ] `graphrag://graph/status`

- [ ] schema snapshot file exists
  - [ ] `schemas/mcp/public-surface.v0.1.0.json`
- [ ] runtime tool listing matches frozen snapshot
- [ ] runtime auth header expectations match frozen snapshot

---

## 17. Final sign-off

Release is ready only if all of the following are true:

- [ ] lint is green
- [ ] tests are green
- [ ] clean-volume compose startup is green
- [ ] smoke is green
- [ ] explicit schema apply is available
- [ ] explicit graph bootstrap / rebuild is available
- [ ] AGE projection is working
- [ ] retrieval and trace flows are working
- [ ] docs match verified commands
- [ ] public tool/resource surface is frozen

If any box above is unchecked, do not tag `v0.1.0`.
# Ticket status summary

This document summarizes the current completion state of the implementation tickets under `docs/tickets/`.

It is intended as a quick progress view that complements:

- `docs/implementation-plan.md`
- `docs/plan.yaml`
- `docs/release-checklist.md`

## Status legend

- `completed`
  - The ticket goal and done condition are satisfied by the current repository state.
- `completed_with_scope_adjustment`
  - The intended outcome is satisfied, but the exact file names or implementation shape differ from the original ticket wording.
- `mostly_completed`
  - The ticket is substantially implemented, but one or more verification or operational sign-off details remain.
- `open`
  - The ticket goal is not yet sufficiently implemented.

## Summary

| Ticket | Title | Status | Notes |
|---|---|---|---|
| T001 | Repository skeleton | completed | Repository structure, package layout, docs, env examples, and project metadata are present. |
| T002 | Compose topology | completed | Compose topology, networks, proxy-only host exposure, healthchecks, and dependency ordering are in place. |
| T003 | Environment and secrets | completed_with_scope_adjustment | Env examples and naming conventions are documented; helper behavior exists through docs and examples rather than a dedicated placeholder-population script. |
| T004 | PostgreSQL image with pgvector and Apache AGE | completed | Repository-owned PostgreSQL image with pgvector and Apache AGE is present and validated through runtime checks. |
| T005 | Schema migrations | completed | Canonical relational schema, indexes, and schema application flow are implemented. |
| T006 | AGE bootstrap and refresh | completed_with_scope_adjustment | Graph bootstrap and refresh behavior exists, but the functionality is consolidated into the existing schema/bootstrap tooling rather than matching every originally named script one-for-one. |
| T007 | HTTP app skeleton | completed | FastAPI-based remote MCP HTTP host, readiness route, auth header wiring, and config/logging setup are implemented. |
| T008 | MCP tools and resources schema | completed | Stable machine-readable public surface snapshot and resource URI templates are present. |
| T009 | Smoke test | completed | End-to-end smoke path exists and has been validated against the compose-backed HTTPS endpoint. |
| T010 | Document ingest | completed | Document ingestion, chunk persistence, metadata/hash persistence, and ingestion job tracking are implemented. |
| T011 | Embedding pipeline | completed | Embedding abstraction, OpenAI-compatible paths, persistence, retry handling, and fallback behavior are implemented. |
| T012 | Entity and relation extraction | completed | Entity extraction, alias handling, relation extraction, evidence linking, and regression tests are in place. |
| T013 | Graph refresh flow | completed | Relational-to-AGE projection, document-scoped refresh, and full rebuild flow are implemented. |
| T014 | Naive retrieval | completed | Query normalization, vector lookup, source-backed retrieval, and retrieval logging are implemented. |
| T015 | Entity search and expand | completed | Entity search, neighbor expansion, evidence links, and bounds are implemented. |
| T016 | Local graph retrieval | completed | Local-graph retrieval returns combined textual and relational support. |
| T017 | Hybrid retrieval and source trace | completed | Hybrid retrieval, retrieval IDs, source trace, and evidence-rich responses are implemented. |
| T018 | Limits and safety controls | completed | Input limits, retrieval bounds, predictable validation failures, and no arbitrary SQL/Cypher surface are enforced. |
| T019 | Structured logging | mostly_completed | Structured JSON logs, request correlation, auth context, DB spans, and logging docs exist; final observability sign-off remains checklist-driven. |
| T020 | Release readiness | completed_with_scope_adjustment | Release-readiness docs, integration tests, smoke validation, and public surface freeze exist; `rebuild_embeddings` was explicitly removed from the `v0.1.0` surface instead of being shipped as a frozen tool. |

## Detailed notes

### T001 Repository skeleton
Status: `completed`

Implemented outcomes:
- top-level repository structure exists
- Python package exists under `src/pggraphrag_mcp`
- project metadata and docs are present
- baseline test/build/compose commands are represented

### T002 Compose topology
Status: `completed`

Implemented outcomes:
- core compose file for app and DB
- overlay compose file for proxy and auth
- internal and edge communication boundaries
- only the proxy publishes host-facing ports
- healthchecks and startup ordering are defined

### T003 Environment and secrets
Status: `completed_with_scope_adjustment`

Implemented outcomes:
- `.env.example`
- `.env.production.example`
- consistent `PGGRAPHRAG_MCP_` prefix
- environment variable documentation

Adjustment:
- the original ticket mentions a dedicated helper script for populating placeholders
- the repository currently satisfies the developer workflow primarily through documentation and example env files rather than a standalone helper utility

### T004 PostgreSQL image with pgvector and Apache AGE
Status: `completed`

Implemented outcomes:
- repository-owned PostgreSQL image
- pgvector support
- Apache AGE support
- runtime validation through bootstrap and status flows

### T005 Schema migrations
Status: `completed`

Implemented outcomes:
- canonical relational schema
- required indexes
- schema application tooling
- fresh database bootstrap path

### T006 AGE bootstrap and refresh
Status: `completed_with_scope_adjustment`

Implemented outcomes:
- graph bootstrap behavior
- graph refresh behavior
- idempotent graph lifecycle handling
- repeatable rebuild path

Adjustment:
- the exact standalone script names in the ticket are not all present as separate files
- equivalent behavior is implemented through the existing bootstrap/schema/ops tooling

### T007 HTTP app skeleton
Status: `completed`

Implemented outcomes:
- FastAPI/uvicorn HTTP host
- `/readyz`
- `/mcp`
- config loading
- structured logging setup
- auth context propagated from proxy headers

### T008 MCP tools and resources schema
Status: `completed`

Implemented outcomes:
- stable tool listing
- stable resource URI templates
- versioned public surface snapshot

### T009 Smoke test
Status: `completed`

Implemented outcomes:
- unauthorized request check
- authenticated health check
- authenticated minimal tool invocation
- seeded ingest
- hybrid retrieval
- source trace
- compose-backed HTTPS smoke validation

### T010 Document ingest
Status: `completed`

Implemented outcomes:
- `document_ingest`
- `document_reingest`
- `document_delete`
- canonical persistence of document and chunk state
- ingestion job tracking

### T011 Embedding pipeline
Status: `completed`

Implemented outcomes:
- embedding provider abstraction
- OpenAI-compatible provider path
- deterministic/local fallback path
- retry handling
- embedding persistence into chunk records

### T012 Entity and relation extraction
Status: `completed`

Implemented outcomes:
- entity extraction
- alias/canonicalization handling
- relation extraction
- evidence chunk linking
- regression coverage for extraction quality

### T013 Graph refresh flow
Status: `completed`

Implemented outcomes:
- canonical relational facts projected into AGE
- document-scoped refresh
- full rebuild
- graph refresh logging and auditability

### T014 Naive retrieval
Status: `completed`

Implemented outcomes:
- normalized query handling
- vector-backed candidate retrieval
- source-backed results
- retrieval metadata logging

### T015 Entity search and expand
Status: `completed`

Implemented outcomes:
- entity search
- entity expansion
- graph hop and result limits
- evidence references back to chunks and documents

### T016 Local graph retrieval
Status: `completed`

Implemented outcomes:
- naive retrieval candidates augmented with graph context
- combined textual and relational support in one response

### T017 Hybrid retrieval and source trace
Status: `completed`

Implemented outcomes:
- hybrid ranking and aggregation
- retrieval IDs
- traceable evidence bundles
- `source_trace`
- rich response payload shape

### T018 Limits and safety controls
Status: `completed`

Implemented outcomes:
- bounded vector candidates
- bounded graph hops
- bounded response size
- predictable validation behavior
- no arbitrary SQL execution surface
- no arbitrary Cypher execution surface

### T019 Structured logging
Status: `mostly_completed`

Implemented outcomes:
- structured JSON logs
- request correlation IDs
- authenticated identity in logs
- DB span logging
- logging field documentation

Remaining nuance:
- final operational sign-off still depends on the release checklist and real-world observability review rather than only code presence

### T020 Release readiness
Status: `completed_with_scope_adjustment`

Implemented outcomes:
- integration tests
- release checklist
- docs quick start validation
- public surface freeze
- compose-backed smoke validation
- CI-equivalent local validation

Adjustment:
- the originally exposed `rebuild_embeddings` placeholder was removed from the `v0.1.0` public surface instead of being shipped as a frozen not-implemented tool
- this keeps the release surface internally consistent

## Totals

- `completed`: 16
- `completed_with_scope_adjustment`: 3
- `mostly_completed`: 1
- `open`: 0

## Practical interpretation

The ticket set is functionally consumed for `v0.1.0`.

What remains is mostly:
- final release judgment
- optional operational verification variants
- potential future work that was intentionally deferred from the `v0.1.0` surface

The most notable deferred item is:
- `rebuild_embeddings`
  - intentionally removed from the frozen `v0.1.0` tool surface
  - should be reconsidered in a later release if needed
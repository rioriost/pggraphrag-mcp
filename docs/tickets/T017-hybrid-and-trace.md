# T017 Hybrid retrieval and source trace

## Goal
Deliver the main GraphRAG retrieval path.

## Tasks
- Implement hybrid score aggregation
- Add `source_trace`
- Emit retrieval IDs and traceable evidence bundles
- Ensure response includes summary, chunks, entities, relationships, and sources

## Done when
- `retrieve_hybrid` and `source_trace` work end-to-end on seeded examples

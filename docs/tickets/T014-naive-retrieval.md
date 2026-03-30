# T014 Naive retrieval

## Goal
Provide vector-only retrieval baseline.

## Tasks
- Normalize query
- Embed query
- Fetch top-k chunks via pgvector
- Return supporting chunks and sources
- Log retrieval metadata

## Done when
- `retrieve_naive` returns stable, source-backed results for a seeded corpus

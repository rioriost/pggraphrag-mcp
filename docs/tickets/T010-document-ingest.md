# T010 Document ingest

## Goal
Persist documents and chunks into canonical storage.

## Tasks
- Implement `document_ingest`
- Store raw metadata, hashes, and chunk records
- Define reingest semantics for duplicate content
- Capture ingestion job state transitions

## Done when
- A sample document is persisted as one document row and N chunk rows

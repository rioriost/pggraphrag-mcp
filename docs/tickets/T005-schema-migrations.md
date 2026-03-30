# T005 Schema migrations

## Goal
Create canonical relational schema.

## Tasks
- Add migration files for document, chunk, entity, chunk_entity, relation_fact, ingestion_job, retrieval_log
- Add indexes for document lookup, chunk retrieval, and foreign keys
- Add vector index strategy placeholder matching chosen embedding dimensions

## Done when
- Fresh database can be migrated from zero to current schema with one command

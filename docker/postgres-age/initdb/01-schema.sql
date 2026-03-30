BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;

LOAD 'age';
SET search_path = public, ag_catalog;

CREATE TABLE IF NOT EXISTS schema_version (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_version (version)
VALUES ('0001_initial')
ON CONFLICT (version) DO NOTHING;

CREATE TABLE IF NOT EXISTS document (
    document_id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    source_uri text NOT NULL,
    title text NOT NULL,
    mime_type text NOT NULL,
    content_hash text NOT NULL,
    status text NOT NULL,
    content text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk (
    chunk_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES document(document_id) ON DELETE CASCADE,
    chunk_no integer NOT NULL,
    text text NOT NULL,
    token_count integer NOT NULL DEFAULT 0,
    embedding vector(1536),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_no)
);

CREATE TABLE IF NOT EXISTS entity (
    entity_id uuid PRIMARY KEY,
    canonical_name text NOT NULL,
    entity_type text NOT NULL,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk_entity (
    chunk_id uuid NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
    entity_id uuid NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    mention_count integer NOT NULL DEFAULT 1,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (chunk_id, entity_id)
);

CREATE TABLE IF NOT EXISTS relation_fact (
    relation_fact_id uuid PRIMARY KEY,
    source_entity_id uuid NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    target_entity_id uuid NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    relation_type text NOT NULL,
    weight double precision NOT NULL DEFAULT 1.0,
    evidence_chunk_id uuid REFERENCES chunk(chunk_id) ON DELETE SET NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_job (
    ingestion_job_id uuid PRIMARY KEY,
    document_id uuid REFERENCES document(document_id) ON DELETE SET NULL,
    status text NOT NULL,
    failure_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_log (
    retrieval_id uuid PRIMARY KEY,
    query_text text NOT NULL,
    mode text NOT NULL,
    returned_source_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    timings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS graph_refresh_log (
    graph_refresh_id uuid PRIMARY KEY,
    graph_name text NOT NULL,
    scope text NOT NULL,
    document_id uuid REFERENCES document(document_id) ON DELETE CASCADE,
    node_count integer NOT NULL DEFAULT 0,
    edge_count integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_source_uri
    ON document (source_uri);

CREATE INDEX IF NOT EXISTS idx_chunk_document_id
    ON chunk (document_id);

CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
    ON chunk
    USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_entity_canonical_name
    ON entity (canonical_name);

CREATE INDEX IF NOT EXISTS idx_relation_fact_source_target
    ON relation_fact (source_entity_id, target_entity_id);

CREATE INDEX IF NOT EXISTS idx_graph_refresh_log_document_id
    ON graph_refresh_log (document_id);

CREATE INDEX IF NOT EXISTS idx_graph_refresh_log_graph_name_created_at
    ON graph_refresh_log (graph_name, created_at DESC);

COMMIT;

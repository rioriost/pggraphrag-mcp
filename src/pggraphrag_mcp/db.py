from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import psycopg
from psycopg import sql

LOGGER = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIMENSIONS = 1536


@dataclass(slots=True, frozen=True)
class DatabaseStatus:
    database: str
    current_user: str
    vector_extension_installed: bool
    age_extension_installed: bool
    age_graph_exists: bool
    schema_version_table_exists: bool
    document_table_exists: bool
    chunk_table_exists: bool
    entity_table_exists: bool
    relation_fact_table_exists: bool
    chunk_entity_table_exists: bool
    ingestion_job_table_exists: bool
    retrieval_log_table_exists: bool
    graph_refresh_log_table_exists: bool
    document_content_column_exists: bool

    @property
    def is_ready(self) -> bool:
        return all(
            [
                self.vector_extension_installed,
                self.age_extension_installed,
                self.age_graph_exists,
                self.schema_version_table_exists,
                self.document_table_exists,
                self.chunk_table_exists,
                self.entity_table_exists,
                self.relation_fact_table_exists,
                self.chunk_entity_table_exists,
                self.ingestion_job_table_exists,
                self.retrieval_log_table_exists,
                self.graph_refresh_log_table_exists,
                self.document_content_column_exists,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "current_user": self.current_user,
            "vector_extension_installed": self.vector_extension_installed,
            "age_extension_installed": self.age_extension_installed,
            "age_graph_exists": self.age_graph_exists,
            "schema_version_table_exists": self.schema_version_table_exists,
            "document_table_exists": self.document_table_exists,
            "chunk_table_exists": self.chunk_table_exists,
            "entity_table_exists": self.entity_table_exists,
            "relation_fact_table_exists": self.relation_fact_table_exists,
            "chunk_entity_table_exists": self.chunk_entity_table_exists,
            "ingestion_job_table_exists": self.ingestion_job_table_exists,
            "retrieval_log_table_exists": self.retrieval_log_table_exists,
            "graph_refresh_log_table_exists": self.graph_refresh_log_table_exists,
            "document_content_column_exists": self.document_content_column_exists,
            "is_ready": self.is_ready,
        }


class DatabaseBootstrapError(RuntimeError):
    """Raised when database bootstrap actions fail."""


class Database:
    """
    Lightweight PostgreSQL helper used by the HTTP app and scripts.

    Responsibilities:
    - open short-lived psycopg connections
    - ensure required extensions/schema objects exist
    - expose status checks for health and smoke tests
    """

    def __init__(
        self,
        dsn: str,
        *,
        age_graph_name: str,
        app_name: str = "pggraphrag-mcp",
        embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    ) -> None:
        self._dsn = dsn
        self._age_graph_name = age_graph_name
        self._app_name = app_name
        self._embedding_dimensions = embedding_dimensions

    @contextmanager
    def connection(
        self, *, autocommit: bool = False
    ) -> Iterator[psycopg.Connection[Any]]:
        conn = psycopg.connect(
            self._dsn,
            autocommit=autocommit,
            application_name=self._app_name,
        )
        try:
            yield conn
        finally:
            conn.close()

    def ping(self) -> bool:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            value = cur.fetchone()
        return bool(value and value[0] == 1)

    def bootstrap(self) -> None:
        """
        Create required extensions, tables, indexes, and the AGE graph.

        This method is intentionally idempotent so it can be called repeatedly
        from compose startup hooks or management scripts.
        """
        try:
            with self.connection(autocommit=True) as conn:
                self._ensure_extensions(conn)
                self._ensure_tables(conn)
                self._ensure_indexes(conn)
                self._ensure_age_graph(conn)
        except psycopg.Error as exc:
            LOGGER.exception("Database bootstrap failed")
            raise DatabaseBootstrapError(str(exc)) from exc

    def get_status(self) -> DatabaseStatus:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            db_name, current_user = cur.fetchone()

            vector_installed = self._extension_exists(cur, "vector")
            age_installed = self._extension_exists(cur, "age")
            age_graph_exists = self._age_graph_exists(cur, self._age_graph_name)

            schema_version_exists = self._table_exists(cur, "public", "schema_version")
            document_exists = self._table_exists(cur, "public", "document")
            chunk_exists = self._table_exists(cur, "public", "chunk")
            entity_exists = self._table_exists(cur, "public", "entity")
            relation_fact_exists = self._table_exists(cur, "public", "relation_fact")
            chunk_entity_exists = self._table_exists(cur, "public", "chunk_entity")
            ingestion_job_exists = self._table_exists(cur, "public", "ingestion_job")
            retrieval_log_exists = self._table_exists(cur, "public", "retrieval_log")
            graph_refresh_log_exists = self._table_exists(
                cur, "public", "graph_refresh_log"
            )
            document_content_exists = self._column_exists(
                cur,
                "public",
                "document",
                "content",
            )

        return DatabaseStatus(
            database=db_name,
            current_user=current_user,
            vector_extension_installed=vector_installed,
            age_extension_installed=age_installed,
            age_graph_exists=age_graph_exists,
            schema_version_table_exists=schema_version_exists,
            document_table_exists=document_exists,
            chunk_table_exists=chunk_exists,
            entity_table_exists=entity_exists,
            relation_fact_table_exists=relation_fact_exists,
            chunk_entity_table_exists=chunk_entity_exists,
            ingestion_job_table_exists=ingestion_job_exists,
            retrieval_log_table_exists=retrieval_log_exists,
            graph_refresh_log_table_exists=graph_refresh_log_exists,
            document_content_column_exists=document_content_exists,
        )

    def _ensure_extensions(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS age")
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = public, ag_catalog")

    def _ensure_tables(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                INSERT INTO schema_version (version)
                VALUES ('0001_initial')
                ON CONFLICT (version) DO NOTHING
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document (
                    document_id uuid PRIMARY KEY,
                    tenant_id text NOT NULL,
                    source_uri text NOT NULL,
                    title text NOT NULL,
                    mime_type text NOT NULL,
                    content_hash text NOT NULL,
                    status text NOT NULL,
                    content text NOT NULL DEFAULT '',
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE document
                ADD COLUMN IF NOT EXISTS content text NOT NULL DEFAULT ''
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunk (
                    chunk_id uuid PRIMARY KEY,
                    document_id uuid NOT NULL REFERENCES document(document_id) ON DELETE CASCADE,
                    chunk_no integer NOT NULL,
                    text text NOT NULL,
                    token_count integer NOT NULL DEFAULT 0,
                    embedding vector({self._embedding_dimensions}),
                    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    UNIQUE (document_id, chunk_no)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entity (
                    entity_id uuid PRIMARY KEY,
                    canonical_name text NOT NULL,
                    entity_type text NOT NULL,
                    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
                    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_entity (
                    chunk_id uuid NOT NULL REFERENCES chunk(chunk_id) ON DELETE CASCADE,
                    entity_id uuid NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                    mention_count integer NOT NULL DEFAULT 1,
                    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                    PRIMARY KEY (chunk_id, entity_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS relation_fact (
                    relation_fact_id uuid PRIMARY KEY,
                    source_entity_id uuid NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                    target_entity_id uuid NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
                    relation_type text NOT NULL,
                    weight double precision NOT NULL DEFAULT 1.0,
                    evidence_chunk_id uuid REFERENCES chunk(chunk_id) ON DELETE SET NULL,
                    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_job (
                    ingestion_job_id uuid PRIMARY KEY,
                    document_id uuid REFERENCES document(document_id) ON DELETE SET NULL,
                    status text NOT NULL,
                    failure_reason text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_log (
                    retrieval_id uuid PRIMARY KEY,
                    query_text text NOT NULL,
                    mode text NOT NULL,
                    returned_source_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
                    timings jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
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
                )
                """
            )

    def _ensure_indexes(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_document_tenant_content_hash
                ON document (tenant_id, content_hash)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_document_source_uri
                ON document (source_uri)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunk_document_id
                ON chunk (document_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
                ON chunk
                USING ivfflat (embedding vector_cosine_ops)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunk_entity_entity_id
                ON chunk_entity (entity_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_entity_canonical_name
                ON entity (canonical_name)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_relation_fact_source_target
                ON relation_fact (source_entity_id, target_entity_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_relation_fact_evidence_chunk_id
                ON relation_fact (evidence_chunk_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_retrieval_log_created_at
                ON retrieval_log (created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_graph_refresh_log_created_at
                ON graph_refresh_log (created_at DESC)
                """
            )

    def _ensure_age_graph(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = public, ag_catalog")

            if not self._age_graph_exists(cur, self._age_graph_name):
                query = sql.SQL("SELECT create_graph(%s)")
                cur.execute(query, (self._age_graph_name,))

    @staticmethod
    def _extension_exists(cur: psycopg.Cursor[Any], extension_name: str) -> bool:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_extension
                WHERE extname = %s
            )
            """,
            (extension_name,),
        )
        row = cur.fetchone()
        return bool(row and row[0])

    @staticmethod
    def _table_exists(
        cur: psycopg.Cursor[Any], schema_name: str, table_name: str
    ) -> bool:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s
            )
            """,
            (schema_name, table_name),
        )
        row = cur.fetchone()
        return bool(row and row[0])

    @staticmethod
    def _column_exists(
        cur: psycopg.Cursor[Any],
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> bool:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = %s
            )
            """,
            (schema_name, table_name, column_name),
        )
        row = cur.fetchone()
        return bool(row and row[0])

    @staticmethod
    def _age_graph_exists(cur: psycopg.Cursor[Any], graph_name: str) -> bool:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM ag_catalog.ag_graph
                WHERE name = %s
            )
            """,
            (graph_name,),
        )
        row = cur.fetchone()
        return bool(row and row[0])

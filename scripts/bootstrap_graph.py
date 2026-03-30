from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row


def utc_now() -> datetime:
    return datetime.now(UTC)


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip()
    return normalized if normalized else default


def require_env(name: str) -> str:
    value = env(name)
    if value is None:
        raise RuntimeError(f"{name} is required")
    return value


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def cypher_string_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    age_graph_name: str
    app_name: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=require_env("PGGRAPHRAG_MCP_DATABASE_URL"),
            age_graph_name=env("PGGRAPHRAG_MCP_AGE_GRAPH_NAME", "pggraphrag_memory")
            or "pggraphrag_memory",
            app_name=env("PGGRAPHRAG_MCP_APP_NAME", "pggraphrag-mcp")
            or "pggraphrag-mcp",
            log_level=env("PGGRAPHRAG_MCP_LOG_LEVEL", "INFO") or "INFO",
        )


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "timestamp": utc_now().isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    print(json_dumps(payload), file=sys.stderr)


class GraphBootstrapError(RuntimeError):
    """Raised when AGE graph bootstrap or rebuild fails."""


class GraphBootstrapManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def connect(self, *, autocommit: bool = False) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self.settings.database_url,
            row_factory=dict_row,
            autocommit=autocommit,
            application_name=f"{self.settings.app_name}-bootstrap-graph",
        )

    def bootstrap(self, *, full_rebuild: bool = False) -> dict[str, Any]:
        started_at = utc_now()
        graph_name = self.settings.age_graph_name

        with self.connect() as conn:
            with conn.transaction():
                self._ensure_age_loaded(conn)
                self._ensure_graph_exists(conn, graph_name)

                if full_rebuild:
                    self._truncate_graph(conn, graph_name)

                counts = self._project_all_documents(conn, graph_name)

                refresh_log_id = self._insert_graph_refresh_log(
                    conn,
                    graph_name=graph_name,
                    scope="full",
                    document_id=None,
                    node_count=counts["node_count"],
                    edge_count=counts["edge_count"],
                    status="completed",
                    metadata={
                        "full_rebuild": full_rebuild,
                        "projected_documents": counts["projected_documents"],
                        "projected_chunks": counts["projected_chunks"],
                        "projected_entities": counts["projected_entities"],
                        "projected_relations": counts["projected_relations"],
                        "projected_mentions": counts["projected_mentions"],
                    },
                )

        result = {
            "status": "completed",
            "graph_name": graph_name,
            "scope": "full",
            "full_rebuild": full_rebuild,
            "graph_refresh_id": str(refresh_log_id),
            "started_at": started_at.isoformat(),
            "finished_at": utc_now().isoformat(),
            **counts,
        }
        log_event("graph_bootstrap_completed", **result)
        return result

    def bootstrap_document(self, document_id: uuid.UUID) -> dict[str, Any]:
        started_at = utc_now()
        graph_name = self.settings.age_graph_name

        with self.connect() as conn:
            with conn.transaction():
                self._ensure_age_loaded(conn)
                self._ensure_graph_exists(conn, graph_name)
                self._delete_document_projection(conn, graph_name, document_id)

                counts = self._project_document(conn, graph_name, document_id)

                refresh_log_id = self._insert_graph_refresh_log(
                    conn,
                    graph_name=graph_name,
                    scope="document",
                    document_id=document_id,
                    node_count=counts["node_count"],
                    edge_count=counts["edge_count"],
                    status="completed",
                    metadata={
                        "full_rebuild": False,
                        "projected_documents": counts["projected_documents"],
                        "projected_chunks": counts["projected_chunks"],
                        "projected_entities": counts["projected_entities"],
                        "projected_relations": counts["projected_relations"],
                        "projected_mentions": counts["projected_mentions"],
                    },
                )

        result = {
            "status": "completed",
            "graph_name": graph_name,
            "scope": "document",
            "document_id": str(document_id),
            "full_rebuild": False,
            "graph_refresh_id": str(refresh_log_id),
            "started_at": started_at.isoformat(),
            "finished_at": utc_now().isoformat(),
            **counts,
        }
        log_event("graph_document_bootstrap_completed", **result)
        return result

    def status(self) -> dict[str, Any]:
        graph_name = self.settings.age_graph_name
        with self.connect() as conn:
            self._ensure_age_loaded(conn)
            graph_exists = self._graph_exists(conn, graph_name)
            node_count = (
                self._count_graph_nodes(conn, graph_name) if graph_exists else 0
            )
            edge_count = (
                self._count_graph_edges(conn, graph_name) if graph_exists else 0
            )
            latest_refresh = self._latest_graph_refresh(conn, graph_name)

        result = {
            "graph_name": graph_name,
            "graph_exists": graph_exists,
            "node_count": node_count,
            "edge_count": edge_count,
            "latest_refresh": latest_refresh,
        }
        log_event("graph_status_checked", **result)
        return result

    def _ensure_age_loaded(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS age")
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = public, ag_catalog")

    def _graph_exists(self, conn: psycopg.Connection[Any], graph_name: str) -> bool:
        with conn.cursor() as cur:
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
        return bool(row and row["exists"])

    def _ensure_graph_exists(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
    ) -> None:
        if self._graph_exists(conn, graph_name):
            return

        with conn.cursor() as cur:
            cur.execute("SELECT ag_catalog.create_graph(%s)", (graph_name,))
        log_event("graph_created", graph_name=graph_name)

    def _execute_cypher(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        query: str,
    ) -> None:
        query_text = query.strip().replace("$$", "\\$\\$")
        graph_name_literal = cypher_string_literal(graph_name)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM ag_catalog.cypher(
                    {graph_name_literal},
                    $$ {query_text} $$
                ) AS (result ag_catalog.agtype)
                """
            )

    def _truncate_graph(self, conn: psycopg.Connection[Any], graph_name: str) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            """
            MATCH (n)
            DETACH DELETE n
            RETURN 1
            """,
        )
        log_event("graph_truncated", graph_name=graph_name)

    def _delete_document_projection(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        document_id: uuid.UUID,
    ) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MATCH (d:Document {{document_id: {cypher_string_literal(str(document_id))}}})
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
            DETACH DELETE d, c
            RETURN 1
            """,
        )

    def _project_all_documents(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
    ) -> dict[str, int]:
        document_ids = self._list_document_ids(conn)
        aggregate = self._empty_counts()

        for document_id in document_ids:
            counts = self._project_document(conn, graph_name, document_id)
            for key, value in counts.items():
                aggregate[key] += value

        return aggregate

    def _project_document(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        document_id: uuid.UUID,
    ) -> dict[str, int]:
        document = self._get_document(conn, document_id)
        if document is None:
            raise GraphBootstrapError(f"Document not found: {document_id}")

        chunks = self._get_chunks_for_document(conn, document_id)
        entities = self._entities_for_document(conn, document_id)
        mentions = self._chunk_entity_rows_for_document(conn, document_id)
        relations = self._relation_rows_for_document(conn, document_id)

        self._upsert_document_node(conn, graph_name, document)
        for chunk in chunks:
            self._upsert_chunk_node(conn, graph_name, chunk)
            self._upsert_document_chunk_edge(
                conn, graph_name, document_id, chunk["chunk_id"]
            )

        seen_entity_ids: set[uuid.UUID] = set()
        for entity in entities:
            entity_id = entity["entity_id"]
            if entity_id in seen_entity_ids:
                continue
            self._upsert_entity_node(conn, graph_name, entity)
            seen_entity_ids.add(entity_id)

        for mention in mentions:
            self._upsert_mentions_edge(
                conn,
                graph_name,
                mention["chunk_id"],
                mention["entity_id"],
                int(mention["mention_count"]),
            )

        for relation in relations:
            self._upsert_relation_edge(conn, graph_name, relation)

        return {
            "projected_documents": 1,
            "projected_chunks": len(chunks),
            "projected_entities": len(seen_entity_ids),
            "projected_relations": len(relations),
            "projected_mentions": len(mentions),
            "node_count": 1 + len(chunks) + len(seen_entity_ids),
            "edge_count": len(chunks) + len(mentions) + len(relations),
        }

    def _list_document_ids(self, conn: psycopg.Connection[Any]) -> list[uuid.UUID]:
        with conn.cursor() as cur:
            cur.execute("SELECT document_id FROM document ORDER BY created_at")
            rows = cur.fetchall()
        return [row["document_id"] for row in rows]

    def _get_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    document_id,
                    tenant_id,
                    source_uri,
                    title,
                    mime_type,
                    content_hash,
                    status
                FROM document
                WHERE document_id = %s
                """,
                (document_id,),
            )
            return cur.fetchone()

    def _get_chunks_for_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    chunk_id,
                    document_id,
                    chunk_no,
                    text
                FROM chunk
                WHERE document_id = %s
                ORDER BY chunk_no
                """,
                (document_id,),
            )
            return list(cur.fetchall())

    def _entities_for_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    e.entity_id,
                    e.canonical_name,
                    e.entity_type
                FROM chunk c
                JOIN chunk_entity ce
                  ON ce.chunk_id = c.chunk_id
                JOIN entity e
                  ON e.entity_id = ce.entity_id
                WHERE c.document_id = %s
                ORDER BY e.canonical_name
                """,
                (document_id,),
            )
            return list(cur.fetchall())

    def _chunk_entity_rows_for_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ce.chunk_id,
                    ce.entity_id,
                    ce.mention_count
                FROM chunk_entity ce
                JOIN chunk c
                  ON c.chunk_id = ce.chunk_id
                WHERE c.document_id = %s
                """,
                (document_id,),
            )
            return list(cur.fetchall())

    def _relation_rows_for_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    rf.relation_fact_id,
                    rf.source_entity_id,
                    rf.target_entity_id,
                    rf.relation_type,
                    rf.weight,
                    rf.evidence_chunk_id
                FROM relation_fact rf
                JOIN chunk c
                  ON c.chunk_id = rf.evidence_chunk_id
                WHERE c.document_id = %s
                ORDER BY rf.created_at
                """,
                (document_id,),
            )
            return list(cur.fetchall())

    def _upsert_document_node(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        document: dict[str, Any],
    ) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MERGE (d:Document {{document_id: {cypher_string_literal(str(document["document_id"]))}}})
            SET d.title = {cypher_string_literal(str(document["title"]))},
                d.source_uri = {cypher_string_literal(str(document["source_uri"]))},
                d.tenant_id = {cypher_string_literal(str(document["tenant_id"]))},
                d.status = {cypher_string_literal(str(document["status"]))}
            RETURN 1
            """,
        )

    def _upsert_chunk_node(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        chunk: dict[str, Any],
    ) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MERGE (c:Chunk {{chunk_id: {cypher_string_literal(str(chunk["chunk_id"]))}}})
            SET c.chunk_no = {int(chunk["chunk_no"])},
                c.text = {cypher_string_literal(str(chunk["text"]))},
                c.document_id = {cypher_string_literal(str(chunk["document_id"]))}
            RETURN 1
            """,
        )

    def _upsert_document_chunk_edge(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        document_id: uuid.UUID,
        chunk_id: uuid.UUID,
    ) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MATCH (d:Document {{document_id: {cypher_string_literal(str(document_id))}}})
            MATCH (c:Chunk {{chunk_id: {cypher_string_literal(str(chunk_id))}}})
            MERGE (d)-[:HAS_CHUNK]->(c)
            RETURN 1
            """,
        )

    def _upsert_entity_node(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        entity: dict[str, Any],
    ) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MERGE (e:Entity {{entity_id: {cypher_string_literal(str(entity["entity_id"]))}}})
            SET e.canonical_name = {cypher_string_literal(str(entity["canonical_name"]))},
                e.entity_type = {cypher_string_literal(str(entity["entity_type"]))}
            RETURN 1
            """,
        )

    def _upsert_mentions_edge(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        chunk_id: uuid.UUID,
        entity_id: uuid.UUID,
        mention_count: int,
    ) -> None:
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MATCH (c:Chunk {{chunk_id: {cypher_string_literal(str(chunk_id))}}})
            MATCH (e:Entity {{entity_id: {cypher_string_literal(str(entity_id))}}})
            MERGE (c)-[r:MENTIONS]->(e)
            SET r.mention_count = {int(mention_count)}
            RETURN 1
            """,
        )

    def _upsert_relation_edge(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
        relation: dict[str, Any],
    ) -> None:
        evidence_chunk_literal = (
            cypher_string_literal(str(relation["evidence_chunk_id"]))
            if relation["evidence_chunk_id"] is not None
            else "null"
        )
        self._execute_cypher(
            conn,
            graph_name,
            f"""
            MATCH (source:Entity {{entity_id: {cypher_string_literal(str(relation["source_entity_id"]))}}})
            MATCH (target:Entity {{entity_id: {cypher_string_literal(str(relation["target_entity_id"]))}}})
            MERGE (source)-[r:RELATES_TO {{relation_fact_id: {cypher_string_literal(str(relation["relation_fact_id"]))}}}]->(target)
            SET r.relation_type = {cypher_string_literal(str(relation["relation_type"]))},
                r.weight = {float(relation["weight"])},
                r.evidence_chunk_id = {evidence_chunk_literal}
            RETURN 1
            """,
        )

    def _insert_graph_refresh_log(
        self,
        conn: psycopg.Connection[Any],
        *,
        graph_name: str,
        scope: str,
        document_id: uuid.UUID | None,
        node_count: int,
        edge_count: int,
        status: str,
        metadata: dict[str, Any],
    ) -> uuid.UUID:
        graph_refresh_id = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_refresh_log (
                    graph_refresh_id,
                    graph_name,
                    scope,
                    document_id,
                    node_count,
                    edge_count,
                    status,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    graph_refresh_id,
                    graph_name,
                    scope,
                    document_id,
                    node_count,
                    edge_count,
                    status,
                    json_dumps(metadata),
                    utc_now(),
                    utc_now(),
                ),
            )
        return graph_refresh_id

    def _latest_graph_refresh(
        self,
        conn: psycopg.Connection[Any],
        graph_name: str,
    ) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    graph_refresh_id,
                    graph_name,
                    scope,
                    document_id,
                    node_count,
                    edge_count,
                    status,
                    metadata,
                    created_at,
                    updated_at
                FROM graph_refresh_log
                WHERE graph_name = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (graph_name,),
            )
            row = cur.fetchone()

        if row is None:
            return None

        return {
            "graph_refresh_id": str(row["graph_refresh_id"]),
            "graph_name": row["graph_name"],
            "scope": row["scope"],
            "document_id": str(row["document_id"]) if row["document_id"] else None,
            "node_count": int(row["node_count"]),
            "edge_count": int(row["edge_count"]),
            "status": row["status"],
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _count_graph_nodes(self, conn: psycopg.Connection[Any], graph_name: str) -> int:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM ag_catalog.cypher(
                    {cypher_string_literal(graph_name)},
                    $$ MATCH (n) RETURN n $$
                ) AS (n ag_catalog.agtype)
                """
            )
            row = cur.fetchone()
        return int(row["count"]) if row else 0

    def _count_graph_edges(self, conn: psycopg.Connection[Any], graph_name: str) -> int:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM ag_catalog.cypher(
                    {cypher_string_literal(graph_name)},
                    $$ MATCH ()-[r]->() RETURN r $$
                ) AS (r ag_catalog.agtype)
                """
            )
            row = cur.fetchone()
        return int(row["count"]) if row else 0

    def _empty_counts(self) -> dict[str, int]:
        return {
            "projected_documents": 0,
            "projected_chunks": 0,
            "projected_entities": 0,
            "projected_relations": 0,
            "projected_mentions": 0,
            "node_count": 0,
            "edge_count": 0,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap_graph.py",
        description="Explicit graph bootstrap and rebuild management script for Apache AGE projection operations.",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current graph projection status.",
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Truncate and fully rebuild the AGE graph projection.",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        default=None,
        help="Refresh only one document projection by document UUID.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON result.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    manager = GraphBootstrapManager(settings)

    try:
        if args.status:
            result = manager.status()
        elif args.document_id is not None:
            try:
                document_id = uuid.UUID(args.document_id)
            except ValueError as exc:
                raise GraphBootstrapError(
                    f"document-id must be a valid UUID: {args.document_id}"
                ) from exc
            result = manager.bootstrap_document(document_id)
        else:
            result = manager.bootstrap(full_rebuild=args.full_rebuild)

        if args.pretty:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(json_dumps(result))
        return 0
    except Exception as exc:
        error_payload = {
            "status": "failed",
            "error": str(exc),
            "timestamp": utc_now().isoformat(),
        }
        print(json.dumps(error_payload, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

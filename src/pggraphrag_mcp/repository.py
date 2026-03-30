from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n{2,}")


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(value or "")]


def content_hash_for_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def deterministic_embedding(
    text: str,
    dimensions: int,
) -> list[float]:
    """
    Produce a deterministic pseudo-embedding.

    This is intentionally lightweight so the repository layer can support
    ingestion and retrieval end-to-end even before a real embedding provider
    is wired in.
    """
    if dimensions <= 0:
        return []

    tokens = tokenize(text)
    if not tokens:
        return [0.0] * dimensions

    values = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(dimensions):
            byte_value = digest[index % len(digest)]
            values[index] += (byte_value / 255.0) - 0.5

    scale = float(len(tokens))
    return [round(value / scale, 8) for value in values]


def chunk_text(
    text: str,
    *,
    max_chunk_chars: int = 700,
    overlap_chars: int = 120,
) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    sentences = [
        part.strip() for part in _SENTENCE_SPLIT_RE.split(normalized) if part.strip()
    ]
    if not sentences:
        sentences = [normalized]

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = normalize_text(f"{overlap} {sentence}")
            while len(current) > max_chunk_chars:
                chunks.append(current[:max_chunk_chars].strip())
                tail_start = max(0, max_chunk_chars - overlap_chars)
                current = current[tail_start:].strip()
        else:
            chunks.append(sentence[:max_chunk_chars].strip())
            remainder = sentence[max_chunk_chars - overlap_chars :].strip()
            current = remainder

    if current:
        chunks.append(current)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in chunks:
        normalized_item = normalize_text(item)
        if normalized_item and normalized_item not in seen:
            seen.add(normalized_item)
            deduped.append(normalized_item)
    return deduped


@dataclass(slots=True, frozen=True)
class DocumentRecord:
    document_id: uuid.UUID
    tenant_id: str
    source_uri: str
    title: str
    mime_type: str
    content_hash: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class ChunkRecord:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_no: int
    text: str
    token_count: int
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(slots=True, frozen=True)
class EntityRecord:
    entity_id: uuid.UUID
    canonical_name: str
    entity_type: str
    aliases: list[str]
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(slots=True, frozen=True)
class RelationRecord:
    relation_fact_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relation_type: str
    weight: float
    evidence_chunk_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(slots=True, frozen=True)
class SourceRecord:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_uri: str
    title: str
    chunk_no: int
    snippet: str


@dataclass(slots=True, frozen=True)
class IngestionResult:
    ingestion_job_id: uuid.UUID
    document: DocumentRecord
    chunks: list[ChunkRecord]
    entities: list[EntityRecord]
    relations: list[RelationRecord]
    graph_refresh_summary: dict[str, Any]


@dataclass(slots=True, frozen=True)
class EntitySearchResult:
    entity: EntityRecord
    evidence_chunks: list[SourceRecord]
    score: float


@dataclass(slots=True, frozen=True)
class RetrievalResult:
    retrieval_id: uuid.UUID
    summary: str
    mode: str
    supporting_chunks: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    confidence: float
    timings: dict[str, Any]


class GraphRagRepository:
    """
    Relational repository for ingestion, retrieval, graph refresh, and trace APIs.

    The repository keeps PostgreSQL as the canonical state and treats AGE as a
    derived projection. Retrieval uses relational data and deterministic
    pseudo-embeddings so the stack can operate end-to-end before a production
    embedding provider is added.
    """

    def __init__(
        self,
        dsn: str,
        *,
        age_graph_name: str,
        embedding_dimensions: int = 1536,
        max_return_chunks: int = 12,
        max_return_entities: int = 20,
        max_graph_hops: int = 2,
        app_name: str = "pggraphrag-mcp",
    ) -> None:
        self._dsn = dsn
        self._age_graph_name = age_graph_name
        self._embedding_dimensions = embedding_dimensions
        self._max_return_chunks = max_return_chunks
        self._max_return_entities = max_return_entities
        self._max_graph_hops = max_graph_hops
        self._app_name = app_name

    def connection(self) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self._dsn,
            row_factory=dict_row,
            application_name=self._app_name,
        )

    # ---------------------------------------------------------------------
    # Ingestion
    # ---------------------------------------------------------------------

    def document_ingest(
        self,
        *,
        tenant_id: str,
        source_uri: str,
        title: str,
        text: str,
        mime_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
        reingest: bool = True,
    ) -> IngestionResult:
        metadata = metadata or {}
        normalized_text = normalize_text(text)
        if not normalized_text:
            raise ValueError("Document text must not be empty.")

        ingestion_job_id = uuid.uuid4()
        content_hash = content_hash_for_text(normalized_text)
        chunks = chunk_text(normalized_text)

        with self.connection() as conn:
            with conn.transaction():
                self._set_ingestion_job_status(
                    conn,
                    ingestion_job_id=ingestion_job_id,
                    document_id=None,
                    status="running",
                    failure_reason=None,
                )

                existing_document_id = self._find_document_by_hash(
                    conn,
                    tenant_id=tenant_id,
                    content_hash=content_hash,
                )

                if existing_document_id and reingest:
                    self._delete_document_graph_projection(conn, existing_document_id)
                    self._delete_document_relational(conn, existing_document_id)

                document = self._upsert_document(
                    conn,
                    tenant_id=tenant_id,
                    source_uri=source_uri,
                    title=title,
                    mime_type=mime_type,
                    content_hash=content_hash,
                )

                chunk_records = self._replace_chunks_for_document(
                    conn,
                    document_id=document.document_id,
                    chunk_texts=chunks,
                    metadata=metadata,
                )

                entity_records, relation_records = self._extract_entities_and_relations(
                    conn,
                    chunk_records=chunk_records,
                )

                graph_refresh_summary = self.graph_refresh(
                    conn=conn,
                    document_id=document.document_id,
                )

                self._set_ingestion_job_status(
                    conn,
                    ingestion_job_id=ingestion_job_id,
                    document_id=document.document_id,
                    status="completed",
                    failure_reason=None,
                )

                return IngestionResult(
                    ingestion_job_id=ingestion_job_id,
                    document=document,
                    chunks=chunk_records,
                    entities=entity_records,
                    relations=relation_records,
                    graph_refresh_summary=graph_refresh_summary,
                )

    def document_reingest(
        self,
        *,
        tenant_id: str,
        source_uri: str,
        title: str,
        text: str,
        mime_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        return self.document_ingest(
            tenant_id=tenant_id,
            source_uri=source_uri,
            title=title,
            text=text,
            mime_type=mime_type,
            metadata=metadata,
            reingest=True,
        )

    def document_delete(self, *, document_id: uuid.UUID) -> bool:
        with self.connection() as conn:
            with conn.transaction():
                self._delete_document_graph_projection(conn, document_id)
                deleted = self._delete_document_relational(conn, document_id)
                return deleted

    # ---------------------------------------------------------------------
    # Retrieval
    # ---------------------------------------------------------------------

    def retrieve_naive(
        self,
        *,
        query: str,
        top_k: int = 5,
    ) -> RetrievalResult:
        normalized_query = normalize_text(query)
        if not normalized_query:
            raise ValueError("Query must not be empty.")

        retrieval_id = uuid.uuid4()
        query_embedding = deterministic_embedding(
            normalized_query, self._embedding_dimensions
        )

        with self.connection() as conn:
            candidates = self._rank_chunks_by_similarity(
                conn,
                query=query,
                query_embedding=query_embedding,
                top_k=min(top_k, self._max_return_chunks),
            )
            supporting_chunks = [self._chunk_payload(item) for item in candidates]
            sources = [self._source_payload(item) for item in candidates]
            summary = self._build_summary_from_chunks(
                normalized_query,
                [item["text"] for item in candidates],
            )
            confidence = round(
                max((item["score"] for item in candidates), default=0.0),
                4,
            )
            timings = {
                "strategy": "deterministic-local",
                "candidate_count": len(candidates),
            }

            self._insert_retrieval_log(
                conn,
                retrieval_id=retrieval_id,
                query_text=normalized_query,
                mode="naive",
                returned_source_ids=[str(item["chunk_id"]) for item in candidates],
                timings=timings,
            )

            return RetrievalResult(
                retrieval_id=retrieval_id,
                summary=summary,
                mode="naive",
                supporting_chunks=[dict(item) for item in supporting_chunks],
                entities=[],
                relationships=[],
                sources=[dict(item) for item in sources],
                confidence=confidence,
                timings=dict(timings),
            )

    def entity_search(
        self,
        *,
        query: str,
        limit: int = 10,
    ) -> list[EntitySearchResult]:
        normalized_query = normalize_text(query).lower()
        if not normalized_query:
            return []

        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.entity_id,
                    e.canonical_name,
                    e.entity_type,
                    e.aliases,
                    e.metadata,
                    e.created_at
                FROM entity e
                WHERE lower(e.canonical_name) LIKE %s
                   OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(e.aliases) alias
                        WHERE lower(alias) LIKE %s
                   )
                ORDER BY
                    CASE
                        WHEN lower(e.canonical_name) = %s THEN 0
                        WHEN lower(e.canonical_name) LIKE %s THEN 1
                        ELSE 2
                    END,
                    e.canonical_name
                LIMIT %s
                """,
                (
                    f"%{normalized_query}%",
                    f"%{normalized_query}%",
                    normalized_query,
                    f"{normalized_query}%",
                    limit,
                ),
            )
            rows = list(cur.fetchall())

        results: list[EntitySearchResult] = []
        with self.connection() as conn:
            for row in rows:
                entity = self._entity_from_row(row)
                evidence = self._entity_evidence_sources(
                    conn, entity.entity_id, limit=3
                )
                score = self._entity_name_score(normalized_query, entity.canonical_name)
                results.append(
                    EntitySearchResult(
                        entity=entity,
                        evidence_chunks=evidence,
                        score=score,
                    )
                )
        return results

    def entity_expand(
        self,
        *,
        entity_id: uuid.UUID,
        hops: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        effective_hops = max(1, min(hops, self._max_graph_hops))
        effective_limit = min(limit, self._max_return_entities)

        with self.connection() as conn:
            root_entity = self._get_entity(conn, entity_id)
            if root_entity is None:
                raise ValueError(f"Entity not found: {entity_id}")

            neighbors = self._expand_entity_neighbors(
                conn,
                entity_id=entity_id,
                hops=effective_hops,
                limit=effective_limit,
            )

            relationships = []
            for item in neighbors:
                relationships.append(
                    {
                        "relation_fact_id": str(item["relation_fact_id"]),
                        "source_entity_id": str(item["source_entity_id"]),
                        "target_entity_id": str(item["target_entity_id"]),
                        "relation_type": item["relation_type"],
                        "weight": float(item["weight"]),
                        "evidence_chunk_id": (
                            str(item["evidence_chunk_id"])
                            if item["evidence_chunk_id"]
                            else None
                        ),
                    }
                )

            related_entity_ids = {item["source_entity_id"] for item in neighbors} | {
                item["target_entity_id"] for item in neighbors
            }
            entity_payloads = []
            for related_entity_id in sorted(related_entity_ids):
                related = self._get_entity(conn, related_entity_id)
                if related is not None:
                    entity_payloads.append(self._entity_payload(related))

            evidence_chunk_ids = {
                item["evidence_chunk_id"]
                for item in neighbors
                if item["evidence_chunk_id"] is not None
            }
            sources = self._sources_for_chunk_ids(conn, list(evidence_chunk_ids))

            return {
                "root_entity": self._entity_payload(root_entity),
                "hops": effective_hops,
                "entities": entity_payloads,
                "relationships": relationships,
                "sources": [self._source_payload(item) for item in sources],
            }

    def retrieve_local_graph(
        self,
        *,
        query: str,
        top_k: int = 5,
        graph_limit: int = 20,
    ) -> RetrievalResult:
        naive = self.retrieve_naive(query=query, top_k=top_k)
        supporting_chunk_ids = [
            uuid.UUID(item["chunk_id"]) for item in naive.supporting_chunks
        ]

        with self.connection() as conn:
            entities = self._entities_for_chunks(conn, supporting_chunk_ids)
            relationships = self._relationships_for_entity_ids(
                conn,
                [uuid.UUID(item["entity_id"]) for item in entities],
                limit=min(graph_limit, self._max_return_entities),
            )
            sources = [self._source_payload(item) for item in naive.sources]
            for relation in relationships:
                evidence_chunk_id = relation.get("evidence_chunk_id")
                if evidence_chunk_id:
                    source = self._source_for_chunk_id(
                        conn, uuid.UUID(evidence_chunk_id)
                    )
                    if source and all(
                        s.get("chunk_id") != source.get("chunk_id") for s in sources
                    ):
                        sources.append(source)

            summary = naive.summary
            if entities:
                sample_names = ", ".join(
                    item["canonical_name"] for item in entities[:4]
                )
                summary = f"{summary} Related entities include {sample_names}."

            retrieval_id = uuid.uuid4()
            timings = {
                "strategy": "naive_plus_local_graph",
                "chunk_count": len(naive.supporting_chunks),
                "entity_count": len(entities),
                "relationship_count": len(relationships),
            }

            self._insert_retrieval_log(
                conn,
                retrieval_id=retrieval_id,
                query_text=normalize_text(query),
                mode="local_graph",
                returned_source_ids=[
                    str(item["chunk_id"]) for item in sources if item.get("chunk_id")
                ],
                timings=timings,
            )

            return RetrievalResult(
                retrieval_id=retrieval_id,
                summary=summary,
                mode="local_graph",
                supporting_chunks=[dict(item) for item in naive.supporting_chunks],
                entities=[dict(item) for item in entities],
                relationships=[dict(item) for item in relationships],
                sources=[dict(item) for item in sources],
                confidence=naive.confidence,
                timings=dict(timings),
            )

    def retrieve_hybrid(
        self,
        *,
        query: str,
        top_k: int = 5,
        graph_limit: int = 20,
    ) -> RetrievalResult:
        local_graph = self.retrieve_local_graph(
            query=query,
            top_k=top_k,
            graph_limit=graph_limit,
        )

        enriched_entities = list(local_graph.entities)
        enriched_relationships = list(local_graph.relationships)
        sources = [self._source_payload(item) for item in local_graph.sources]

        score = round(
            min(
                1.0,
                local_graph.confidence
                + (0.03 * min(len(enriched_entities), 5))
                + (0.02 * min(len(enriched_relationships), 5)),
            ),
            4,
        )

        summary = local_graph.summary
        if enriched_relationships:
            top_relation = enriched_relationships[0]
            summary = (
                f"{summary} One highlighted relationship is "
                f"{top_relation['relation_type']} between "
                f"{top_relation['source_entity_name']} and {top_relation['target_entity_name']}."
            )

        retrieval_id = uuid.uuid4()
        timings = {
            "strategy": "hybrid",
            "chunk_count": len(local_graph.supporting_chunks),
            "entity_count": len(enriched_entities),
            "relationship_count": len(enriched_relationships),
            "source_count": len(sources),
        }

        with self.connection() as conn:
            self._insert_retrieval_log(
                conn,
                retrieval_id=retrieval_id,
                query_text=normalize_text(query),
                mode="hybrid",
                returned_source_ids=[
                    str(item["chunk_id"]) for item in sources if item.get("chunk_id")
                ],
                timings=timings,
            )

        return RetrievalResult(
            retrieval_id=retrieval_id,
            summary=summary,
            mode="hybrid",
            supporting_chunks=[dict(item) for item in local_graph.supporting_chunks],
            entities=[dict(item) for item in enriched_entities],
            relationships=[dict(item) for item in enriched_relationships],
            sources=[dict(item) for item in sources],
            confidence=score,
            timings=dict(timings),
        )

    def source_trace(self, *, retrieval_id: uuid.UUID) -> dict[str, Any]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT retrieval_id, query_text, mode, returned_source_ids, timings, created_at
                FROM retrieval_log
                WHERE retrieval_id = %s
                """,
                (retrieval_id,),
            )
            row = cur.fetchone()

            if row is None:
                raise ValueError(f"Retrieval trace not found: {retrieval_id}")

            source_ids = []
            for value in row["returned_source_ids"] or []:
                if isinstance(value, uuid.UUID):
                    source_ids.append(value)
                    continue
                try:
                    source_ids.append(uuid.UUID(str(value)))
                except ValueError:
                    continue

            sources = self._sources_for_chunk_ids(conn, source_ids)

            return {
                "retrieval_id": str(row["retrieval_id"]),
                "query_text": row["query_text"],
                "mode": row["mode"],
                "timings": row["timings"] or {},
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else None,
                "sources": [self._source_payload(item) for item in sources],
            }

    # ---------------------------------------------------------------------
    # Graph refresh
    # ---------------------------------------------------------------------

    def graph_refresh(
        self,
        *,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID | None = None,
        full_rebuild: bool = False,
    ) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = public, ag_catalog")

            if full_rebuild:
                self._truncate_age_graph(cur)

            if document_id is not None:
                self._delete_document_graph_projection(conn, document_id)
                document_ids = [document_id]
            else:
                cur.execute("SELECT document_id FROM document ORDER BY created_at")
                document_ids = [row["document_id"] for row in cur.fetchall()]

            projected_documents = 0
            projected_chunks = 0
            projected_entities = 0
            projected_relations = 0

            for current_document_id in document_ids:
                document = self._get_document(conn, current_document_id)
                if document is None:
                    continue

                self._upsert_age_document_node(cur, document)
                projected_documents += 1

                chunks = self._get_chunks_for_document(conn, current_document_id)
                for chunk in chunks:
                    self._upsert_age_chunk_node(cur, chunk)
                    self._upsert_age_document_chunk_edge(
                        cur, document.document_id, chunk.chunk_id
                    )
                    projected_chunks += 1

                entities = self._entities_for_document(conn, current_document_id)
                unique_entities: dict[uuid.UUID, dict[str, Any]] = {}
                for entity in entities:
                    entity_id_value = entity["entity_id"]
                    normalized_entity_id = (
                        entity_id_value
                        if isinstance(entity_id_value, uuid.UUID)
                        else uuid.UUID(str(entity_id_value))
                    )
                    unique_entities[normalized_entity_id] = entity

                for entity in unique_entities.values():
                    self._upsert_age_entity_node(cur, entity)
                    projected_entities += 1

                mentions = self._chunk_entity_rows_for_document(
                    conn, current_document_id
                )
                for mention in mentions:
                    self._upsert_age_mentions_edge(
                        cur,
                        mention["chunk_id"],
                        mention["entity_id"],
                        mention["mention_count"],
                    )

                relations = self._relation_rows_for_document(conn, current_document_id)
                for relation in relations:
                    self._upsert_age_relation_edge(cur, relation)
                    projected_relations += 1

            return {
                "graph_name": self._age_graph_name,
                "document_scope": str(document_id) if document_id else "all",
                "full_rebuild": full_rebuild,
                "projected_documents": projected_documents,
                "projected_chunks": projected_chunks,
                "projected_entities": projected_entities,
                "projected_relations": projected_relations,
            }

    # ---------------------------------------------------------------------
    # Internal relational helpers
    # ---------------------------------------------------------------------

    def _find_document_by_hash(
        self,
        conn: psycopg.Connection[Any],
        *,
        tenant_id: str,
        content_hash: str,
    ) -> uuid.UUID | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_id
                FROM document
                WHERE tenant_id = %s
                  AND content_hash = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tenant_id, content_hash),
            )
            row = cur.fetchone()
            return row["document_id"] if row else None

    def _upsert_document(
        self,
        conn: psycopg.Connection[Any],
        *,
        tenant_id: str,
        source_uri: str,
        title: str,
        mime_type: str,
        content_hash: str,
    ) -> DocumentRecord:
        now = utc_now()
        document_id = uuid.uuid4()

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document (
                    document_id,
                    tenant_id,
                    source_uri,
                    title,
                    mime_type,
                    content_hash,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    document_id,
                    tenant_id,
                    source_uri,
                    title,
                    mime_type,
                    content_hash,
                    status,
                    created_at,
                    updated_at
                """,
                (
                    document_id,
                    tenant_id,
                    source_uri,
                    title,
                    mime_type,
                    content_hash,
                    "active",
                    now,
                    now,
                ),
            )
            row = cur.fetchone()
        return self._document_from_row(row)

    def _replace_chunks_for_document(
        self,
        conn: psycopg.Connection[Any],
        *,
        document_id: uuid.UUID,
        chunk_texts: Sequence[str],
        metadata: dict[str, Any],
    ) -> list[ChunkRecord]:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunk WHERE document_id = %s", (document_id,))

        results: list[ChunkRecord] = []
        for index, chunk_body in enumerate(chunk_texts):
            chunk_id = uuid.uuid4()
            token_count = len(tokenize(chunk_body))
            embedding = deterministic_embedding(chunk_body, self._embedding_dimensions)
            chunk_metadata = {
                "char_count": len(chunk_body),
                "embedding_provider": "deterministic-local",
                **metadata,
            }

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chunk (
                        chunk_id,
                        document_id,
                        chunk_no,
                        text,
                        token_count,
                        embedding,
                        metadata,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb, %s)
                    RETURNING
                        chunk_id,
                        document_id,
                        chunk_no,
                        text,
                        token_count,
                        metadata,
                        created_at
                    """,
                    (
                        chunk_id,
                        document_id,
                        index,
                        chunk_body,
                        token_count,
                        self._vector_literal(embedding),
                        json_dumps(chunk_metadata),
                        utc_now(),
                    ),
                )
                row = cur.fetchone()
                results.append(self._chunk_from_row(row))
        return results

    def _extract_entities_and_relations(
        self,
        conn: psycopg.Connection[Any],
        *,
        chunk_records: Sequence[ChunkRecord],
    ) -> tuple[list[EntityRecord], list[RelationRecord]]:
        chunk_entity_ids: dict[uuid.UUID, list[uuid.UUID]] = {}
        entity_records_by_id: dict[uuid.UUID, EntityRecord] = {}

        for chunk in chunk_records:
            names = self._extract_candidate_entities(chunk.text)
            names = names[: self._max_return_entities]
            associated_ids: list[uuid.UUID] = []

            for name in names:
                entity = self._get_or_create_entity(
                    conn,
                    canonical_name=name,
                    entity_type=self._infer_entity_type(name),
                )
                entity_records_by_id[entity.entity_id] = entity
                associated_ids.append(entity.entity_id)

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO chunk_entity (
                            chunk_id,
                            entity_id,
                            mention_count,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s::jsonb)
                        ON CONFLICT (chunk_id, entity_id)
                        DO UPDATE SET
                            mention_count = EXCLUDED.mention_count,
                            metadata = EXCLUDED.metadata
                        """,
                        (
                            chunk.chunk_id,
                            entity.entity_id,
                            self._mention_count(chunk.text, name),
                            json_dumps({"extractor": "heuristic-v1"}),
                        ),
                    )

            chunk_entity_ids[chunk.chunk_id] = associated_ids

        relation_records: list[RelationRecord] = []
        for chunk in chunk_records:
            entity_ids = chunk_entity_ids.get(chunk.chunk_id, [])
            if len(entity_ids) < 2:
                continue

            for left_index in range(len(entity_ids) - 1):
                source_entity_id = entity_ids[left_index]
                target_entity_id = entity_ids[left_index + 1]
                relation_type = self._infer_relation_type(chunk.text)

                relation = self._upsert_relation_fact(
                    conn,
                    source_entity_id=source_entity_id,
                    target_entity_id=target_entity_id,
                    relation_type=relation_type,
                    evidence_chunk_id=chunk.chunk_id,
                )
                relation_records.append(relation)

        return list(entity_records_by_id.values()), relation_records

    def _get_or_create_entity(
        self,
        conn: psycopg.Connection[Any],
        *,
        canonical_name: str,
        entity_type: str,
    ) -> EntityRecord:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_id,
                    canonical_name,
                    entity_type,
                    aliases,
                    metadata,
                    created_at
                FROM entity
                WHERE lower(canonical_name) = lower(%s)
                LIMIT 1
                """,
                (canonical_name,),
            )
            row = cur.fetchone()
            if row:
                return self._entity_from_row(row)

            entity_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO entity (
                    entity_id,
                    canonical_name,
                    entity_type,
                    aliases,
                    metadata,
                    created_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                RETURNING
                    entity_id,
                    canonical_name,
                    entity_type,
                    aliases,
                    metadata,
                    created_at
                """,
                (
                    entity_id,
                    canonical_name,
                    entity_type,
                    json_dumps([]),
                    json_dumps({"extractor": "heuristic-v1"}),
                    utc_now(),
                ),
            )
            inserted = cur.fetchone()
            return self._entity_from_row(inserted)

    def _upsert_relation_fact(
        self,
        conn: psycopg.Connection[Any],
        *,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        relation_type: str,
        evidence_chunk_id: uuid.UUID,
    ) -> RelationRecord:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    relation_fact_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    weight,
                    evidence_chunk_id,
                    metadata,
                    created_at
                FROM relation_fact
                WHERE source_entity_id = %s
                  AND target_entity_id = %s
                  AND relation_type = %s
                  AND evidence_chunk_id = %s
                LIMIT 1
                """,
                (
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    evidence_chunk_id,
                ),
            )
            existing = cur.fetchone()
            if existing:
                return self._relation_from_row(existing)

            relation_fact_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO relation_fact (
                    relation_fact_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    weight,
                    evidence_chunk_id,
                    metadata,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING
                    relation_fact_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    weight,
                    evidence_chunk_id,
                    metadata,
                    created_at
                """,
                (
                    relation_fact_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    1.0,
                    evidence_chunk_id,
                    json_dumps({"extractor": "heuristic-v1"}),
                    utc_now(),
                ),
            )
            inserted = cur.fetchone()
            return self._relation_from_row(inserted)

    def _set_ingestion_job_status(
        self,
        conn: psycopg.Connection[Any],
        *,
        ingestion_job_id: uuid.UUID,
        document_id: uuid.UUID | None,
        status: str,
        failure_reason: str | None,
    ) -> None:
        now = utc_now()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_job (
                    ingestion_job_id,
                    document_id,
                    status,
                    failure_reason,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (ingestion_job_id)
                DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    status = EXCLUDED.status,
                    failure_reason = EXCLUDED.failure_reason,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    ingestion_job_id,
                    document_id,
                    status,
                    failure_reason,
                    now,
                    now,
                ),
            )

    def _insert_retrieval_log(
        self,
        conn: psycopg.Connection[Any],
        *,
        retrieval_id: uuid.UUID,
        query_text: str,
        mode: str,
        returned_source_ids: Sequence[str],
        timings: dict[str, Any],
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO retrieval_log (
                    retrieval_id,
                    query_text,
                    mode,
                    returned_source_ids,
                    timings,
                    created_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    retrieval_id,
                    query_text,
                    mode,
                    json_dumps(list(returned_source_ids)),
                    json_dumps(timings),
                    utc_now(),
                ),
            )

    def _delete_document_relational(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> bool:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM document WHERE document_id = %s", (document_id,))
            return cur.rowcount > 0

    # ---------------------------------------------------------------------
    # Internal graph helpers
    # ---------------------------------------------------------------------

    def _delete_document_graph_projection(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute("LOAD 'age'")
            cur.execute("SET search_path = public, ag_catalog")
            self._execute_cypher(
                cur,
                f"""
                MATCH (d:Document {{document_id: {self._cypher_string_literal(str(document_id))}}})
                OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
                DETACH DELETE d, c
                RETURN 1
                """,
            )

    def _truncate_age_graph(self, cur: psycopg.Cursor[Any]) -> None:
        self._execute_cypher(
            cur,
            """
            MATCH (n)
            DETACH DELETE n
            RETURN 1
            """,
        )

    def _upsert_age_document_node(
        self,
        cur: psycopg.Cursor[Any],
        document: DocumentRecord,
    ) -> None:
        self._execute_cypher(
            cur,
            f"""
            MERGE (d:Document {{document_id: {self._cypher_string_literal(str(document.document_id))}}})
            SET d.title = {self._cypher_string_literal(str(document.title))},
                d.source_uri = {self._cypher_string_literal(str(document.source_uri))},
                d.tenant_id = {self._cypher_string_literal(str(document.tenant_id))},
                d.status = {self._cypher_string_literal(str(document.status))}
            RETURN 1
            """,
        )

    def _upsert_age_chunk_node(
        self,
        cur: psycopg.Cursor[Any],
        chunk: ChunkRecord,
    ) -> None:
        self._execute_cypher(
            cur,
            f"""
            MERGE (c:Chunk {{chunk_id: {self._cypher_string_literal(str(chunk.chunk_id))}}})
            SET c.chunk_no = {int(chunk.chunk_no)},
                c.text = {self._cypher_string_literal(str(chunk.text))},
                c.document_id = {self._cypher_string_literal(str(chunk.document_id))}
            RETURN 1
            """,
        )

    def _upsert_age_document_chunk_edge(
        self,
        cur: psycopg.Cursor[Any],
        document_id: uuid.UUID,
        chunk_id: uuid.UUID,
    ) -> None:
        self._execute_cypher(
            cur,
            f"""
            MATCH (d:Document {{document_id: {self._cypher_string_literal(str(document_id))}}})
            MATCH (c:Chunk {{chunk_id: {self._cypher_string_literal(str(chunk_id))}}})
            MERGE (d)-[:HAS_CHUNK]->(c)
            RETURN 1
            """,
        )

    def _upsert_age_entity_node(
        self,
        cur: psycopg.Cursor[Any],
        entity: dict[str, Any],
    ) -> None:
        self._execute_cypher(
            cur,
            f"""
            MERGE (e:Entity {{entity_id: {self._cypher_string_literal(str(entity["entity_id"]))}}})
            SET e.canonical_name = {self._cypher_string_literal(str(entity["canonical_name"]))},
                e.entity_type = {self._cypher_string_literal(str(entity["entity_type"]))}
            RETURN 1
            """,
        )

    def _upsert_age_mentions_edge(
        self,
        cur: psycopg.Cursor[Any],
        chunk_id: uuid.UUID,
        entity_id: uuid.UUID,
        mention_count: int,
    ) -> None:
        self._execute_cypher(
            cur,
            f"""
            MATCH (c:Chunk {{chunk_id: {self._cypher_string_literal(str(chunk_id))}}})
            MATCH (e:Entity {{entity_id: {self._cypher_string_literal(str(entity_id))}}})
            MERGE (c)-[r:MENTIONS]->(e)
            SET r.mention_count = {int(mention_count)}
            RETURN 1
            """,
        )

    def _upsert_age_relation_edge(
        self,
        cur: psycopg.Cursor[Any],
        relation: dict[str, Any],
    ) -> None:
        evidence_chunk_literal = (
            self._cypher_string_literal(str(relation["evidence_chunk_id"]))
            if relation["evidence_chunk_id"] is not None
            else "null"
        )
        self._execute_cypher(
            cur,
            f"""
            MATCH (source:Entity {{entity_id: {self._cypher_string_literal(str(relation["source_entity_id"]))}}})
            MATCH (target:Entity {{entity_id: {self._cypher_string_literal(str(relation["target_entity_id"]))}}})
            MERGE (source)-[r:RELATES_TO {{
                relation_fact_id: {self._cypher_string_literal(str(relation["relation_fact_id"]))}
            }}]->(target)
            SET r.relation_type = {self._cypher_string_literal(str(relation["relation_type"]))},
                r.weight = {float(relation["weight"])},
                r.evidence_chunk_id = {evidence_chunk_literal}
            RETURN 1
            """,
        )

    def _execute_cypher(
        self,
        cur: psycopg.Cursor[Any],
        query: str,
    ) -> None:
        escaped_query = query.strip().replace("$$", "\\$\\$")
        graph_name_literal = self._cypher_string_literal(self._age_graph_name)
        cur.execute(
            f"""
            SELECT *
            FROM ag_catalog.cypher(
                {graph_name_literal},
                $$ {escaped_query} $$
            ) AS (result ag_catalog.agtype)
            """
        )

    def _cypher_string_literal(self, value: str) -> str:
        value_str = str(value)
        escaped = value_str.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    # ---------------------------------------------------------------------
    # Query helpers
    # ---------------------------------------------------------------------

    def _rank_chunks_by_similarity(
        self,
        conn: psycopg.Connection[Any],
        *,
        query: str,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.chunk_id,
                    c.document_id,
                    c.chunk_no,
                    c.text,
                    c.token_count,
                    c.embedding::text AS embedding_text,
                    c.metadata,
                    d.source_uri,
                    d.title
                FROM chunk c
                JOIN document d
                  ON d.document_id = c.document_id
                ORDER BY c.created_at
                """
            )
            rows = list(cur.fetchall())

        query_tokens = set(tokenize(query))
        scored: list[dict[str, Any]] = []

        for row in rows:
            chunk_embedding = self._parse_vector_text(row["embedding_text"])
            embedding_score = cosine_similarity(query_embedding, chunk_embedding)
            chunk_tokens = set(tokenize(row["text"]))
            lexical_overlap = (
                len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
                if query_tokens
                else 0.0
            )
            score = (embedding_score * 0.7) + (lexical_overlap * 0.3)

            if score <= 0.0:
                continue

            scored.append(
                {
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "chunk_no": row["chunk_no"],
                    "text": row["text"],
                    "token_count": row["token_count"],
                    "metadata": row["metadata"] or {},
                    "source_uri": row["source_uri"],
                    "title": row["title"],
                    "score": round(score, 6),
                }
            )

        scored.sort(key=lambda item: (-item["score"], item["chunk_no"]))
        return scored[:top_k]

    def _entities_for_chunks(
        self,
        conn: psycopg.Connection[Any],
        chunk_ids: Sequence[uuid.UUID],
    ) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    e.entity_id,
                    e.canonical_name,
                    e.entity_type,
                    e.aliases,
                    e.metadata,
                    e.created_at
                FROM chunk_entity ce
                JOIN entity e
                  ON e.entity_id = ce.entity_id
                WHERE ce.chunk_id = ANY(%s)
                ORDER BY e.canonical_name
                LIMIT %s
                """,
                (list(chunk_ids), self._max_return_entities),
            )
            rows = cur.fetchall()
        return [self._entity_payload(self._entity_from_row(row)) for row in rows]

    def _relationships_for_entity_ids(
        self,
        conn: psycopg.Connection[Any],
        entity_ids: Sequence[uuid.UUID],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not entity_ids:
            return []

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    rf.relation_fact_id,
                    rf.source_entity_id,
                    source_e.canonical_name AS source_entity_name,
                    rf.target_entity_id,
                    target_e.canonical_name AS target_entity_name,
                    rf.relation_type,
                    rf.weight,
                    rf.evidence_chunk_id,
                    rf.metadata,
                    rf.created_at
                FROM relation_fact rf
                JOIN entity source_e
                  ON source_e.entity_id = rf.source_entity_id
                JOIN entity target_e
                  ON target_e.entity_id = rf.target_entity_id
                WHERE rf.source_entity_id = ANY(%s)
                   OR rf.target_entity_id = ANY(%s)
                ORDER BY rf.weight DESC, rf.created_at DESC
                LIMIT %s
                """,
                (list(entity_ids), list(entity_ids), limit),
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "relation_fact_id": str(row["relation_fact_id"]),
                    "source_entity_id": str(row["source_entity_id"]),
                    "source_entity_name": row["source_entity_name"],
                    "target_entity_id": str(row["target_entity_id"]),
                    "target_entity_name": row["target_entity_name"],
                    "relation_type": row["relation_type"],
                    "weight": float(row["weight"]),
                    "evidence_chunk_id": (
                        str(row["evidence_chunk_id"])
                        if row["evidence_chunk_id"]
                        else None
                    ),
                }
            )
        return results

    def _expand_entity_neighbors(
        self,
        conn: psycopg.Connection[Any],
        *,
        entity_id: uuid.UUID,
        hops: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        visited = {entity_id}
        frontier = {entity_id}
        collected: list[dict[str, Any]] = []

        for _ in range(hops):
            if not frontier:
                break

            frontier_ids = list(frontier)
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
                    WHERE rf.source_entity_id = ANY(%s)
                       OR rf.target_entity_id = ANY(%s)
                    ORDER BY rf.weight DESC, rf.created_at DESC
                    LIMIT %s
                    """,
                    (frontier_ids, frontier_ids, limit),
                )
                rows = cur.fetchall()

            new_frontier: set[uuid.UUID] = set()
            for row in rows:
                normalized_row = dict(row)
                normalized_row["relation_fact_id"] = str(row["relation_fact_id"])
                normalized_row["source_entity_id"] = str(row["source_entity_id"])
                normalized_row["target_entity_id"] = str(row["target_entity_id"])
                if row["evidence_chunk_id"] is not None:
                    normalized_row["evidence_chunk_id"] = str(row["evidence_chunk_id"])
                collected.append(normalized_row)
                source_entity_id = str(row["source_entity_id"])
                target_entity_id = str(row["target_entity_id"])
                if source_entity_id not in visited:
                    new_frontier.add(source_entity_id)
                if target_entity_id not in visited:
                    new_frontier.add(target_entity_id)

            visited |= new_frontier
            frontier = new_frontier

            if len(collected) >= limit:
                break

        unique_rows: dict[str, dict[str, Any]] = {}
        for row in collected:
            unique_rows[row["relation_fact_id"]] = row
        return list(unique_rows.values())[:limit]

    def _entity_evidence_sources(
        self,
        conn: psycopg.Connection[Any],
        entity_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[SourceRecord]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.document_id,
                    c.chunk_id,
                    d.source_uri,
                    d.title,
                    c.chunk_no,
                    c.text
                FROM chunk_entity ce
                JOIN chunk c
                  ON c.chunk_id = ce.chunk_id
                JOIN document d
                  ON d.document_id = c.document_id
                WHERE ce.entity_id = %s
                ORDER BY c.created_at
                LIMIT %s
                """,
                (entity_id, limit),
            )
            rows = cur.fetchall()

        return [self._source_from_row(row) for row in rows]

    def _sources_for_chunk_ids(
        self,
        conn: psycopg.Connection[Any],
        chunk_ids: Sequence[uuid.UUID],
    ) -> list[SourceRecord]:
        if not chunk_ids:
            return []

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.document_id,
                    c.chunk_id,
                    d.source_uri,
                    d.title,
                    c.chunk_no,
                    c.text
                FROM chunk c
                JOIN document d
                  ON d.document_id = c.document_id
                WHERE c.chunk_id = ANY(%s)
                ORDER BY c.chunk_no
                """,
                (list(chunk_ids),),
            )
            rows = cur.fetchall()
        return [self._source_from_row(row) for row in rows]

    def _source_for_chunk_id(
        self,
        conn: psycopg.Connection[Any],
        chunk_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        sources = self._sources_for_chunk_ids(conn, [chunk_id])
        if not sources:
            return None
        return self._source_payload(sources[0])

    def _get_entity(
        self,
        conn: psycopg.Connection[Any],
        entity_id: uuid.UUID,
    ) -> EntityRecord | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_id,
                    canonical_name,
                    entity_type,
                    aliases,
                    metadata,
                    created_at
                FROM entity
                WHERE entity_id = %s
                """,
                (entity_id,),
            )
            row = cur.fetchone()
        return self._entity_from_row(row) if row else None

    def _get_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> DocumentRecord | None:
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
                    status,
                    created_at,
                    updated_at
                FROM document
                WHERE document_id = %s
                """,
                (document_id,),
            )
            row = cur.fetchone()
        return self._document_from_row(row) if row else None

    def _get_chunks_for_document(
        self,
        conn: psycopg.Connection[Any],
        document_id: uuid.UUID,
    ) -> list[ChunkRecord]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    chunk_id,
                    document_id,
                    chunk_no,
                    text,
                    token_count,
                    metadata,
                    created_at
                FROM chunk
                WHERE document_id = %s
                ORDER BY chunk_no
                """,
                (document_id,),
            )
            rows = cur.fetchall()
        return [self._chunk_from_row(row) for row in rows]

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

    # ---------------------------------------------------------------------
    # Row mappers / payload builders
    # ---------------------------------------------------------------------

    def _document_from_row(self, row: dict[str, Any]) -> DocumentRecord:
        return DocumentRecord(
            document_id=row["document_id"],
            tenant_id=row["tenant_id"],
            source_uri=row["source_uri"],
            title=row["title"],
            mime_type=row["mime_type"],
            content_hash=row["content_hash"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _chunk_from_row(self, row: dict[str, Any]) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            chunk_no=row["chunk_no"],
            text=row["text"],
            token_count=row["token_count"],
            metadata=row.get("metadata") or {},
            created_at=row["created_at"],
        )

    def _entity_from_row(self, row: dict[str, Any]) -> EntityRecord:
        aliases = row.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        return EntityRecord(
            entity_id=row["entity_id"],
            canonical_name=row["canonical_name"],
            entity_type=row["entity_type"],
            aliases=aliases,
            metadata=row.get("metadata") or {},
            created_at=row["created_at"],
        )

    def _relation_from_row(self, row: dict[str, Any]) -> RelationRecord:
        return RelationRecord(
            relation_fact_id=row["relation_fact_id"],
            source_entity_id=row["source_entity_id"],
            target_entity_id=row["target_entity_id"],
            relation_type=row["relation_type"],
            weight=float(row["weight"]),
            evidence_chunk_id=row["evidence_chunk_id"],
            metadata=row.get("metadata") or {},
            created_at=row["created_at"],
        )

    def _source_from_row(self, row: dict[str, Any]) -> SourceRecord:
        return SourceRecord(
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            source_uri=row["source_uri"],
            title=row["title"],
            chunk_no=row["chunk_no"],
            snippet=normalize_text(row["text"])[:240],
        )

    def _entity_payload(self, entity: EntityRecord) -> dict[str, Any]:
        return {
            "entity_id": str(entity.entity_id),
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "aliases": list(entity.aliases),
            "metadata": dict(entity.metadata),
        }

    def _chunk_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "chunk_id": str(item["chunk_id"]),
            "document_id": str(item["document_id"]),
            "chunk_no": item["chunk_no"],
            "text": item["text"],
            "token_count": item["token_count"],
            "score": round(float(item["score"]), 4),
            "metadata": item.get("metadata") or {},
        }

    def _source_payload(self, source: SourceRecord | dict[str, Any]) -> dict[str, Any]:
        if isinstance(source, dict):
            document_id = source.get("document_id")
            chunk_id = source.get("chunk_id")
            return {
                "document_id": str(document_id) if document_id is not None else None,
                "chunk_id": str(chunk_id) if chunk_id is not None else None,
                "source_uri": source.get("source_uri"),
                "title": source.get("title"),
                "chunk_no": source.get("chunk_no"),
                "snippet": source.get("snippet"),
            }
        return {
            "document_id": str(source.document_id),
            "chunk_id": str(source.chunk_id),
            "source_uri": source.source_uri,
            "title": source.title,
            "chunk_no": source.chunk_no,
            "snippet": source.snippet,
        }

    # ---------------------------------------------------------------------
    # Heuristic extraction helpers
    # ---------------------------------------------------------------------

    def _extract_candidate_entities(self, text: str) -> list[str]:
        candidates = re.findall(r"\b(?:[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*)\b", text)
        filtered: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            normalized = normalize_text(candidate)
            if len(normalized) < 2:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            filtered.append(normalized)
        return filtered

    def _infer_entity_type(self, name: str) -> str:
        if "Inc" in name or "Corp" in name or "LLC" in name or "Company" in name:
            return "organization"
        if "Team" in name or "Department" in name:
            return "organization"
        if "Project" in name or "System" in name or "Platform" in name:
            return "system"
        return "concept"

    def _mention_count(self, text: str, name: str) -> int:
        return max(1, len(re.findall(re.escape(name), text, flags=re.IGNORECASE)))

    def _infer_relation_type(self, text: str) -> str:
        lowered = text.lower()
        if "depends on" in lowered:
            return "DEPENDS_ON"
        if "uses" in lowered or "utilizes" in lowered:
            return "USES"
        if "contains" in lowered or "includes" in lowered:
            return "CONTAINS"
        if "relates to" in lowered:
            return "RELATES_TO"
        return "CO_OCCURS_WITH"

    def _entity_name_score(self, query: str, canonical_name: str) -> float:
        normalized = canonical_name.lower()
        if normalized == query:
            return 1.0
        if normalized.startswith(query):
            return 0.9
        if query in normalized:
            return 0.75
        return 0.5

    def _build_summary_from_chunks(self, query: str, chunks: Sequence[str]) -> str:
        if not chunks:
            return f"No supporting chunks were found for '{query}'."
        lead = normalize_text(chunks[0])[:180]
        return f"Top result for '{query}' is grounded in: {lead}"

    # ---------------------------------------------------------------------
    # Vector helpers
    # ---------------------------------------------------------------------

    def _vector_literal(self, values: Sequence[float]) -> str:
        return "[" + ",".join(f"{value:.8f}" for value in values) + "]"

    def _parse_vector_text(self, raw_value: str | None) -> list[float]:
        if not raw_value:
            return []
        stripped = raw_value.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return []
        return [float(part) for part in stripped.split(",") if part.strip()]


__all__ = [
    "ChunkRecord",
    "DocumentRecord",
    "EntityRecord",
    "EntitySearchResult",
    "GraphRagRepository",
    "IngestionResult",
    "RelationRecord",
    "RetrievalResult",
    "SourceRecord",
    "chunk_text",
    "content_hash_for_text",
    "deterministic_embedding",
    "normalize_text",
]

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

from .embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    create_embedding_provider,
)

LOGGER = logging.getLogger(__name__)


def lexical_overlap_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    text_tokens = set(tokenize(text))
    if not query_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / max(1, len(query_tokens))


def coverage_overlap_score(query: str, text: str) -> float:
    query_tokens = tokenize(query)
    text_tokens = set(tokenize(text))
    if not query_tokens:
        return 0.0

    informative_query_tokens = [
        token
        for token in query_tokens
        if len(token) > 2
        and token
        not in {
            "the",
            "and",
            "for",
            "with",
            "from",
            "into",
            "onto",
            "that",
            "this",
            "uses",
            "used",
            "using",
            "does",
            "have",
            "has",
            "had",
        }
    ]
    basis = informative_query_tokens or query_tokens
    if not basis:
        return 0.0

    covered = sum(1 for token in basis if token in text_tokens)
    return covered / max(1, len(basis))


def jaccard_similarity_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    text_tokens = set(tokenize(text))
    if not query_tokens and not text_tokens:
        return 0.0
    union = query_tokens | text_tokens
    if not union:
        return 0.0
    return len(query_tokens & text_tokens) / len(union)


def phrase_match_score(query: str, text: str) -> float:
    normalized_query = normalize_text(query).lower()
    normalized_text = normalize_text(text).lower()
    if not normalized_query or not normalized_text:
        return 0.0
    if normalized_query in normalized_text:
        return 1.0
    query_terms = normalized_query.split(" ")
    if len(query_terms) > 1 and all(term in normalized_text for term in query_terms):
        return 0.75
    return 0.0


def proximity_score(query: str, text: str) -> float:
    query_terms = [term for term in tokenize(query) if term]
    text_terms = [term for term in tokenize(text) if term]
    if len(query_terms) < 2 or not text_terms:
        return 0.0

    positions: list[int] = []
    for term in query_terms:
        try:
            positions.append(text_terms.index(term))
        except ValueError:
            continue

    if len(positions) < 2:
        return 0.0

    span = max(positions) - min(positions)
    if span <= 1:
        return 1.0
    return max(0.0, 1.0 - min(span, 12) / 12.0)


def recency_score(rank: int, total_count: int) -> float:
    if total_count <= 1:
        return 1.0
    return max(0.0, 1.0 - (rank / max(1, total_count - 1)))


def _score_profile(profile: str) -> dict[str, float]:
    if profile == "hybrid":
        return {
            "embedding": 0.28,
            "lexical": 0.14,
            "coverage": 0.12,
            "jaccard": 0.06,
            "phrase": 0.10,
            "proximity": 0.05,
            "entity": 0.11,
            "relation": 0.10,
            "recency": 0.02,
            "exact_entity": 0.02,
        }
    return {
        "embedding": 0.34,
        "lexical": 0.18,
        "coverage": 0.14,
        "jaccard": 0.08,
        "phrase": 0.12,
        "proximity": 0.05,
        "entity": 0.05,
        "relation": 0.00,
        "recency": 0.02,
        "exact_entity": 0.02,
    }


def rerank_chunk_candidates(
    *,
    query: str,
    candidates: Sequence[dict[str, Any]],
    entity_names_by_chunk_id: Mapping[uuid.UUID, Sequence[str]] | None = None,
    relation_count_by_chunk_id: Mapping[uuid.UUID, int] | None = None,
    profile: str = "naive",
) -> list[dict[str, Any]]:
    entity_names_by_chunk_id = entity_names_by_chunk_id or {}
    relation_count_by_chunk_id = relation_count_by_chunk_id or {}
    weights = _score_profile(profile)

    reranked: list[dict[str, Any]] = []
    normalized_query = normalize_text(query)
    query_tokens = set(tokenize(normalized_query))
    total_candidates = len(candidates)

    for rank, candidate in enumerate(candidates):
        chunk_id = candidate["chunk_id"]
        text = candidate["text"]
        embedding_score = float(
            candidate.get("embedding_score", candidate.get("score", 0.0))
        )
        lexical_score = lexical_overlap_score(normalized_query, text)
        coverage_score = coverage_overlap_score(normalized_query, text)
        jaccard_score = jaccard_similarity_score(normalized_query, text)
        phrase_score = phrase_match_score(normalized_query, text)
        proximity = proximity_score(normalized_query, text)

        entity_names = entity_names_by_chunk_id.get(chunk_id, [])
        entity_hit_score = 0.0
        exact_entity_match_score = 0.0
        matched_entity_names: list[str] = []
        normalized_query_key = normalize_text(normalized_query).replace(" ", "").lower()
        for entity_name in entity_names:
            entity_tokens = set(tokenize(entity_name))
            entity_key = normalize_text(entity_name).replace(" ", "").lower()
            if query_tokens & entity_tokens:
                entity_hit_score = 1.0
                matched_entity_names.append(entity_name)
            if normalized_query_key and entity_key == normalized_query_key:
                exact_entity_match_score = 1.0
                if entity_name not in matched_entity_names:
                    matched_entity_names.append(entity_name)

        relation_count = relation_count_by_chunk_id.get(chunk_id, 0)
        relation_score = min(1.0, relation_count / 3.0)
        recency = recency_score(rank, total_candidates)

        final_score = (
            (embedding_score * weights["embedding"])
            + (lexical_score * weights["lexical"])
            + (coverage_score * weights["coverage"])
            + (jaccard_score * weights["jaccard"])
            + (phrase_score * weights["phrase"])
            + (proximity * weights["proximity"])
            + (entity_hit_score * weights["entity"])
            + (relation_score * weights["relation"])
            + (recency * weights["recency"])
            + (exact_entity_match_score * weights["exact_entity"])
        )

        reranked.append(
            {
                **candidate,
                "score": round(final_score, 6),
                "score_breakdown": {
                    "profile": profile,
                    "embedding_similarity": round(embedding_score, 6),
                    "lexical_overlap": round(lexical_score, 6),
                    "coverage_overlap": round(coverage_score, 6),
                    "jaccard_similarity": round(jaccard_score, 6),
                    "phrase_match": round(phrase_score, 6),
                    "term_proximity": round(proximity, 6),
                    "entity_hit": round(entity_hit_score, 6),
                    "exact_entity_match": round(exact_entity_match_score, 6),
                    "relation_evidence": round(relation_score, 6),
                    "relation_count": relation_count,
                    "matched_entity_names": matched_entity_names,
                    "recency": round(recency, 6),
                    "weights": {key: round(value, 4) for key, value in weights.items()},
                    "final_score": round(final_score, 6),
                },
            }
        )

    reranked.sort(
        key=lambda item: (
            -float(item["score"]),
            -float(item["score_breakdown"]["embedding_similarity"]),
            -float(item["score_breakdown"]["lexical_overlap"]),
            item["chunk_no"],
        )
    )
    return reranked


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
        embedding_provider_name: str = "openai",
        embedding_model_name: str = "text-embedding-3-small",
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
        self._embedding_provider_name = embedding_provider_name
        self._embedding_model_name = embedding_model_name
        self._embedding_provider = self._build_embedding_provider()

    def connection(self) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self._dsn,
            row_factory=dict_row,
            application_name=self._app_name,
        )

    def _log_db_span(
        self,
        *,
        operation: str,
        started_at: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "event": "db_span",
            "db_operation": operation,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
        if extra:
            payload.update(extra)
        LOGGER.info("Repository DB span", extra=payload)

    def _bounded_top_k(self, value: int) -> int:
        if value < 1:
            raise ValueError("top_k must be greater than zero.")
        return min(value, self._max_return_chunks)

    def _bounded_graph_limit(self, value: int) -> int:
        if value < 1:
            raise ValueError("graph_limit must be greater than zero.")
        return min(value, self._max_return_entities)

    def _bounded_hops(self, value: int) -> int:
        if value < 1:
            raise ValueError("hops must be greater than zero.")
        return min(value, self._max_graph_hops)

    def _build_embedding_provider(self) -> EmbeddingProvider:
        try:
            return create_embedding_provider(
                provider_name=self._embedding_provider_name,
                model_name=self._embedding_model_name,
                dimensions=self._embedding_dimensions,
            )
        except EmbeddingProviderError:
            return create_embedding_provider(
                provider_name="deterministic",
                model_name="deterministic-placeholder-v1",
                dimensions=self._embedding_dimensions,
            )

    def _embed_text(self, text: str, *, input_type: str) -> tuple[list[float], str]:
        try:
            vector = self._embedding_provider.embed_text(text, input_type=input_type)
            provider_mode = getattr(
                self._embedding_provider,
                "provider_mode",
                self._embedding_provider.provider_name,
            )
            return vector.to_list(), str(provider_mode)
        except EmbeddingProviderError:
            return (
                deterministic_embedding(text, self._embedding_dimensions),
                "deterministic-fallback",
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

        effective_top_k = self._bounded_top_k(top_k)
        retrieval_id = uuid.uuid4()
        query_embedding, query_embedding_mode = self._embed_text(
            normalized_query,
            input_type="query",
        )

        started_at = time.perf_counter()
        with self.connection() as conn:
            candidates = self._rank_chunks_by_similarity(
                conn,
                query=query,
                query_embedding=query_embedding,
                top_k=effective_top_k,
            )
            chunk_ids = [item["chunk_id"] for item in candidates]
            entity_names_by_chunk_id = self._entity_names_by_chunk_ids(conn, chunk_ids)
            relation_count_by_chunk_id = self._relation_count_by_chunk_ids(
                conn, chunk_ids
            )
            reranked_candidates = rerank_chunk_candidates(
                query=normalized_query,
                candidates=candidates,
                entity_names_by_chunk_id=entity_names_by_chunk_id,
                relation_count_by_chunk_id=relation_count_by_chunk_id,
                profile="naive",
            )
            supporting_chunks = [
                self._chunk_payload(item) for item in reranked_candidates
            ]
            sources = [self._source_payload(item) for item in reranked_candidates]
            summary = self._build_summary_from_chunks(
                normalized_query,
                [item["text"] for item in reranked_candidates],
            )
            confidence = round(
                max((item["score"] for item in reranked_candidates), default=0.0),
                4,
            )
            timings = {
                "strategy": "deterministic-local-reranked",
                "candidate_count": len(reranked_candidates),
                "requested_top_k": top_k,
                "effective_top_k": effective_top_k,
                "embedding_provider": self._embedding_provider.provider_name,
                "embedding_model": self._embedding_provider.model_name,
                "embedding_provider_mode": query_embedding_mode,
            }

            self._insert_retrieval_log(
                conn,
                retrieval_id=retrieval_id,
                query_text=normalized_query,
                mode="naive",
                returned_source_ids=[
                    str(item["chunk_id"]) for item in reranked_candidates
                ],
                timings=timings,
            )
            self._log_db_span(
                operation="retrieve_naive",
                started_at=started_at,
                extra={
                    "retrieval_id": str(retrieval_id),
                    "requested_top_k": top_k,
                    "effective_top_k": effective_top_k,
                    "candidate_count": len(reranked_candidates),
                    "embedding_provider": self._embedding_provider.provider_name,
                    "embedding_model": self._embedding_provider.model_name,
                    "embedding_provider_mode": query_embedding_mode,
                },
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
        effective_hops = self._bounded_hops(hops)
        effective_limit = self._bounded_graph_limit(limit)

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
        effective_top_k = self._bounded_top_k(top_k)
        effective_graph_limit = self._bounded_graph_limit(graph_limit)

        naive = self.retrieve_naive(query=query, top_k=effective_top_k)
        supporting_chunk_ids = [
            uuid.UUID(item["chunk_id"]) for item in naive.supporting_chunks
        ]

        started_at = time.perf_counter()
        with self.connection() as conn:
            entities = self._entities_for_chunks(conn, supporting_chunk_ids)
            relationships = self._relationships_for_entity_ids(
                conn,
                [uuid.UUID(item["entity_id"]) for item in entities],
                limit=effective_graph_limit,
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

            reranked_supporting_chunks = rerank_chunk_candidates(
                query=query,
                candidates=list(naive.supporting_chunks),
                entity_names_by_chunk_id=self._entity_names_by_chunk_ids(
                    conn,
                    [uuid.UUID(item["chunk_id"]) for item in naive.supporting_chunks],
                ),
                relation_count_by_chunk_id=self._relation_count_by_chunk_ids(
                    conn,
                    [uuid.UUID(item["chunk_id"]) for item in naive.supporting_chunks],
                ),
                profile="hybrid",
            )
            summary = naive.summary
            if entities:
                sample_names = ", ".join(
                    item["canonical_name"] for item in entities[:4]
                )
                summary = f"{summary} Related entities include {sample_names}."

            retrieval_id = uuid.uuid4()
            timings = {
                "strategy": "naive_plus_local_graph_reranked",
                "chunk_count": len(reranked_supporting_chunks),
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
                timings={
                    **timings,
                    "requested_top_k": top_k,
                    "effective_top_k": effective_top_k,
                    "requested_graph_limit": graph_limit,
                    "effective_graph_limit": effective_graph_limit,
                },
            )
            self._log_db_span(
                operation="retrieve_local_graph",
                started_at=started_at,
                extra={
                    "retrieval_id": str(retrieval_id),
                    "requested_top_k": top_k,
                    "effective_top_k": effective_top_k,
                    "requested_graph_limit": graph_limit,
                    "effective_graph_limit": effective_graph_limit,
                    "entity_count": len(entities),
                    "relationship_count": len(relationships),
                },
            )

            return RetrievalResult(
                retrieval_id=retrieval_id,
                summary=summary,
                mode="local_graph",
                supporting_chunks=[dict(item) for item in reranked_supporting_chunks],
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
        effective_top_k = self._bounded_top_k(top_k)
        effective_graph_limit = self._bounded_graph_limit(graph_limit)

        local_graph = self.retrieve_local_graph(
            query=query,
            top_k=effective_top_k,
            graph_limit=effective_graph_limit,
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

        reranked_supporting_chunks = []
        for rank, item in enumerate(local_graph.supporting_chunks):
            relation_bonus = 0.0
            supporting_relation_types: list[str] = []
            for relationship in enriched_relationships:
                if relationship.get("evidence_chunk_id") == item.get("chunk_id"):
                    relation_bonus = min(relation_bonus + 0.2, 1.0)
                    relation_type = relationship.get("relation_type")
                    if relation_type and relation_type not in supporting_relation_types:
                        supporting_relation_types.append(str(relation_type))

            base_score = float(item.get("score", 0.0))
            lexical_score = lexical_overlap_score(query, item.get("text", ""))
            jaccard_score = jaccard_similarity_score(query, item.get("text", ""))
            phrase_score = phrase_match_score(query, item.get("text", ""))
            proximity = proximity_score(query, item.get("text", ""))
            recency = recency_score(rank, len(local_graph.supporting_chunks))

            final_score = (
                (base_score * 0.50)
                + (lexical_score * 0.16)
                + (jaccard_score * 0.06)
                + (phrase_score * 0.08)
                + (proximity * 0.05)
                + (relation_bonus * 0.12)
                + (recency * 0.03)
            )

            reranked_supporting_chunks.append(
                {
                    **dict(item),
                    "score": round(final_score, 6),
                    "score_breakdown": {
                        "profile": "hybrid-secondary",
                        "base_rank_score": round(base_score, 6),
                        "lexical_overlap": round(lexical_score, 6),
                        "jaccard_similarity": round(jaccard_score, 6),
                        "phrase_match": round(phrase_score, 6),
                        "term_proximity": round(proximity, 6),
                        "relation_evidence": round(relation_bonus, 6),
                        "supporting_relation_types": supporting_relation_types,
                        "recency": round(recency, 6),
                        "weights": {
                            "base_rank_score": 0.50,
                            "lexical_overlap": 0.16,
                            "jaccard_similarity": 0.06,
                            "phrase_match": 0.08,
                            "term_proximity": 0.05,
                            "relation_evidence": 0.12,
                            "recency": 0.03,
                        },
                        "final_score": round(final_score, 6),
                    },
                }
            )

        reranked_supporting_chunks.sort(
            key=lambda item: (-float(item["score"]), item["chunk_no"])
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
            "strategy": "hybrid-reranked",
            "chunk_count": len(reranked_supporting_chunks),
            "entity_count": len(enriched_entities),
            "relationship_count": len(enriched_relationships),
            "source_count": len(sources),
        }

        started_at = time.perf_counter()
        with self.connection() as conn:
            self._insert_retrieval_log(
                conn,
                retrieval_id=retrieval_id,
                query_text=normalize_text(query),
                mode="hybrid",
                returned_source_ids=[
                    str(item["chunk_id"]) for item in sources if item.get("chunk_id")
                ],
                timings={
                    **timings,
                    "requested_top_k": top_k,
                    "effective_top_k": effective_top_k,
                    "requested_graph_limit": graph_limit,
                    "effective_graph_limit": effective_graph_limit,
                },
            )
            self._log_db_span(
                operation="retrieve_hybrid",
                started_at=started_at,
                extra={
                    "retrieval_id": str(retrieval_id),
                    "requested_top_k": top_k,
                    "effective_top_k": effective_top_k,
                    "requested_graph_limit": graph_limit,
                    "effective_graph_limit": effective_graph_limit,
                    "entity_count": len(enriched_entities),
                    "relationship_count": len(enriched_relationships),
                    "source_count": len(sources),
                },
            )

        return RetrievalResult(
            retrieval_id=retrieval_id,
            summary=summary,
            mode="hybrid",
            supporting_chunks=[dict(item) for item in reranked_supporting_chunks],
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
            refresh_scope = "document" if document_id else "full"

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

            node_count = projected_documents + projected_chunks + projected_entities
            edge_count = (
                projected_chunks
                + projected_relations
                + sum(
                    1 for _ in self._chunk_entity_rows_for_documents(conn, document_ids)
                )
            )
            self._insert_graph_refresh_log(
                conn,
                graph_name=self._age_graph_name,
                refresh_scope=refresh_scope,
                document_id=document_id,
                node_count=node_count,
                edge_count=edge_count,
                status="completed",
                metadata={
                    "full_rebuild": full_rebuild,
                    "document_count": len(document_ids),
                    "projected_documents": projected_documents,
                    "projected_chunks": projected_chunks,
                    "projected_entities": projected_entities,
                    "projected_relations": projected_relations,
                },
            )

            return {
                "graph_name": self._age_graph_name,
                "document_scope": str(document_id) if document_id else "all",
                "full_rebuild": full_rebuild,
                "projected_documents": projected_documents,
                "projected_chunks": projected_chunks,
                "projected_entities": projected_entities,
                "projected_relations": projected_relations,
                "refresh_scope": refresh_scope,
                "node_count": node_count,
                "edge_count": edge_count,
                "status": "completed",
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
            embedding, provider_mode = self._embed_text(
                chunk_body,
                input_type="document",
            )
            chunk_metadata = {
                "char_count": len(chunk_body),
                "embedding_provider": self._embedding_provider.provider_name,
                "embedding_model": self._embedding_provider.model_name,
                "embedding_dimensions": self._embedding_provider.dimensions,
                "embedding_provider_mode": provider_mode,
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
            extracted_entities = self._extract_candidate_entities(chunk.text)
            names = [item["canonical_name"] for item in extracted_entities][
                : self._max_return_entities
            ]
            associated_ids: list[uuid.UUID] = []
            mention_metadata_by_name = {
                item["canonical_name"]: item for item in extracted_entities
            }

            for name in names:
                mention_metadata = mention_metadata_by_name.get(name, {})
                entity = self._get_or_create_entity(
                    conn,
                    canonical_name=name,
                    entity_type=self._infer_entity_type(name),
                    aliases=mention_metadata.get("aliases", []),
                    metadata={
                        "extractor": "heuristic-v2",
                        "token_basis": mention_metadata.get("token_basis", []),
                    },
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
                            int(mention_metadata.get("mention_count", 1)),
                            json_dumps(
                                {
                                    "extractor": "heuristic-v2",
                                    "entity_type": mention_metadata.get("entity_type"),
                                    "aliases": mention_metadata.get("aliases", []),
                                    "token_basis": mention_metadata.get(
                                        "token_basis", []
                                    ),
                                    "start_offset": mention_metadata.get(
                                        "start_offset"
                                    ),
                                    "end_offset": mention_metadata.get("end_offset"),
                                }
                            ),
                        ),
                    )

            chunk_entity_ids[chunk.chunk_id] = associated_ids

        relation_records_by_id: dict[uuid.UUID, RelationRecord] = {}
        for chunk in chunk_records:
            entity_ids = chunk_entity_ids.get(chunk.chunk_id, [])
            if len(entity_ids) < 2:
                continue

            chunk_relations = self._extract_candidate_relations(
                chunk.text,
                entity_records_by_id=entity_records_by_id,
            )
            if chunk_relations:
                for relation_candidate in chunk_relations:
                    relation = self._upsert_relation_fact(
                        conn,
                        source_entity_id=relation_candidate["source_entity_id"],
                        target_entity_id=relation_candidate["target_entity_id"],
                        relation_type=relation_candidate["relation_type"],
                        evidence_chunk_id=chunk.chunk_id,
                        weight=relation_candidate["weight"],
                        metadata={
                            "extractor": "heuristic-v2",
                            "pattern": relation_candidate["pattern"],
                            "token_distance": relation_candidate["token_distance"],
                            "evidence_strength": "pattern-match",
                        },
                    )
                    relation_records_by_id[relation.relation_fact_id] = relation
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
                    weight=0.25,
                    metadata={
                        "extractor": "heuristic-v2",
                        "pattern": "fallback-adjacent",
                        "evidence_strength": "weak-fallback",
                    },
                )
                relation_records_by_id[relation.relation_fact_id] = relation

        return list(entity_records_by_id.values()), list(
            relation_records_by_id.values()
        )

    def _get_or_create_entity(
        self,
        conn: psycopg.Connection[Any],
        *,
        canonical_name: str,
        entity_type: str,
        aliases: Sequence[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EntityRecord:
        aliases = [
            alias for alias in (aliases or []) if alias and alias != canonical_name
        ]
        metadata = metadata or {}

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
                existing = self._entity_from_row(row)
                merged_aliases = sorted(
                    {
                        *existing.aliases,
                        *aliases,
                    }
                )
                merged_metadata = {
                    **existing.metadata,
                    **metadata,
                }
                cur.execute(
                    """
                    UPDATE entity
                    SET aliases = %s::jsonb,
                        metadata = %s::jsonb
                    WHERE entity_id = %s
                    RETURNING
                        entity_id,
                        canonical_name,
                        entity_type,
                        aliases,
                        metadata,
                        created_at
                    """,
                    (
                        json_dumps(merged_aliases),
                        json_dumps(merged_metadata),
                        existing.entity_id,
                    ),
                )
                updated = cur.fetchone()
                return self._entity_from_row(updated)

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
                    json_dumps(sorted(set(aliases))),
                    json_dumps({"extractor": "heuristic-v2", **metadata}),
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
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> RelationRecord:
        metadata = metadata or {}

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
                existing_record = self._relation_from_row(existing)
                merged_metadata = {
                    **existing_record.metadata,
                    **metadata,
                }
                cur.execute(
                    """
                    UPDATE relation_fact
                    SET weight = %s,
                        metadata = %s::jsonb
                    WHERE relation_fact_id = %s
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
                        float(weight),
                        json_dumps(merged_metadata),
                        existing_record.relation_fact_id,
                    ),
                )
                updated = cur.fetchone()
                return self._relation_from_row(updated)

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
                    float(weight),
                    evidence_chunk_id,
                    json_dumps({"extractor": "heuristic-v2", **metadata}),
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

    def _insert_graph_refresh_log(
        self,
        conn: psycopg.Connection[Any],
        *,
        graph_name: str,
        refresh_scope: str,
        document_id: uuid.UUID | None,
        node_count: int,
        edge_count: int,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
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
                    uuid.uuid4(),
                    graph_name,
                    refresh_scope,
                    document_id,
                    node_count,
                    edge_count,
                    status,
                    json_dumps(metadata),
                    utc_now(),
                    utc_now(),
                ),
            )

    def _chunk_entity_rows_for_documents(
        self,
        conn: psycopg.Connection[Any],
        document_ids: Sequence[uuid.UUID],
    ) -> list[dict[str, Any]]:
        if not document_ids:
            return []
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
                WHERE c.document_id = ANY(%s)
                """,
                (list(document_ids),),
            )
            return list(cur.fetchall())

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

        scored: list[dict[str, Any]] = []

        for row in rows:
            chunk_embedding = self._parse_vector_text(row["embedding_text"])
            embedding_score = cosine_similarity(query_embedding, chunk_embedding)

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
                    "embedding_score": round(embedding_score, 6),
                    "score": round(embedding_score, 6),
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

    def _entity_names_by_chunk_ids(
        self,
        conn: psycopg.Connection[Any],
        chunk_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, list[str]]:
        if not chunk_ids:
            return {}

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ce.chunk_id,
                    e.canonical_name
                FROM chunk_entity ce
                JOIN entity e
                  ON e.entity_id = ce.entity_id
                WHERE ce.chunk_id = ANY(%s)
                ORDER BY ce.chunk_id, e.canonical_name
                """,
                (list(chunk_ids),),
            )
            rows = cur.fetchall()

        result: dict[uuid.UUID, list[str]] = {}
        for row in rows:
            result.setdefault(row["chunk_id"], []).append(row["canonical_name"])
        return result

    def _relation_count_by_chunk_ids(
        self,
        conn: psycopg.Connection[Any],
        chunk_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        if not chunk_ids:
            return {}

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    evidence_chunk_id AS chunk_id,
                    COUNT(*) AS relation_count
                FROM relation_fact
                WHERE evidence_chunk_id = ANY(%s)
                GROUP BY evidence_chunk_id
                """,
                (list(chunk_ids),),
            )
            rows = cur.fetchall()

        result: dict[uuid.UUID, int] = {}
        for row in rows:
            result[row["chunk_id"]] = int(row["relation_count"])
        return result

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
            payload = {
                "document_id": str(document_id) if document_id is not None else None,
                "chunk_id": str(chunk_id) if chunk_id is not None else None,
                "source_uri": source.get("source_uri"),
                "title": source.get("title"),
                "chunk_no": source.get("chunk_no"),
                "snippet": source.get("snippet"),
            }
            if "score" in source:
                payload["score"] = round(float(source.get("score", 0.0)), 6)
            if "score_breakdown" in source:
                payload["score_breakdown"] = dict(source.get("score_breakdown", {}))
            return payload
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

    def _extract_candidate_entities(self, text: str) -> list[dict[str, Any]]:
        sentence_matches = list(re.finditer(r"[^.!?。！？]+(?:[.!?。！？]|$)", text))
        filtered: list[dict[str, Any]] = []
        filtered_by_key: dict[str, dict[str, Any]] = {}

        for sentence_match in sentence_matches:
            sentence_text = sentence_match.group(0)
            sentence_start = sentence_match.start()

            candidates = re.finditer(
                r"\b(?:[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\b",
                sentence_text,
            )

            for match in candidates:
                raw_candidate = match.group(0)
                normalized = normalize_text(raw_candidate)
                if len(normalized) < 3:
                    continue

                normalized = self._trim_entity_phrase_boundary(normalized)
                if len(normalized) < 3:
                    continue
                if self._is_noise_entity_candidate(normalized):
                    continue

                lowered = self._canonical_entity_key(normalized)

                token_basis = normalized.split(" ")
                aliases = self._build_entity_aliases(normalized, token_basis)
                mention_count = self._mention_count(text, normalized)

                local_start = match.start()
                start_offset = sentence_start + local_start
                end_offset = start_offset + len(normalized)

                candidate_payload = {
                    "canonical_name": normalized,
                    "entity_type": self._infer_entity_type(normalized),
                    "aliases": aliases,
                    "token_basis": token_basis,
                    "mention_count": mention_count,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "sentence_start_offset": sentence_start,
                    "sentence_end_offset": sentence_match.end(),
                }

                existing = filtered_by_key.get(lowered)
                if existing is None:
                    filtered_by_key[lowered] = candidate_payload
                    continue

                existing_name = str(existing["canonical_name"])
                existing_token_count = len(existing_name.split(" "))
                normalized_token_count = len(token_basis)

                prefer_replacement = False
                if normalized_token_count > existing_token_count:
                    prefer_replacement = True
                elif normalized_token_count == existing_token_count and len(
                    normalized
                ) > len(existing_name):
                    prefer_replacement = True

                if prefer_replacement:
                    filtered_by_key[lowered] = candidate_payload

        filtered = list(filtered_by_key.values())
        filtered.sort(
            key=lambda item: (
                -int(item["mention_count"]),
                int(item["start_offset"]),
                item["canonical_name"],
            )
        )
        return filtered

    def _infer_entity_type(self, name: str) -> str:
        if "Inc" in name or "Corp" in name or "LLC" in name or "Company" in name:
            return "organization"
        if "Team" in name or "Department" in name:
            return "organization"
        if "Project" in name or "System" in name or "Platform" in name:
            return "system"
        if "API" in name or "Service" in name:
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
        if "connects to" in lowered or "connected to" in lowered:
            return "CONNECTS_TO"
        if "part of" in lowered or "belongs to" in lowered:
            return "PART_OF"
        if "relates to" in lowered:
            return "RELATES_TO"
        return "CO_OCCURS_WITH"

    def _extract_candidate_relations(
        self,
        text: str,
        *,
        entity_records_by_id: dict[uuid.UUID, EntityRecord],
    ) -> list[dict[str, Any]]:
        if not entity_records_by_id:
            return []

        relation_patterns: list[tuple[str, str]] = [
            ("DEPENDS_ON", "depends on"),
            ("USES", "uses"),
            ("CONTAINS", "contains"),
            ("CONNECTS_TO", "connects to"),
            ("PART_OF", "part of"),
            ("RELATES_TO", "relates to"),
        ]

        entity_mentions = self._extract_candidate_entities(text)
        if not entity_mentions:
            return []

        entity_by_name = {
            self._canonical_entity_key(entity.canonical_name): entity
            for entity in entity_records_by_id.values()
        }
        matched_mentions: list[dict[str, Any]] = []
        for mention in entity_mentions:
            canonical_name = self._canonical_entity_key(str(mention["canonical_name"]))
            entity = entity_by_name.get(canonical_name)
            if entity is None:
                continue
            matched_mentions.append(
                {
                    **mention,
                    "entity_id": entity.entity_id,
                }
            )

        relations: list[dict[str, Any]] = []
        for sentence_match in re.finditer(r"[^.!?。！？]+(?:[.!?。！？]|$)", text):
            sentence_text = sentence_match.group(0)
            sentence_start = sentence_match.start()
            lowered_sentence = sentence_text.lower()

            sentence_mentions = [
                item
                for item in matched_mentions
                if int(item["start_offset"]) >= sentence_start
                and int(item["end_offset"]) <= sentence_match.end()
            ]

            if len(sentence_mentions) < 2:
                continue

            for relation_type, pattern in relation_patterns:
                pattern_start = lowered_sentence.find(pattern)
                if pattern_start == -1:
                    continue

                absolute_pattern_start = sentence_start + pattern_start
                absolute_pattern_end = absolute_pattern_start + len(pattern)

                source_candidates = [
                    item
                    for item in sentence_mentions
                    if int(item["end_offset"]) <= absolute_pattern_start
                ]
                target_candidates = [
                    item
                    for item in sentence_mentions
                    if int(item["start_offset"]) >= absolute_pattern_end
                ]

                if not source_candidates or not target_candidates:
                    continue

                source = max(
                    source_candidates,
                    key=lambda item: (
                        int(item["end_offset"]),
                        int(item["mention_count"]),
                    ),
                )
                target = min(
                    target_candidates,
                    key=lambda item: (
                        int(item["start_offset"]),
                        -int(item["mention_count"]),
                    ),
                )

                if source["entity_id"] == target["entity_id"]:
                    continue

                token_distance = max(
                    1,
                    len(
                        tokenize(
                            text[
                                int(source["end_offset"]) : int(target["start_offset"])
                            ]
                        )
                    ),
                )
                if token_distance > 8:
                    continue

                weight = round(
                    max(
                        0.6,
                        1.0 - ((token_distance - 1) * 0.03),
                    ),
                    4,
                )

                relations.append(
                    {
                        "source_entity_id": source["entity_id"],
                        "target_entity_id": target["entity_id"],
                        "relation_type": relation_type,
                        "weight": weight,
                        "pattern": pattern,
                        "token_distance": token_distance,
                        "sentence_start_offset": sentence_start,
                        "sentence_end_offset": sentence_match.end(),
                    }
                )

        deduped: list[dict[str, Any]] = []
        seen_keys: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
        for relation in relations:
            key = (
                relation["source_entity_id"],
                relation["target_entity_id"],
                relation["relation_type"],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(relation)
        return deduped

    def _is_noise_entity_candidate(self, candidate: str) -> bool:
        generic_singletons = {
            "Graph",
            "Memory",
            "Source",
            "Trace",
            "Evidence",
            "Bundle",
            "System",
            "Service",
            "Project",
            "Platform",
            "Data",
            "Model",
            "Cache",
            "Store",
            "Worker",
            "Engine",
            "Control",
            "Plane",
            "Node",
            "Metadata",
        }
        if candidate in generic_singletons:
            return True

        token_basis = candidate.split(" ")
        if len(token_basis) == 1:
            token = token_basis[0]
            if len(token) <= 4 and token.isalpha():
                return True
            if token.lower() in {
                "service",
                "system",
                "platform",
                "project",
                "engine",
                "worker",
                "store",
                "cache",
                "model",
            }:
                return True

        return False

    def _build_entity_aliases(
        self,
        normalized: str,
        token_basis: list[str],
    ) -> list[str]:
        aliases: set[str] = set()

        if len(token_basis) > 1:
            compact = normalized.replace(" ", "")
            if compact != normalized and len(compact) > 4:
                aliases.add(compact)

        if len(token_basis) >= 2:
            spaced_lower = " ".join(token_basis)
            compact_lower = "".join(token_basis)
            if compact_lower and compact_lower != spaced_lower:
                aliases.add(compact_lower)

        if len(token_basis) > 2:
            initials = "".join(token[0] for token in token_basis if token)
            if len(initials) > 1:
                aliases.add(initials)

        return sorted(
            {
                alias
                for alias in aliases
                if alias != normalized and not self._is_noise_entity_candidate(alias)
            }
        )

    def _trim_entity_phrase_boundary(self, candidate: str) -> str:
        token_basis = candidate.split(" ")

        leading_prefix_tokens = {
            "The",
            "This",
            "That",
            "These",
            "Those",
        }
        leading_generic_role_tokens = {
            "Platform",
            "Project",
            "Service",
            "System",
            "Module",
            "Layer",
        }
        trailing_conjunction_tokens = {"And", "Or", "But"}
        trailing_generic_role_tokens = {
            "Service",
            "System",
            "Module",
            "Layer",
            "Store",
            "Engine",
        }
        protected_store_phrases = {
            "Graph Memory Store",
        }

        while token_basis and token_basis[0] in leading_prefix_tokens:
            token_basis = token_basis[1:]

        while len(token_basis) > 2 and token_basis[0] in leading_generic_role_tokens:
            token_basis = token_basis[1:]

        while token_basis and token_basis[-1] in trailing_conjunction_tokens:
            token_basis = token_basis[:-1]

        while (
            len(token_basis) > 2
            and token_basis[-1] in trailing_generic_role_tokens
            and " ".join(token_basis) not in protected_store_phrases
        ):
            token_basis = token_basis[:-1]

        return " ".join(token_basis).strip()

    def _canonical_entity_key(self, value: str) -> str:
        return normalize_text(value).replace(" ", "").lower()

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

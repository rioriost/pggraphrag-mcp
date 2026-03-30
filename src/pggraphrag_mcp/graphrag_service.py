from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .config import AppConfig
from .logging_utils import get_logger

LOGGER = get_logger(__name__)


class RepositoryProtocol(Protocol):
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
    ) -> Any: ...

    def document_reingest(
        self,
        *,
        tenant_id: str,
        source_uri: str,
        title: str,
        text: str,
        mime_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    def document_delete(self, *, document_id: uuid.UUID) -> bool: ...

    def graph_refresh(
        self,
        *,
        conn: Any,
        document_id: uuid.UUID | None = None,
        full_rebuild: bool = False,
    ) -> dict[str, Any]: ...

    def connection(self) -> Any: ...

    def retrieve_naive(
        self,
        *,
        query: str,
        top_k: int = 5,
    ) -> Any: ...

    def retrieve_local_graph(
        self,
        *,
        query: str,
        top_k: int = 5,
        graph_limit: int = 20,
    ) -> Any: ...

    def retrieve_hybrid(
        self,
        *,
        query: str,
        top_k: int = 5,
        graph_limit: int = 20,
    ) -> Any: ...

    def entity_search(
        self,
        *,
        query: str,
        limit: int = 10,
    ) -> list[Any]: ...

    def entity_expand(
        self,
        *,
        entity_id: uuid.UUID,
        hops: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]: ...

    def source_trace(
        self,
        *,
        retrieval_id: uuid.UUID,
    ) -> dict[str, Any]: ...


@dataclass(slots=True, frozen=True)
class IngestDocumentCommand:
    tenant_id: str
    source_uri: str
    title: str
    text: str
    mime_type: str = "text/plain"
    metadata: dict[str, Any] | None = None
    reingest: bool = True


@dataclass(slots=True, frozen=True)
class GraphRefreshCommand:
    document_id: uuid.UUID | None = None
    full_rebuild: bool = False


@dataclass(slots=True, frozen=True)
class RetrievalCommand:
    query: str
    top_k: int = 5
    graph_limit: int | None = None


@dataclass(slots=True, frozen=True)
class EntitySearchCommand:
    query: str
    limit: int = 10


@dataclass(slots=True, frozen=True)
class EntityExpandCommand:
    entity_id: uuid.UUID
    hops: int = 1
    limit: int = 20


@dataclass(slots=True, frozen=True)
class SourceTraceCommand:
    retrieval_id: uuid.UUID


class GraphRAGServiceError(RuntimeError):
    """Base exception for GraphRAG service failures."""


class GraphRAGValidationError(GraphRAGServiceError):
    """Raised when a caller provides invalid input."""


class GraphRAGApplicationService:
    """
    Repository-backed GraphRAG application service.

    Responsibilities:
    - validate and normalize application inputs
    - apply config-driven limits
    - orchestrate ingestion, graph refresh, retrieval, and trace flows
    - add lightweight operation timing and structured logging
    - return plain dictionaries ready for JSON-RPC transport
    """

    def __init__(
        self,
        *,
        repository: RepositoryProtocol,
        config: AppConfig,
    ) -> None:
        self._repository = repository
        self._config = config

    # ------------------------------------------------------------------
    # Public ingestion methods
    # ------------------------------------------------------------------

    def document_ingest(self, command: IngestDocumentCommand) -> dict[str, Any]:
        tenant_id = self._require_text(command.tenant_id, field_name="tenant_id")
        source_uri = self._require_text(command.source_uri, field_name="source_uri")
        title = self._require_text(command.title, field_name="title")
        text = self._require_text(command.text, field_name="text")
        mime_type = self._require_text(command.mime_type, field_name="mime_type")
        metadata = self._normalize_metadata(command.metadata)

        started = time.perf_counter()
        LOGGER.info(
            "Starting document ingestion",
            extra={
                "event": "document_ingest_started",
                "tenant_id": tenant_id,
                "source_uri": source_uri,
                "title": title,
                "reingest": command.reingest,
            },
        )

        result = self._repository.document_ingest(
            tenant_id=tenant_id,
            source_uri=source_uri,
            title=title,
            text=text,
            mime_type=mime_type,
            metadata=metadata,
            reingest=command.reingest,
        )

        elapsed_ms = self._elapsed_ms(started)
        payload = self._normalize_ingestion_result(result, elapsed_ms=elapsed_ms)

        LOGGER.info(
            "Completed document ingestion",
            extra={
                "event": "document_ingest_completed",
                "tenant_id": tenant_id,
                "source_uri": source_uri,
                "document_id": payload["document"]["document_id"],
                "chunk_count": payload["chunk_count"],
                "entity_count": payload["entity_count"],
                "relation_count": payload["relation_count"],
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    def document_reingest(self, command: IngestDocumentCommand) -> dict[str, Any]:
        tenant_id = self._require_text(command.tenant_id, field_name="tenant_id")
        source_uri = self._require_text(command.source_uri, field_name="source_uri")
        title = self._require_text(command.title, field_name="title")
        text = self._require_text(command.text, field_name="text")
        mime_type = self._require_text(command.mime_type, field_name="mime_type")
        metadata = self._normalize_metadata(command.metadata)

        started = time.perf_counter()
        LOGGER.info(
            "Starting document reingestion",
            extra={
                "event": "document_reingest_started",
                "tenant_id": tenant_id,
                "source_uri": source_uri,
                "title": title,
            },
        )

        result = self._repository.document_reingest(
            tenant_id=tenant_id,
            source_uri=source_uri,
            title=title,
            text=text,
            mime_type=mime_type,
            metadata=metadata,
        )

        elapsed_ms = self._elapsed_ms(started)
        payload = self._normalize_ingestion_result(result, elapsed_ms=elapsed_ms)

        LOGGER.info(
            "Completed document reingestion",
            extra={
                "event": "document_reingest_completed",
                "tenant_id": tenant_id,
                "source_uri": source_uri,
                "document_id": payload["document"]["document_id"],
                "chunk_count": payload["chunk_count"],
                "entity_count": payload["entity_count"],
                "relation_count": payload["relation_count"],
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    def document_delete(self, *, document_id: str | uuid.UUID) -> dict[str, Any]:
        normalized_document_id = self._coerce_uuid(
            document_id, field_name="document_id"
        )

        started = time.perf_counter()
        deleted = self._repository.document_delete(document_id=normalized_document_id)
        elapsed_ms = self._elapsed_ms(started)

        payload = {
            "document_id": str(normalized_document_id),
            "deleted": bool(deleted),
            "elapsed_ms": elapsed_ms,
        }

        LOGGER.info(
            "Completed document delete",
            extra={
                "event": "document_delete_completed",
                "document_id": str(normalized_document_id),
                "deleted": bool(deleted),
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    # ------------------------------------------------------------------
    # Public graph methods
    # ------------------------------------------------------------------

    def graph_refresh(self, command: GraphRefreshCommand) -> dict[str, Any]:
        if command.document_id is not None and command.full_rebuild:
            raise GraphRAGValidationError(
                "document_id and full_rebuild cannot be used together."
            )

        started = time.perf_counter()
        with self._repository.connection() as conn:
            summary = self._repository.graph_refresh(
                conn=conn,
                document_id=command.document_id,
                full_rebuild=command.full_rebuild,
            )

        elapsed_ms = self._elapsed_ms(started)
        payload = {
            "graph_name": summary.get("graph_name", self._config.age_graph_name),
            "document_scope": summary.get("document_scope"),
            "full_rebuild": bool(summary.get("full_rebuild", command.full_rebuild)),
            "projected_documents": int(summary.get("projected_documents", 0)),
            "projected_chunks": int(summary.get("projected_chunks", 0)),
            "projected_entities": int(summary.get("projected_entities", 0)),
            "projected_relations": int(summary.get("projected_relations", 0)),
            "elapsed_ms": elapsed_ms,
        }

        LOGGER.info(
            "Completed graph refresh",
            extra={
                "event": "graph_refresh_completed",
                **payload,
            },
        )
        return payload

    # ------------------------------------------------------------------
    # Public retrieval methods
    # ------------------------------------------------------------------

    def retrieve_naive(self, command: RetrievalCommand) -> dict[str, Any]:
        query = self._require_text(command.query, field_name="query")
        top_k = self._bounded_top_k(command.top_k)

        started = time.perf_counter()
        result = self._repository.retrieve_naive(query=query, top_k=top_k)
        elapsed_ms = self._elapsed_ms(started)

        payload = self._normalize_retrieval_result(result, elapsed_ms=elapsed_ms)

        LOGGER.info(
            "Completed naive retrieval",
            extra={
                "event": "retrieve_naive_completed",
                "retrieval_id": payload["retrieval_id"],
                "top_k": top_k,
                "chunk_count": len(payload["supporting_chunks"]),
                "confidence": payload["confidence"],
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    def retrieve_local_graph(self, command: RetrievalCommand) -> dict[str, Any]:
        query = self._require_text(command.query, field_name="query")
        top_k = self._bounded_top_k(command.top_k)
        graph_limit = self._bounded_graph_limit(command.graph_limit)

        started = time.perf_counter()
        result = self._repository.retrieve_local_graph(
            query=query,
            top_k=top_k,
            graph_limit=graph_limit,
        )
        elapsed_ms = self._elapsed_ms(started)

        payload = self._normalize_retrieval_result(result, elapsed_ms=elapsed_ms)

        LOGGER.info(
            "Completed local graph retrieval",
            extra={
                "event": "retrieve_local_graph_completed",
                "retrieval_id": payload["retrieval_id"],
                "top_k": top_k,
                "graph_limit": graph_limit,
                "chunk_count": len(payload["supporting_chunks"]),
                "entity_count": len(payload["entities"]),
                "relationship_count": len(payload["relationships"]),
                "confidence": payload["confidence"],
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    def retrieve_hybrid(self, command: RetrievalCommand) -> dict[str, Any]:
        query = self._require_text(command.query, field_name="query")
        top_k = self._bounded_top_k(command.top_k)
        graph_limit = self._bounded_graph_limit(command.graph_limit)

        started = time.perf_counter()
        result = self._repository.retrieve_hybrid(
            query=query,
            top_k=top_k,
            graph_limit=graph_limit,
        )
        elapsed_ms = self._elapsed_ms(started)

        payload = self._normalize_retrieval_result(result, elapsed_ms=elapsed_ms)

        LOGGER.info(
            "Completed hybrid retrieval",
            extra={
                "event": "retrieve_hybrid_completed",
                "retrieval_id": payload["retrieval_id"],
                "top_k": top_k,
                "graph_limit": graph_limit,
                "chunk_count": len(payload["supporting_chunks"]),
                "entity_count": len(payload["entities"]),
                "relationship_count": len(payload["relationships"]),
                "source_count": len(payload["sources"]),
                "confidence": payload["confidence"],
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    # ------------------------------------------------------------------
    # Public entity / trace methods
    # ------------------------------------------------------------------

    def entity_search(self, command: EntitySearchCommand) -> dict[str, Any]:
        query = self._require_text(command.query, field_name="query")
        limit = self._bounded_entity_limit(command.limit)

        started = time.perf_counter()
        results = self._repository.entity_search(query=query, limit=limit)
        elapsed_ms = self._elapsed_ms(started)

        payload = {
            "query": query,
            "limit": limit,
            "results": [self._normalize_entity_search_result(item) for item in results],
            "elapsed_ms": elapsed_ms,
        }

        LOGGER.info(
            "Completed entity search",
            extra={
                "event": "entity_search_completed",
                "query": query,
                "limit": limit,
                "result_count": len(payload["results"]),
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    def entity_expand(self, command: EntityExpandCommand) -> dict[str, Any]:
        entity_id = self._coerce_uuid(command.entity_id, field_name="entity_id")
        hops = self._bounded_hops(command.hops)
        limit = self._bounded_entity_limit(command.limit)

        started = time.perf_counter()
        result = self._repository.entity_expand(
            entity_id=entity_id,
            hops=hops,
            limit=limit,
        )
        elapsed_ms = self._elapsed_ms(started)

        payload = {
            "root_entity": self._normalize_entity_payload(result.get("root_entity")),
            "hops": int(result.get("hops", hops)),
            "entities": [
                self._normalize_entity_payload(item)
                for item in result.get("entities", [])
            ],
            "relationships": [
                self._normalize_relationship_payload(item)
                for item in result.get("relationships", [])
            ],
            "sources": [
                self._normalize_source_payload(item)
                for item in result.get("sources", [])
            ],
            "elapsed_ms": elapsed_ms,
        }

        LOGGER.info(
            "Completed entity expand",
            extra={
                "event": "entity_expand_completed",
                "entity_id": str(entity_id),
                "hops": hops,
                "limit": limit,
                "entity_count": len(payload["entities"]),
                "relationship_count": len(payload["relationships"]),
                "source_count": len(payload["sources"]),
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    def source_trace(self, command: SourceTraceCommand) -> dict[str, Any]:
        retrieval_id = self._coerce_uuid(
            command.retrieval_id, field_name="retrieval_id"
        )

        started = time.perf_counter()
        result = self._repository.source_trace(retrieval_id=retrieval_id)
        elapsed_ms = self._elapsed_ms(started)

        payload = {
            "retrieval_id": str(retrieval_id),
            "query_text": result.get("query_text"),
            "mode": result.get("mode"),
            "timings": self._normalize_timings(
                result.get("timings"),
                elapsed_ms=elapsed_ms,
            ),
            "created_at": result.get("created_at"),
            "sources": [
                self._normalize_source_payload(item)
                for item in result.get("sources", [])
            ],
        }

        LOGGER.info(
            "Completed source trace lookup",
            extra={
                "event": "source_trace_completed",
                "retrieval_id": str(retrieval_id),
                "source_count": len(payload["sources"]),
                "elapsed_ms": elapsed_ms,
            },
        )
        return payload

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "app_name": self._config.app_name,
            "app_version": self._config.app_version,
            "environment": self._config.env,
            "embedding_provider": self._config.embedding_provider,
            "embedding_model": self._config.embedding_model,
            "embedding_dimensions": self._config.embedding_dimensions,
            "max_vector_candidates": self._config.max_vector_candidates,
            "max_graph_hops": self._config.max_graph_hops,
            "max_return_chunks": self._config.max_return_chunks,
            "max_return_entities": self._config.max_return_entities,
            "graph_name": self._config.age_graph_name,
        }

    def _normalize_ingestion_result(
        self,
        result: Any,
        *,
        elapsed_ms: float,
    ) -> dict[str, Any]:
        document = getattr(result, "document", None)
        chunks = list(getattr(result, "chunks", []) or [])
        entities = list(getattr(result, "entities", []) or [])
        relations = list(getattr(result, "relations", []) or [])
        graph_refresh_summary = getattr(result, "graph_refresh_summary", {}) or {}

        return {
            "ingestion_job_id": str(getattr(result, "ingestion_job_id")),
            "document": self._normalize_document_record(document),
            "chunks": [self._normalize_chunk_record(item) for item in chunks],
            "entities": [self._normalize_entity_record(item) for item in entities],
            "relations": [self._normalize_relation_record(item) for item in relations],
            "chunk_count": len(chunks),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "graph_refresh_summary": {
                "graph_name": graph_refresh_summary.get(
                    "graph_name", self._config.age_graph_name
                ),
                "document_scope": graph_refresh_summary.get("document_scope"),
                "full_rebuild": bool(graph_refresh_summary.get("full_rebuild", False)),
                "projected_documents": int(
                    graph_refresh_summary.get("projected_documents", 0)
                ),
                "projected_chunks": int(
                    graph_refresh_summary.get("projected_chunks", 0)
                ),
                "projected_entities": int(
                    graph_refresh_summary.get("projected_entities", 0)
                ),
                "projected_relations": int(
                    graph_refresh_summary.get("projected_relations", 0)
                ),
            },
            "elapsed_ms": elapsed_ms,
        }

    def _normalize_retrieval_result(
        self,
        result: Any,
        *,
        elapsed_ms: float,
    ) -> dict[str, Any]:
        raw_supporting_chunks = list(getattr(result, "supporting_chunks", []) or [])
        raw_entities = list(getattr(result, "entities", []) or [])
        raw_relationships = list(getattr(result, "relationships", []) or [])
        raw_sources = list(getattr(result, "sources", []) or [])

        supporting_chunks = [
            self._normalize_chunk_result(item)
            for item in raw_supporting_chunks[: self._config.max_return_chunks]
        ]

        entities = [
            self._normalize_entity_result(item)
            for item in raw_entities[: self._config.max_return_entities]
        ]

        relationships = [
            self._normalize_relationship_result(item)
            for item in raw_relationships[: self._config.max_return_entities]
        ]

        max_sources = max(
            self._config.max_return_chunks,
            self._config.max_return_entities,
        )
        sources = [
            self._normalize_source_payload(item) for item in raw_sources[:max_sources]
        ]

        confidence = self._bounded_confidence(getattr(result, "confidence", 0.0))
        summary = self._require_text_or_default(
            getattr(result, "summary", None),
            default="No summary available.",
        )

        return {
            "retrieval_id": str(getattr(result, "retrieval_id")),
            "summary": summary,
            "mode": self._require_text_or_default(
                getattr(result, "mode", None),
                default="unknown",
            ),
            "supporting_chunks": supporting_chunks,
            "entities": entities,
            "relationships": relationships,
            "sources": sources,
            "confidence": confidence,
            "limits_applied": {
                "requested_supporting_chunks": len(raw_supporting_chunks),
                "returned_supporting_chunks": len(supporting_chunks),
                "max_return_chunks": self._config.max_return_chunks,
                "requested_entities": len(raw_entities),
                "returned_entities": len(entities),
                "max_return_entities": self._config.max_return_entities,
                "requested_relationships": len(raw_relationships),
                "returned_relationships": len(relationships),
                "requested_sources": len(raw_sources),
                "returned_sources": len(sources),
                "max_sources": max_sources,
            },
            "timings": self._normalize_timings(
                getattr(result, "timings", None),
                elapsed_ms=elapsed_ms,
                operation="retrieval",
            ),
        }

    def _normalize_entity_search_result(self, item: Any) -> dict[str, Any]:
        return {
            "entity": self._normalize_entity_record(getattr(item, "entity", None)),
            "evidence_chunks": [
                self._normalize_source_payload(source)
                for source in list(getattr(item, "evidence_chunks", []) or [])
            ],
            "score": round(float(getattr(item, "score", 0.0)), 4),
        }

    def _normalize_document_record(self, document: Any) -> dict[str, Any]:
        if document is None:
            return {}
        return {
            "document_id": str(getattr(document, "document_id")),
            "tenant_id": getattr(document, "tenant_id", None),
            "source_uri": getattr(document, "source_uri", None),
            "title": getattr(document, "title", None),
            "mime_type": getattr(document, "mime_type", None),
            "content_hash": getattr(document, "content_hash", None),
            "status": getattr(document, "status", None),
            "created_at": self._isoformat(getattr(document, "created_at", None)),
            "updated_at": self._isoformat(getattr(document, "updated_at", None)),
        }

    def _normalize_chunk_record(self, chunk: Any) -> dict[str, Any]:
        if chunk is None:
            return {}
        return {
            "chunk_id": str(getattr(chunk, "chunk_id")),
            "document_id": str(getattr(chunk, "document_id")),
            "chunk_no": int(getattr(chunk, "chunk_no", 0)),
            "text": getattr(chunk, "text", ""),
            "token_count": int(getattr(chunk, "token_count", 0)),
            "metadata": dict(getattr(chunk, "metadata", {}) or {}),
            "created_at": self._isoformat(getattr(chunk, "created_at", None)),
        }

    def _normalize_entity_record(self, entity: Any) -> dict[str, Any]:
        if entity is None:
            return {}
        return {
            "entity_id": str(getattr(entity, "entity_id")),
            "canonical_name": getattr(entity, "canonical_name", None),
            "entity_type": getattr(entity, "entity_type", None),
            "aliases": list(getattr(entity, "aliases", []) or []),
            "metadata": dict(getattr(entity, "metadata", {}) or {}),
            "created_at": self._isoformat(getattr(entity, "created_at", None)),
        }

    def _normalize_relation_record(self, relation: Any) -> dict[str, Any]:
        if relation is None:
            return {}
        evidence_chunk_id = getattr(relation, "evidence_chunk_id", None)
        return {
            "relation_fact_id": str(getattr(relation, "relation_fact_id")),
            "source_entity_id": str(getattr(relation, "source_entity_id")),
            "target_entity_id": str(getattr(relation, "target_entity_id")),
            "relation_type": getattr(relation, "relation_type", None),
            "weight": round(float(getattr(relation, "weight", 0.0)), 4),
            "evidence_chunk_id": str(evidence_chunk_id) if evidence_chunk_id else None,
            "metadata": dict(getattr(relation, "metadata", {}) or {}),
            "created_at": self._isoformat(getattr(relation, "created_at", None)),
        }

    def _normalize_chunk_result(self, chunk: Any) -> dict[str, Any]:
        if chunk is None:
            return {}
        if isinstance(chunk, dict):
            chunk_id = chunk.get("chunk_id")
            document_id = chunk.get("document_id")
            return {
                "chunk_id": str(chunk_id) if chunk_id is not None else None,
                "document_id": str(document_id) if document_id is not None else None,
                "chunk_no": int(chunk.get("chunk_no", 0)),
                "text": chunk.get("text", ""),
                "score": round(float(chunk.get("score", 0.0)), 4),
                "source_uri": chunk.get("source_uri"),
                "title": chunk.get("title"),
                "metadata": dict(chunk.get("metadata", {}) or {}),
            }
        return {
            "chunk_id": str(getattr(chunk, "chunk_id")),
            "document_id": str(getattr(chunk, "document_id")),
            "chunk_no": int(getattr(chunk, "chunk_no", 0)),
            "text": getattr(chunk, "text", ""),
            "score": round(float(getattr(chunk, "score", 0.0)), 4),
            "source_uri": getattr(chunk, "source_uri", None),
            "title": getattr(chunk, "title", None),
            "metadata": dict(getattr(chunk, "metadata", {}) or {}),
        }

    def _normalize_entity_result(self, entity: Any) -> dict[str, Any]:
        if entity is None:
            return {}
        if isinstance(entity, dict):
            entity_id = entity.get("entity_id")
            return {
                "entity_id": str(entity_id) if entity_id is not None else None,
                "canonical_name": entity.get("canonical_name"),
                "entity_type": entity.get("entity_type"),
                "score": round(float(entity.get("score", 0.0)), 4),
                "aliases": list(entity.get("aliases", []) or []),
            }
        return {
            "entity_id": str(getattr(entity, "entity_id")),
            "canonical_name": getattr(entity, "canonical_name", None),
            "entity_type": getattr(entity, "entity_type", None),
            "score": round(float(getattr(entity, "score", 0.0)), 4),
            "aliases": list(getattr(entity, "aliases", []) or []),
        }

    def _normalize_relationship_result(self, relationship: Any) -> dict[str, Any]:
        if relationship is None:
            return {}
        if isinstance(relationship, dict):
            relation_fact_id = relationship.get("relation_fact_id")
            source_entity_id = relationship.get("source_entity_id")
            target_entity_id = relationship.get("target_entity_id")
            evidence_chunk_id = relationship.get("evidence_chunk_id")
            return {
                "relation_fact_id": str(relation_fact_id)
                if relation_fact_id is not None
                else None,
                "source_entity_id": str(source_entity_id)
                if source_entity_id is not None
                else None,
                "source_entity_name": relationship.get("source_entity_name"),
                "target_entity_id": str(target_entity_id)
                if target_entity_id is not None
                else None,
                "target_entity_name": relationship.get("target_entity_name"),
                "relation_type": relationship.get("relation_type"),
                "weight": round(float(relationship.get("weight", 0.0)), 4),
                "evidence_chunk_id": str(evidence_chunk_id)
                if evidence_chunk_id is not None
                else None,
                "metadata": dict(relationship.get("metadata", {}) or {}),
            }
        evidence_chunk_id = getattr(relationship, "evidence_chunk_id", None)
        return {
            "relation_fact_id": str(getattr(relationship, "relation_fact_id")),
            "source_entity_id": str(getattr(relationship, "source_entity_id")),
            "source_entity_name": getattr(relationship, "source_entity_name", None),
            "target_entity_id": str(getattr(relationship, "target_entity_id")),
            "target_entity_name": getattr(relationship, "target_entity_name", None),
            "relation_type": getattr(relationship, "relation_type", None),
            "weight": round(float(getattr(relationship, "weight", 0.0)), 4),
            "evidence_chunk_id": str(evidence_chunk_id) if evidence_chunk_id else None,
            "metadata": dict(getattr(relationship, "metadata", {}) or {}),
        }

    def _normalize_entity_payload(
        self, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not payload:
            return {}
        result = dict(payload)
        if "entity_id" in result and result["entity_id"] is not None:
            result["entity_id"] = str(result["entity_id"])
        return result

    def _normalize_relationship_payload(
        self,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not payload:
            return {}
        result = dict(payload)
        for key in (
            "relation_fact_id",
            "source_entity_id",
            "target_entity_id",
            "evidence_chunk_id",
        ):
            if key in result and result[key] is not None:
                result[key] = str(result[key])
        if "weight" in result and result["weight"] is not None:
            result["weight"] = round(float(result["weight"]), 4)
        return result

    def _normalize_source_payload(self, payload: Any) -> dict[str, Any]:
        if payload is None:
            return {}
        if isinstance(payload, dict):
            result = dict(payload)
        else:
            result = {
                "document_id": getattr(payload, "document_id", None),
                "chunk_id": getattr(payload, "chunk_id", None),
                "source_uri": getattr(payload, "source_uri", None),
                "title": getattr(payload, "title", None),
                "chunk_no": getattr(payload, "chunk_no", None),
                "snippet": getattr(payload, "snippet", None),
            }

        for key in ("document_id", "chunk_id"):
            if key in result and result[key] is not None:
                result[key] = str(result[key])
        return result

    def _normalize_timings(
        self,
        timings: dict[str, Any] | None,
        *,
        elapsed_ms: float,
        operation: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(timings or {})
        payload["elapsed_ms"] = elapsed_ms
        payload["elapsed_seconds"] = round(elapsed_ms / 1000.0, 6)
        payload["finished_at"] = datetime.now(UTC).isoformat()
        if operation is not None:
            payload["operation"] = operation
        return payload

    def _bounded_top_k(self, value: int) -> int:
        if value <= 0:
            raise GraphRAGValidationError("top_k must be greater than zero.")
        return min(
            int(value),
            int(self._config.max_return_chunks),
            int(self._config.max_vector_candidates),
        )

    def _bounded_graph_limit(self, value: int | None) -> int:
        limit = (
            int(value) if value is not None else int(self._config.max_return_entities)
        )
        if limit <= 0:
            raise GraphRAGValidationError("graph_limit must be greater than zero.")
        return min(
            limit,
            int(self._config.max_return_entities),
            int(self._config.max_vector_candidates),
        )

    def _bounded_entity_limit(self, value: int) -> int:
        if value <= 0:
            raise GraphRAGValidationError("limit must be greater than zero.")
        return min(int(value), int(self._config.max_return_entities))

    def _bounded_hops(self, value: int) -> int:
        if value <= 0:
            raise GraphRAGValidationError("hops must be greater than zero.")
        return min(int(value), int(self._config.max_graph_hops), 4)

    def _bounded_confidence(self, value: float) -> float:
        if math.isnan(value) or math.isinf(value):
            return 0.0
        return round(max(0.0, min(1.0, float(value))), 4)

    def _coerce_uuid(
        self,
        value: str | uuid.UUID,
        *,
        field_name: str,
    ) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        text = self._require_text(value, field_name=field_name)
        try:
            return uuid.UUID(text)
        except ValueError as exc:
            raise GraphRAGValidationError(
                f"{field_name} must be a valid UUID."
            ) from exc

    def _require_text(self, value: Any, *, field_name: str) -> str:
        if not isinstance(value, str):
            raise GraphRAGValidationError(f"{field_name} must be a string.")
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise GraphRAGValidationError(f"{field_name} must not be empty.")
        return normalized

    def _require_text_or_default(self, value: Any, *, default: str) -> str:
        if not isinstance(value, str):
            return default
        normalized = " ".join(value.split()).strip()
        return normalized or default

    def _normalize_metadata(self, value: dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise GraphRAGValidationError("metadata must be a JSON object.")
        return dict(value)

    def _elapsed_ms(self, started: float) -> float:
        return round((time.perf_counter() - started) * 1000.0, 2)

    def _isoformat(self, value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


__all__ = [
    "EntityExpandCommand",
    "EntitySearchCommand",
    "GraphRAGApplicationService",
    "GraphRAGServiceError",
    "GraphRAGValidationError",
    "GraphRefreshCommand",
    "IngestDocumentCommand",
    "RepositoryProtocol",
    "RetrievalCommand",
    "SourceTraceCommand",
]

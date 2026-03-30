# ruff: noqa: E402
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pggraphrag_mcp.config import AppConfig
from pggraphrag_mcp.graphrag_service import (
    EntityExpandCommand,
    EntitySearchCommand,
    GraphRAGApplicationService,
    GraphRAGValidationError,
    GraphRefreshCommand,
    IngestDocumentCommand,
    RetrievalCommand,
    SourceTraceCommand,
)


class FakeSafetyRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

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
    ) -> Any:
        self.calls.append(
            (
                "document_ingest",
                {
                    "tenant_id": tenant_id,
                    "source_uri": source_uri,
                    "title": title,
                    "text": text,
                    "mime_type": mime_type,
                    "metadata": metadata or {},
                    "reingest": reingest,
                },
            )
        )
        return _obj(
            ingestion_job_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            document=_obj(
                document_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                tenant_id=tenant_id,
                source_uri=source_uri,
                title=title,
                mime_type=mime_type,
                content_hash="hash",
                status="active",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:01+00:00",
            ),
            chunks=[],
            entities=[],
            relations=[],
            graph_refresh_summary={
                "graph_name": "pggraphrag_memory",
                "document_scope": "22222222-2222-2222-2222-222222222222",
                "full_rebuild": False,
                "projected_documents": 1,
                "projected_chunks": 0,
                "projected_entities": 0,
                "projected_relations": 0,
            },
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
    ) -> Any:
        self.calls.append(
            (
                "document_reingest",
                {
                    "tenant_id": tenant_id,
                    "source_uri": source_uri,
                    "title": title,
                    "text": text,
                    "mime_type": mime_type,
                    "metadata": metadata or {},
                },
            )
        )
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
        self.calls.append(("document_delete", {"document_id": document_id}))
        return True

    def graph_refresh(
        self,
        *,
        conn: Any,
        document_id: uuid.UUID | None = None,
        full_rebuild: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "graph_refresh",
                {
                    "conn": conn,
                    "document_id": document_id,
                    "full_rebuild": full_rebuild,
                },
            )
        )
        return {
            "graph_name": "pggraphrag_memory",
            "document_scope": str(document_id) if document_id else "all",
            "full_rebuild": full_rebuild,
            "projected_documents": 1 if document_id else 2,
            "projected_chunks": 2,
            "projected_entities": 3,
            "projected_relations": 1,
            "refresh_scope": "document" if document_id else "full",
            "node_count": 6,
            "edge_count": 5,
            "status": "completed",
        }

    def connection(self) -> Any:
        self.calls.append(("connection", {}))
        return _FakeConnection()

    def retrieve_naive(
        self,
        *,
        query: str,
        top_k: int = 5,
    ) -> Any:
        self.calls.append(("retrieve_naive", {"query": query, "top_k": top_k}))
        return _retrieval_result(
            retrieval_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            mode="naive",
            summary=f"naive summary for {query}",
            chunk_count=min(top_k, 3),
            entity_count=0,
            relationship_count=0,
        )

    def retrieve_local_graph(
        self,
        *,
        query: str,
        top_k: int = 5,
        graph_limit: int = 20,
    ) -> Any:
        self.calls.append(
            (
                "retrieve_local_graph",
                {"query": query, "top_k": top_k, "graph_limit": graph_limit},
            )
        )
        return _retrieval_result(
            retrieval_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            mode="local_graph",
            summary=f"local graph summary for {query}",
            chunk_count=min(top_k, 3),
            entity_count=min(graph_limit, 4),
            relationship_count=min(graph_limit, 3),
        )

    def retrieve_hybrid(
        self,
        *,
        query: str,
        top_k: int = 5,
        graph_limit: int = 20,
    ) -> Any:
        self.calls.append(
            (
                "retrieve_hybrid",
                {"query": query, "top_k": top_k, "graph_limit": graph_limit},
            )
        )
        return _retrieval_result(
            retrieval_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
            mode="hybrid",
            summary=f"hybrid summary for {query}",
            chunk_count=min(top_k, 3),
            entity_count=min(graph_limit, 4),
            relationship_count=min(graph_limit, 3),
        )

    def entity_search(
        self,
        *,
        query: str,
        limit: int = 10,
    ) -> list[Any]:
        self.calls.append(("entity_search", {"query": query, "limit": limit}))
        return []

    def entity_expand(
        self,
        *,
        entity_id: uuid.UUID,
        hops: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "entity_expand",
                {"entity_id": entity_id, "hops": hops, "limit": limit},
            )
        )
        return {
            "root_entity": {
                "entity_id": str(entity_id),
                "canonical_name": "GraphRAG",
                "entity_type": "concept",
                "aliases": ["GraphRAG"],
            },
            "hops": hops,
            "entities": [],
            "relationships": [],
            "sources": [],
        }

    def source_trace(
        self,
        *,
        retrieval_id: uuid.UUID,
    ) -> dict[str, Any]:
        self.calls.append(("source_trace", {"retrieval_id": retrieval_id}))
        return {
            "retrieval_id": str(retrieval_id),
            "query_text": "graph query",
            "mode": "hybrid",
            "timings": {"strategy": "hybrid"},
            "created_at": "2026-01-01T00:00:05+00:00",
            "sources": [],
        }


class _FakeConnection:
    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _obj(**kwargs: Any) -> Any:
    class Obj:
        pass

    instance = Obj()
    for key, value in kwargs.items():
        setattr(instance, key, value)
    return instance


def _retrieval_result(
    *,
    retrieval_id: uuid.UUID,
    mode: str,
    summary: str,
    chunk_count: int,
    entity_count: int,
    relationship_count: int,
) -> Any:
    supporting_chunks = []
    for index in range(chunk_count):
        supporting_chunks.append(
            {
                "chunk_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:chunk:{index}")
                ),
                "document_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:document:{index}")
                ),
                "chunk_no": index,
                "text": f"{mode} chunk {index} for testing",
                "score": 0.9 - (index * 0.1),
                "source_uri": f"memory://docs/{mode}/{index}",
                "title": f"{mode.title()} document {index}",
                "metadata": {
                    "char_count": 32,
                    "score_breakdown": {
                        "embedding_similarity": 0.8,
                        "lexical_overlap": 0.7,
                        "final_score": 0.9 - (index * 0.1),
                    },
                },
            }
        )

    entities = []
    for index in range(entity_count):
        entities.append(
            {
                "entity_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:entity:{index}")
                ),
                "canonical_name": f"Entity {index}",
                "entity_type": "concept",
                "score": 0.8 - (index * 0.05),
                "aliases": [],
                "metadata": {},
            }
        )

    relationships = []
    for index in range(relationship_count):
        relationships.append(
            {
                "relation_fact_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:relation:{index}")
                ),
                "source_entity_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:entity:{index}")
                ),
                "source_entity_name": f"Entity {index}",
                "target_entity_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:entity:{index + 1}")
                ),
                "target_entity_name": f"Entity {index + 1}",
                "relation_type": "RELATES_TO",
                "weight": 1.0,
                "evidence_chunk_id": supporting_chunks[0]["chunk_id"]
                if supporting_chunks
                else None,
                "metadata": {},
            }
        )

    sources = []
    for chunk in supporting_chunks:
        sources.append(
            {
                "document_id": chunk["document_id"],
                "chunk_id": chunk["chunk_id"],
                "source_uri": chunk["source_uri"],
                "title": chunk["title"],
                "chunk_no": chunk["chunk_no"],
                "snippet": chunk["text"],
            }
        )

    return _obj(
        retrieval_id=retrieval_id,
        summary=summary,
        mode=mode,
        supporting_chunks=supporting_chunks,
        entities=entities,
        relationships=relationships,
        sources=sources,
        confidence=0.85,
        timings={"strategy": mode, "candidate_count": chunk_count},
    )


def _config() -> AppConfig:
    return AppConfig(
        app_name="pggraphrag-mcp",
        app_version="0.1.0",
        env="test",
        http_host="127.0.0.1",
        http_port=8080,
        http_path="/mcp",
        public_base_url="https://localhost:9443",
        enable_debug_endpoints=True,
        log_level="INFO",
        small_auth_token="test-token",
        auth_header_name="X-Authenticated-Identity",
        auth_identity="test-client",
        db_name="pggraphrag",
        db_user="pggraphrag_app",
        db_password="secret",
        db_host="pggraphrag-db",
        db_port=5432,
        database_url="postgresql://pggraphrag_app:secret@pggraphrag-db:5432/pggraphrag",
        age_graph_name="pggraphrag_memory",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        max_vector_candidates=3,
        max_graph_hops=2,
        max_return_chunks=4,
        max_return_entities=5,
        tls_cert_file="/certs/dev.crt",
        tls_key_file="/certs/dev.key",
        private_image="pggraphrag-mcp-private:local",
        auth_image="pggraphrag-mcp-auth:local",
        db_image="pggraphrag-db:local",
    )


def _service() -> tuple[GraphRAGApplicationService, FakeSafetyRepository]:
    repository = FakeSafetyRepository()
    service = GraphRAGApplicationService(
        repository=repository,
        config=_config(),
    )
    return service, repository


def test_document_ingest_rejects_overly_long_title() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="title must be <= 500 characters"
    ):
        service.document_ingest(
            IngestDocumentCommand(
                tenant_id="tenant-a",
                source_uri="memory://docs/alpha",
                title="A" * 501,
                text="GraphRAG",
            )
        )


def test_document_ingest_rejects_overly_long_source_uri() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError,
        match="source_uri must be <= 2000 characters",
    ):
        service.document_ingest(
            IngestDocumentCommand(
                tenant_id="tenant-a",
                source_uri="m" * 2001,
                title="Alpha",
                text="GraphRAG",
            )
        )


def test_document_ingest_rejects_non_object_metadata() -> None:
    service, _repository = _service()

    with pytest.raises(GraphRAGValidationError, match="metadata must be a JSON object"):
        service.document_ingest(
            IngestDocumentCommand(
                tenant_id="tenant-a",
                source_uri="memory://docs/alpha",
                title="Alpha",
                text="GraphRAG",
                metadata="not-a-dict",  # type: ignore[arg-type]
            )
        )


def test_document_delete_rejects_invalid_uuid() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="document_id must be a valid UUID"
    ):
        service.document_delete(document_id="not-a-uuid")


def test_graph_refresh_rejects_invalid_document_id_type() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="document_id must be a valid UUID"
    ):
        service.graph_refresh(
            GraphRefreshCommand(
                document_id="not-a-uuid",  # type: ignore[arg-type]
                full_rebuild=False,
            )
        )


def test_retrieve_naive_rejects_empty_query() -> None:
    service, _repository = _service()

    with pytest.raises(GraphRAGValidationError, match="query must not be empty"):
        service.retrieve_naive(RetrievalCommand(query="   ", top_k=1))


def test_retrieve_naive_caps_top_k_by_vector_candidate_limit() -> None:
    service, repository = _service()

    payload = service.retrieve_naive(RetrievalCommand(query="GraphRAG", top_k=99))

    assert len(payload["supporting_chunks"]) == 3
    assert repository.calls[-1] == (
        "retrieve_naive",
        {"query": "GraphRAG", "top_k": 3},
    )


def test_retrieve_local_graph_rejects_non_positive_graph_limit() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="graph_limit must be greater than zero"
    ):
        service.retrieve_local_graph(
            RetrievalCommand(query="GraphRAG", top_k=2, graph_limit=0)
        )


def test_retrieve_local_graph_caps_graph_limit_by_vector_candidate_limit() -> None:
    service, repository = _service()

    payload = service.retrieve_local_graph(
        RetrievalCommand(query="GraphRAG", top_k=5, graph_limit=99)
    )

    assert len(payload["entities"]) <= 3
    assert len(payload["relationships"]) <= 3
    assert repository.calls[-1] == (
        "retrieve_local_graph",
        {"query": "GraphRAG", "top_k": 3, "graph_limit": 3},
    )


def test_retrieve_hybrid_limits_applied_are_bounded() -> None:
    service, _repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(query="GraphRAG", top_k=99, graph_limit=99)
    )

    assert payload["limits_applied"]["max_return_chunks"] == 4
    assert payload["limits_applied"]["max_return_entities"] == 5
    assert payload["limits_applied"]["returned_supporting_chunks"] <= 4
    assert payload["limits_applied"]["returned_entities"] <= 5
    assert payload["limits_applied"]["returned_relationships"] <= 5


def test_entity_search_rejects_empty_query() -> None:
    service, _repository = _service()

    with pytest.raises(GraphRAGValidationError, match="query must not be empty"):
        service.entity_search(EntitySearchCommand(query="   ", limit=1))


def test_entity_expand_rejects_invalid_uuid() -> None:
    service, _repository = _service()

    with pytest.raises(GraphRAGValidationError, match="entity_id must be a valid UUID"):
        service.entity_expand(
            EntityExpandCommand(
                entity_id="bad-uuid",  # type: ignore[arg-type]
                hops=1,
                limit=1,
            )
        )


def test_entity_expand_caps_hops_by_configured_limit() -> None:
    service, repository = _service()

    payload = service.entity_expand(
        EntityExpandCommand(
            entity_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
            hops=99,
            limit=5,
        )
    )

    assert payload["hops"] == 2
    assert repository.calls[-1] == (
        "entity_expand",
        {
            "entity_id": uuid.UUID("99999999-9999-9999-9999-999999999999"),
            "hops": 2,
            "limit": 5,
        },
    )


def test_source_trace_rejects_invalid_uuid() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="retrieval_id must be a valid UUID"
    ):
        service.source_trace(
            SourceTraceCommand(
                retrieval_id="bad-uuid",  # type: ignore[arg-type]
            )
        )


def test_retrieval_payloads_remain_json_safe_and_bounded() -> None:
    service, _repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(query="GraphRAG", top_k=99, graph_limit=99)
    )

    for chunk in payload["supporting_chunks"]:
        assert isinstance(chunk["chunk_id"], str)
        assert isinstance(chunk["document_id"], str)
        assert isinstance(chunk["text"], str)

    for entity in payload["entities"]:
        assert isinstance(entity["entity_id"], str)
        assert isinstance(entity["canonical_name"], str)

    for relationship in payload["relationships"]:
        assert isinstance(relationship["relation_fact_id"], str)
        assert isinstance(relationship["source_entity_id"], str)
        assert isinstance(relationship["target_entity_id"], str)

    for source in payload["sources"]:
        assert isinstance(source["document_id"], str)
        assert isinstance(source["chunk_id"], str)

    assert isinstance(payload["timings"]["elapsed_ms"], float)
    assert payload["timings"]["elapsed_ms"] >= 0.0

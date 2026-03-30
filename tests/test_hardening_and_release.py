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


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._last_retrieval_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self._last_document_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

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
                document_id=self._last_document_id,
                tenant_id=tenant_id,
                source_uri=source_uri,
                title=title,
                mime_type=mime_type,
                content_hash="hash",
                status="active",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:01+00:00",
            ),
            chunks=[
                _obj(
                    chunk_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                    document_id=self._last_document_id,
                    chunk_no=0,
                    text=text,
                    token_count=5,
                    metadata={"origin": "fake"},
                    created_at="2026-01-01T00:00:01+00:00",
                )
            ],
            entities=[
                _obj(
                    entity_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
                    canonical_name="GraphRAG",
                    entity_type="concept",
                    aliases=["GraphRAG"],
                    metadata={"origin": "fake"},
                    created_at="2026-01-01T00:00:01+00:00",
                )
            ],
            relations=[],
            graph_refresh_summary={
                "graph_name": "pggraphrag_memory",
                "document_scope": str(self._last_document_id),
                "full_rebuild": False,
                "projected_documents": 1,
                "projected_chunks": 1,
                "projected_entities": 1,
                "projected_relations": 0,
                "refresh_scope": "document",
                "node_count": 3,
                "edge_count": 2,
                "status": "completed",
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
            "projected_documents": 1 if document_id else 4,
            "projected_chunks": 2 if document_id else 10,
            "projected_entities": 3 if document_id else 12,
            "projected_relations": 1 if document_id else 16,
            "refresh_scope": "document" if document_id else "full",
            "node_count": 6 if document_id else 26,
            "edge_count": 5 if document_id else 32,
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
            retrieval_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            mode="naive",
            query=query,
            top_k=top_k,
            chunk_count=top_k,
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
                {
                    "query": query,
                    "top_k": top_k,
                    "graph_limit": graph_limit,
                },
            )
        )
        return _retrieval_result(
            retrieval_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
            mode="local_graph",
            query=query,
            top_k=top_k,
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
                {
                    "query": query,
                    "top_k": top_k,
                    "graph_limit": graph_limit,
                },
            )
        )
        return _retrieval_result(
            retrieval_id=self._last_retrieval_id,
            mode="hybrid",
            query=query,
            top_k=top_k,
            chunk_count=min(top_k, 4),
            entity_count=min(graph_limit, 5),
            relationship_count=min(graph_limit, 4),
        )

    def entity_search(
        self,
        *,
        query: str,
        limit: int = 10,
    ) -> list[Any]:
        self.calls.append(("entity_search", {"query": query, "limit": limit}))
        return [
            _obj(
                entity=_obj(
                    entity_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
                    canonical_name="GraphRAG",
                    entity_type="concept",
                    aliases=["GraphRAG"],
                    metadata={},
                    created_at="2026-01-01T00:00:00+00:00",
                ),
                evidence_chunks=[
                    {
                        "document_id": str(self._last_document_id),
                        "chunk_id": "77777777-7777-7777-7777-777777777777",
                        "source_uri": "memory://docs/graphrag",
                        "title": "GraphRAG Overview",
                        "chunk_no": 0,
                        "snippet": "GraphRAG retrieval and graph reasoning.",
                    }
                ],
                score=0.9,
            )
        ]

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
                {
                    "entity_id": entity_id,
                    "hops": hops,
                    "limit": limit,
                },
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
            "entities": [
                {
                    "entity_id": str(entity_id),
                    "canonical_name": "GraphRAG",
                    "entity_type": "concept",
                    "aliases": ["GraphRAG"],
                }
            ],
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
            "sources": [
                {
                    "document_id": str(self._last_document_id),
                    "chunk_id": "88888888-8888-8888-8888-888888888888",
                    "source_uri": "memory://docs/graphrag",
                    "title": "GraphRAG Overview",
                    "chunk_no": 0,
                    "snippet": "Traceable evidence bundle.",
                }
            ],
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
    query: str,
    top_k: int,
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
                "text": f"{mode} chunk {index} for {query}",
                "score": 0.9 - (index * 0.05),
                "source_uri": f"memory://docs/{mode}/{index}",
                "title": f"{mode.title()} document {index}",
            }
        )

    entities = []
    for index in range(entity_count):
        entities.append(
            {
                "entity_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:entity:{index}")
                ),
                "canonical_name": f"{mode.title()} Entity {index}",
                "entity_type": "concept",
                "score": 0.8 - (index * 0.05),
                "aliases": [f"{mode.title()}Alias{index}"],
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
                "source_entity_name": f"{mode.title()} Entity {index}",
                "target_entity_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:entity:{index + 1}")
                ),
                "target_entity_name": f"{mode.title()} Entity {index + 1}",
                "relation_type": "RELATES_TO",
                "weight": 1.0,
                "evidence_chunk_id": supporting_chunks[0]["chunk_id"]
                if supporting_chunks
                else None,
            }
        )

    return _obj(
        retrieval_id=retrieval_id,
        summary=f"{mode} summary for {query}",
        mode=mode,
        supporting_chunks=supporting_chunks,
        entities=entities,
        relationships=relationships,
        sources=[
            {
                "document_id": supporting_chunks[0]["document_id"]
                if supporting_chunks
                else None,
                "chunk_id": supporting_chunks[0]["chunk_id"]
                if supporting_chunks
                else None,
                "source_uri": supporting_chunks[0]["source_uri"]
                if supporting_chunks
                else None,
                "title": supporting_chunks[0]["title"] if supporting_chunks else None,
                "chunk_no": 0,
                "snippet": supporting_chunks[0]["text"] if supporting_chunks else None,
            }
        ],
        confidence=0.75,
        timings={"strategy": mode, "candidate_count": top_k},
    )


def _config() -> AppConfig:
    return AppConfig(
        app_name="pggraphrag-mcp",
        app_version="0.1.0",
        env="test",
        http_host="127.0.0.1",
        http_port=8080,
        http_path="/mcp",
        public_base_url="https://localhost:8443",
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


def _service() -> tuple[GraphRAGApplicationService, FakeRepository]:
    repository = FakeRepository()
    service = GraphRAGApplicationService(
        repository=repository,
        config=_config(),
    )
    return service, repository


def test_release_readiness_health_snapshot_freezes_public_config_shape() -> None:
    service, _repository = _service()

    snapshot = service.health_snapshot()

    assert snapshot["app_name"] == "pggraphrag-mcp"
    assert snapshot["app_version"] == "0.1.0"
    assert snapshot["embedding_provider"] == "openai"
    assert snapshot["embedding_model"] == "text-embedding-3-small"
    assert snapshot["max_vector_candidates"] == 3
    assert snapshot["max_graph_hops"] == 2
    assert snapshot["max_return_chunks"] == 4
    assert snapshot["max_return_entities"] == 5
    assert snapshot["graph_name"] == "pggraphrag_memory"


def test_naive_retrieval_enforces_max_return_chunks_limit() -> None:
    service, repository = _service()

    payload = service.retrieve_naive(
        RetrievalCommand(query="GraphRAG retrieval", top_k=99)
    )

    assert len(payload["supporting_chunks"]) == 3
    assert repository.calls[-1] == (
        "retrieve_naive",
        {"query": "GraphRAG retrieval", "top_k": 3},
    )


def test_local_graph_retrieval_enforces_chunk_and_entity_limits() -> None:
    service, repository = _service()

    payload = service.retrieve_local_graph(
        RetrievalCommand(
            query="GraphRAG local graph",
            top_k=10,
            graph_limit=99,
        )
    )

    assert len(payload["supporting_chunks"]) <= 3
    assert len(payload["entities"]) <= 5
    assert len(payload["relationships"]) <= 5
    assert repository.calls[-1] == (
        "retrieve_local_graph",
        {"query": "GraphRAG local graph", "top_k": 3, "graph_limit": 3},
    )


def test_hybrid_retrieval_enforces_limits_and_returns_traceable_shape() -> None:
    service, repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG hybrid retrieval",
            top_k=10,
            graph_limit=50,
        )
    )

    assert payload["mode"] == "hybrid"
    assert len(payload["supporting_chunks"]) <= 3
    assert len(payload["entities"]) <= 5
    assert len(payload["relationships"]) <= 5
    assert len(payload["sources"]) == 1
    assert payload["timings"]["elapsed_ms"] >= 0.0
    assert repository.calls[-1] == (
        "retrieve_hybrid",
        {"query": "GraphRAG hybrid retrieval", "top_k": 3, "graph_limit": 3},
    )


def test_entity_search_enforces_max_return_entities_limit() -> None:
    service, repository = _service()

    payload = service.entity_search(EntitySearchCommand(query="GraphRAG", limit=99))

    assert payload["limit"] == 5
    assert len(payload["results"]) == 1
    assert repository.calls[-1] == (
        "entity_search",
        {"query": "GraphRAG", "limit": 5},
    )


def test_entity_expand_enforces_graph_hops_and_entity_limit() -> None:
    service, repository = _service()

    payload = service.entity_expand(
        EntityExpandCommand(
            entity_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
            hops=99,
            limit=99,
        )
    )

    assert payload["hops"] == 2
    assert len(payload["entities"]) <= 5
    assert repository.calls[-1] == (
        "entity_expand",
        {
            "entity_id": uuid.UUID("99999999-9999-9999-9999-999999999999"),
            "hops": 2,
            "limit": 5,
        },
    )


def test_graph_refresh_rejects_conflicting_scope_inputs() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError,
        match="document_id and full_rebuild cannot be used together",
    ):
        service.graph_refresh(
            GraphRefreshCommand(
                document_id=uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111"),
                full_rebuild=True,
            )
        )


def test_graph_refresh_records_release_ready_projection_fields() -> None:
    service, repository = _service()

    payload = service.graph_refresh(
        GraphRefreshCommand(
            document_id=uuid.UUID("bbbbbbbb-1111-1111-1111-111111111111"),
            full_rebuild=False,
        )
    )

    assert payload["graph_name"] == "pggraphrag_memory"
    assert payload["document_scope"] == "bbbbbbbb-1111-1111-1111-111111111111"
    assert payload["projected_documents"] == 1
    assert payload["projected_chunks"] == 2
    assert payload["projected_entities"] == 3
    assert payload["projected_relations"] == 1
    assert payload["elapsed_ms"] >= 0.0
    assert repository.calls[0][0] == "connection"
    assert repository.calls[1][0] == "graph_refresh"


def test_source_trace_returns_release_ready_serializable_shape() -> None:
    service, repository = _service()

    payload = service.source_trace(
        SourceTraceCommand(
            retrieval_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        )
    )

    assert payload["retrieval_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert payload["mode"] == "hybrid"
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["chunk_id"] == "88888888-8888-8888-8888-888888888888"
    assert payload["timings"]["elapsed_ms"] >= 0.0
    assert repository.calls[-1] == (
        "source_trace",
        {"retrieval_id": uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")},
    )


def test_ingest_rejects_empty_text_with_predictable_validation_error() -> None:
    service, _repository = _service()

    with pytest.raises(GraphRAGValidationError, match="text must not be empty"):
        service.document_ingest(
            IngestDocumentCommand(
                tenant_id="tenant-a",
                source_uri="memory://docs/alpha",
                title="Alpha",
                text="   ",
            )
        )


def test_retrieval_rejects_non_positive_top_k() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="top_k must be greater than zero"
    ):
        service.retrieve_naive(RetrievalCommand(query="GraphRAG", top_k=0))


def test_entity_search_rejects_non_positive_limit() -> None:
    service, _repository = _service()

    with pytest.raises(
        GraphRAGValidationError, match="limit must be greater than zero"
    ):
        service.entity_search(EntitySearchCommand(query="GraphRAG", limit=0))


def test_entity_expand_rejects_non_positive_hops() -> None:
    service, _repository = _service()

    with pytest.raises(GraphRAGValidationError, match="hops must be greater than zero"):
        service.entity_expand(
            EntityExpandCommand(
                entity_id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                hops=0,
                limit=5,
            )
        )

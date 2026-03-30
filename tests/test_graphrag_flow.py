# ruff: noqa: E402
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

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
    GraphRefreshCommand,
    IngestDocumentCommand,
    RetrievalCommand,
    SourceTraceCommand,
)


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._last_hybrid_retrieval_id = uuid.UUID(
            "11111111-1111-1111-1111-111111111111"
        )
        self._last_document_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        self._last_entity_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
        self._last_relation_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        self._last_chunk_id = uuid.UUID("55555555-5555-5555-5555-555555555555")

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

        document = _obj(
            document_id=self._last_document_id,
            tenant_id=tenant_id,
            source_uri=source_uri,
            title=title,
            mime_type=mime_type,
            content_hash="abc123",
            status="completed",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:01+00:00",
        )
        chunk = _obj(
            chunk_id=self._last_chunk_id,
            document_id=self._last_document_id,
            chunk_no=0,
            text=text,
            token_count=4,
            metadata={"source": "fake"},
            created_at="2026-01-01T00:00:01+00:00",
        )
        entity = _obj(
            entity_id=self._last_entity_id,
            canonical_name="GraphRAG",
            entity_type="concept",
            aliases=["GraphRAG"],
            metadata={"origin": "fake"},
            created_at="2026-01-01T00:00:01+00:00",
        )
        relation = _obj(
            relation_fact_id=self._last_relation_id,
            source_entity_id=self._last_entity_id,
            target_entity_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
            relation_type="USES",
            weight=1.0,
            evidence_chunk_id=self._last_chunk_id,
            metadata={"origin": "fake"},
            created_at="2026-01-01T00:00:01+00:00",
        )

        return _obj(
            ingestion_job_id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
            document=document,
            chunks=[chunk],
            entities=[entity],
            relations=[relation],
            graph_refresh_summary={
                "graph_name": "pggraphrag_memory",
                "document_scope": str(self._last_document_id),
                "full_rebuild": False,
                "projected_documents": 1,
                "projected_chunks": 1,
                "projected_entities": 1,
                "projected_relations": 1,
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
        return document_id == self._last_document_id

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
                    "document_id": document_id,
                    "full_rebuild": full_rebuild,
                    "conn": conn,
                },
            )
        )
        return {
            "graph_name": "pggraphrag_memory",
            "document_scope": str(document_id) if document_id else "all",
            "full_rebuild": full_rebuild,
            "projected_documents": 1 if document_id else 2,
            "projected_chunks": 1 if document_id else 4,
            "projected_entities": 1 if document_id else 5,
            "projected_relations": 1 if document_id else 3,
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
            retrieval_id=uuid.UUID("88888888-8888-8888-8888-888888888888"),
            mode="naive",
            query=query,
            top_k=top_k,
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
            retrieval_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
            mode="local_graph",
            query=query,
            top_k=top_k,
            include_entities=True,
            include_relationships=True,
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
            retrieval_id=self._last_hybrid_retrieval_id,
            mode="hybrid",
            query=query,
            top_k=top_k,
            include_entities=True,
            include_relationships=True,
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
                    entity_id=self._last_entity_id,
                    canonical_name="GraphRAG",
                    entity_type="concept",
                    aliases=["GraphRAG"],
                    metadata={"origin": "fake"},
                    created_at="2026-01-01T00:00:00+00:00",
                ),
                evidence_chunks=[
                    _obj(
                        document_id=self._last_document_id,
                        chunk_id=self._last_chunk_id,
                        source_uri="memory://docs/graphrag",
                        title="GraphRAG Overview",
                        chunk_no=0,
                        snippet="GraphRAG combines retrieval and graph reasoning.",
                    )
                ],
                score=0.95,
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
            "entities": [
                {
                    "entity_id": str(entity_id),
                    "canonical_name": "GraphRAG",
                    "entity_type": "concept",
                    "aliases": ["GraphRAG"],
                },
                {
                    "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "canonical_name": "Source Trace",
                    "entity_type": "feature",
                    "aliases": ["Source Trace"],
                },
            ],
            "relationships": [
                {
                    "relation_fact_id": str(self._last_relation_id),
                    "source_entity_id": str(entity_id),
                    "source_entity_name": "GraphRAG",
                    "target_entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "target_entity_name": "Source Trace",
                    "relation_type": "USES",
                    "weight": 1.0,
                    "evidence_chunk_id": str(self._last_chunk_id),
                }
            ],
            "sources": [
                {
                    "document_id": str(self._last_document_id),
                    "chunk_id": str(self._last_chunk_id),
                    "source_uri": "memory://docs/graphrag",
                    "title": "GraphRAG Overview",
                    "chunk_no": 0,
                    "snippet": "GraphRAG uses Source Trace.",
                }
            ],
        }

    def source_trace(
        self,
        *,
        retrieval_id: uuid.UUID,
    ) -> dict[str, Any]:
        self.calls.append(("source_trace", {"retrieval_id": retrieval_id}))
        return {
            "retrieval_id": str(retrieval_id),
            "query_text": "how does graphrag work",
            "mode": "hybrid",
            "timings": {"strategy": "hybrid"},
            "created_at": "2026-01-01T00:00:02+00:00",
            "sources": [
                {
                    "document_id": str(self._last_document_id),
                    "chunk_id": str(self._last_chunk_id),
                    "source_uri": "memory://docs/graphrag",
                    "title": "GraphRAG Overview",
                    "chunk_no": 0,
                    "snippet": "GraphRAG combines retrieval and graph reasoning.",
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
    include_entities: bool = False,
    include_relationships: bool = False,
) -> Any:
    supporting_chunks = [
        _obj(
            chunk_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            document_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            chunk_no=0,
            text=f"Result for {query}",
            score=0.91,
            source_uri="memory://docs/graphrag",
            title="GraphRAG Overview",
        )
    ]

    entities = []
    if include_entities:
        entities.append(
            _obj(
                entity_id=uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
                canonical_name="GraphRAG",
                entity_type="concept",
                score=0.88,
                aliases=["GraphRAG"],
            )
        )

    relationships = []
    if include_relationships:
        relationships.append(
            _obj(
                relation_fact_id=uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
                source_entity_id=uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
                source_entity_name="GraphRAG",
                target_entity_id=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
                target_entity_name="Source Trace",
                relation_type="USES",
                weight=1.0,
                evidence_chunk_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            )
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
                "document_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "chunk_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "source_uri": "memory://docs/graphrag",
                "title": "GraphRAG Overview",
                "chunk_no": 0,
                "snippet": f"Result for {query}",
            }
        ],
        confidence=0.91,
        timings={"candidate_count": top_k},
    )


def _service() -> tuple[GraphRAGApplicationService, FakeRepository]:
    repository = FakeRepository()
    config = AppConfig(
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
        max_vector_candidates=30,
        max_graph_hops=2,
        max_return_chunks=12,
        max_return_entities=20,
        tls_cert_file="/certs/dev.crt",
        tls_key_file="/certs/dev.key",
        private_image="pggraphrag-mcp-private:local",
        auth_image="pggraphrag-mcp-auth:local",
        db_image="pggraphrag-db:local",
    )
    service = GraphRAGApplicationService(repository=repository, config=config)
    return service, repository


def test_document_ingest_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.document_ingest(
        IngestDocumentCommand(
            tenant_id="tenant-a",
            source_uri="memory://docs/graphrag",
            title="GraphRAG Overview",
            text="GraphRAG combines retrieval and graph reasoning.",
            mime_type="text/plain",
            metadata={"source": "test"},
        )
    )

    assert result["document"]["document_id"] == "22222222-2222-2222-2222-222222222222"
    assert result["document"]["source_uri"] == "memory://docs/graphrag"
    assert result["chunk_count"] == 1
    assert result["entity_count"] == 1
    assert result["relation_count"] == 1
    assert result["graph_refresh_summary"]["graph_name"] == "pggraphrag_memory"
    assert repository.calls[0][0] == "document_ingest"


def test_document_reingest_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.document_reingest(
        IngestDocumentCommand(
            tenant_id="tenant-a",
            source_uri="memory://docs/graphrag",
            title="GraphRAG Overview v2",
            text="GraphRAG now includes source trace and hybrid retrieval.",
            mime_type="text/plain",
            metadata={"source": "test"},
        )
    )

    assert result["document"]["title"] == "GraphRAG Overview v2"
    assert result["chunk_count"] == 1
    assert any(call[0] == "document_reingest" for call in repository.calls)


def test_document_delete_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.document_delete(document_id="22222222-2222-2222-2222-222222222222")

    assert result["document_id"] == "22222222-2222-2222-2222-222222222222"
    assert result["deleted"] is True
    assert repository.calls[-1][0] == "document_delete"


def test_graph_refresh_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.graph_refresh(
        GraphRefreshCommand(
            document_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            full_rebuild=False,
        )
    )

    assert result["graph_name"] == "pggraphrag_memory"
    assert result["document_scope"] == "22222222-2222-2222-2222-222222222222"
    assert result["projected_documents"] == 1
    assert any(call[0] == "connection" for call in repository.calls)
    assert any(call[0] == "graph_refresh" for call in repository.calls)


def test_retrieve_naive_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.retrieve_naive(
        RetrievalCommand(query="how does graphrag work", top_k=3)
    )

    assert result["mode"] == "naive"
    assert result["retrieval_id"] == "88888888-8888-8888-8888-888888888888"
    assert len(result["supporting_chunks"]) == 1
    assert result["supporting_chunks"][0]["source_uri"] == "memory://docs/graphrag"
    assert result["confidence"] == 0.91
    assert repository.calls[-1][0] == "retrieve_naive"


def test_entity_search_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.entity_search(EntitySearchCommand(query="GraphRAG", limit=5))

    assert result["query"] == "GraphRAG"
    assert result["limit"] == 5
    assert len(result["results"]) == 1
    assert result["results"][0]["entity"]["canonical_name"] == "GraphRAG"
    assert result["results"][0]["score"] == 0.95
    assert repository.calls[-1][0] == "entity_search"


def test_entity_expand_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.entity_expand(
        EntityExpandCommand(
            entity_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            hops=2,
            limit=10,
        )
    )

    assert result["root_entity"]["canonical_name"] == "GraphRAG"
    assert result["hops"] == 2
    assert len(result["entities"]) == 2
    assert len(result["relationships"]) == 1
    assert len(result["sources"]) == 1
    assert repository.calls[-1][0] == "entity_expand"


def test_retrieve_local_graph_uses_repository_backed_application_service() -> None:
    service, repository = _service()

    result = service.retrieve_local_graph(
        RetrievalCommand(query="graphrag source trace", top_k=4, graph_limit=7)
    )

    assert result["mode"] == "local_graph"
    assert len(result["supporting_chunks"]) == 1
    assert len(result["entities"]) == 1
    assert len(result["relationships"]) == 1
    assert result["confidence"] == 0.91
    assert repository.calls[-1][0] == "retrieve_local_graph"


def test_retrieve_hybrid_and_source_trace_use_repository_backed_application_service() -> (
    None
):
    service, repository = _service()

    hybrid = service.retrieve_hybrid(
        RetrievalCommand(query="graphrag hybrid retrieval", top_k=4, graph_limit=8)
    )
    trace = service.source_trace(
        SourceTraceCommand(
            retrieval_id=uuid.UUID("11111111-1111-1111-1111-111111111111")
        )
    )

    assert hybrid["mode"] == "hybrid"
    assert hybrid["retrieval_id"] == "11111111-1111-1111-1111-111111111111"
    assert len(hybrid["sources"]) == 1
    assert trace["retrieval_id"] == "11111111-1111-1111-1111-111111111111"
    assert trace["mode"] == "hybrid"
    assert len(trace["sources"]) == 1
    assert any(call[0] == "retrieve_hybrid" for call in repository.calls)
    assert any(call[0] == "source_trace" for call in repository.calls)

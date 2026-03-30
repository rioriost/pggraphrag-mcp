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
from pggraphrag_mcp.graphrag_service import GraphRAGApplicationService, RetrievalCommand


class FakeRetrievalQualityRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def retrieve_naive(
        self,
        *,
        query: str,
        top_k: int = 5,
    ) -> Any:
        self.calls.append(("retrieve_naive", {"query": query, "top_k": top_k}))
        return _result(
            retrieval_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            mode="naive",
            summary=f"naive summary for {query}",
            supporting_chunks=[
                {
                    "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_no": 0,
                    "text": "GraphRAG uses Source Trace for evidence navigation.",
                    "score": 0.91,
                    "source_uri": "memory://docs/naive/0",
                    "title": "Naive A",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.78,
                            "lexical_overlap": 0.95,
                            "entity_hit": 1.0,
                            "relation_hit": 0.0,
                            "final_score": 0.91,
                        }
                    },
                },
                {
                    "chunk_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                    "document_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                    "chunk_no": 1,
                    "text": "Graph reasoning improves retrieval quality.",
                    "score": 0.63,
                    "source_uri": "memory://docs/naive/1",
                    "title": "Naive B",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.69,
                            "lexical_overlap": 0.48,
                            "entity_hit": 0.3,
                            "relation_hit": 0.0,
                            "final_score": 0.63,
                        }
                    },
                },
            ],
            entities=[],
            relationships=[],
            sources=[
                {
                    "document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "source_uri": "memory://docs/naive/0",
                    "title": "Naive A",
                    "chunk_no": 0,
                    "snippet": "GraphRAG uses Source Trace for evidence navigation.",
                }
            ],
            confidence=0.91,
            timings={
                "strategy": "naive-rerank-v2",
                "candidate_count": top_k,
                "rerank_applied": True,
            },
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
        return _result(
            retrieval_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            mode="local_graph",
            summary=f"local graph summary for {query}",
            supporting_chunks=[
                {
                    "chunk_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                    "document_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "chunk_no": 0,
                    "text": "GraphRAG connects retrieval evidence to graph context.",
                    "score": 0.89,
                    "source_uri": "memory://docs/local/0",
                    "title": "Local A",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.76,
                            "lexical_overlap": 0.84,
                            "entity_hit": 0.95,
                            "relation_hit": 0.85,
                            "final_score": 0.89,
                        }
                    },
                }
            ],
            entities=[
                {
                    "entity_id": "12121212-1212-1212-1212-121212121212",
                    "canonical_name": "GraphRAG",
                    "entity_type": "concept",
                    "score": 0.88,
                    "aliases": ["GraphRAG"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.89,
                            "final_score": 0.88,
                        }
                    },
                }
            ],
            relationships=[
                {
                    "relation_fact_id": "13131313-1313-1313-1313-131313131313",
                    "source_entity_id": "12121212-1212-1212-1212-121212121212",
                    "source_entity_name": "GraphRAG",
                    "target_entity_id": "14141414-1414-1414-1414-141414141414",
                    "target_entity_name": "Source Trace",
                    "relation_type": "USES",
                    "weight": 1.0,
                    "evidence_chunk_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.89,
                            "final_score": 0.92,
                        }
                    },
                }
            ],
            sources=[
                {
                    "document_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "chunk_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                    "source_uri": "memory://docs/local/0",
                    "title": "Local A",
                    "chunk_no": 0,
                    "snippet": "GraphRAG connects retrieval evidence to graph context.",
                }
            ],
            confidence=0.89,
            timings={
                "strategy": "local-graph-rerank-v2",
                "candidate_count": top_k,
                "graph_limit": graph_limit,
                "rerank_applied": True,
            },
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
        return _result(
            retrieval_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            mode="hybrid",
            summary=f"hybrid summary for {query}",
            supporting_chunks=[
                {
                    "chunk_id": "15151515-1515-1515-1515-151515151515",
                    "document_id": "16161616-1616-1616-1616-161616161616",
                    "chunk_no": 0,
                    "text": "GraphRAG uses Source Trace and depends on Graph Memory.",
                    "score": 0.96,
                    "source_uri": "memory://docs/hybrid/0",
                    "title": "Hybrid A",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.79,
                            "lexical_overlap": 0.91,
                            "entity_hit": 1.0,
                            "relation_hit": 1.0,
                            "final_score": 0.96,
                        }
                    },
                },
                {
                    "chunk_id": "17171717-1717-1717-1717-171717171717",
                    "document_id": "18181818-1818-1818-1818-181818181818",
                    "chunk_no": 1,
                    "text": "Graph Memory stores projection state for later use.",
                    "score": 0.74,
                    "source_uri": "memory://docs/hybrid/1",
                    "title": "Hybrid B",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.72,
                            "lexical_overlap": 0.56,
                            "entity_hit": 0.6,
                            "relation_hit": 0.4,
                            "final_score": 0.74,
                        }
                    },
                },
                {
                    "chunk_id": "19191919-1919-1919-1919-191919191919",
                    "document_id": "20202020-2020-2020-2020-202020202020",
                    "chunk_no": 2,
                    "text": "Source Trace is useful, but no graph relation is evidenced here.",
                    "score": 0.68,
                    "source_uri": "memory://docs/hybrid/2",
                    "title": "Hybrid C",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.70,
                            "lexical_overlap": 0.61,
                            "entity_hit": 0.8,
                            "relation_hit": 0.1,
                            "final_score": 0.68,
                        }
                    },
                },
            ],
            entities=[
                {
                    "entity_id": "21212121-2121-2121-2121-212121212121",
                    "canonical_name": "GraphRAG",
                    "entity_type": "concept",
                    "score": 0.95,
                    "aliases": ["GraphRAG"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.96,
                            "final_score": 0.95,
                        }
                    },
                },
                {
                    "entity_id": "22222222-2222-2222-2222-222222222222",
                    "canonical_name": "Source Trace",
                    "entity_type": "concept",
                    "score": 0.92,
                    "aliases": ["Source Trace"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.96,
                            "final_score": 0.92,
                        }
                    },
                },
                {
                    "entity_id": "23232323-2323-2323-2323-232323232323",
                    "canonical_name": "Graph Memory",
                    "entity_type": "concept",
                    "score": 0.90,
                    "aliases": ["Graph Memory"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 0.95,
                            "supporting_chunk_score": 0.96,
                            "final_score": 0.90,
                        }
                    },
                },
            ],
            relationships=[
                {
                    "relation_fact_id": "24242424-2424-2424-2424-242424242424",
                    "source_entity_id": "21212121-2121-2121-2121-212121212121",
                    "source_entity_name": "GraphRAG",
                    "target_entity_id": "22222222-2222-2222-2222-222222222222",
                    "target_entity_name": "Source Trace",
                    "relation_type": "USES",
                    "weight": 1.0,
                    "evidence_chunk_id": "15151515-1515-1515-1515-151515151515",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.96,
                            "final_score": 0.95,
                        }
                    },
                },
                {
                    "relation_fact_id": "25252525-2525-2525-2525-252525252525",
                    "source_entity_id": "22222222-2222-2222-2222-222222222222",
                    "source_entity_name": "Source Trace",
                    "target_entity_id": "23232323-2323-2323-2323-232323232323",
                    "target_entity_name": "Graph Memory",
                    "relation_type": "DEPENDS_ON",
                    "weight": 1.0,
                    "evidence_chunk_id": "15151515-1515-1515-1515-151515151515",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.96,
                            "final_score": 0.94,
                        }
                    },
                },
            ],
            sources=[
                {
                    "document_id": "16161616-1616-1616-1616-161616161616",
                    "chunk_id": "15151515-1515-1515-1515-151515151515",
                    "source_uri": "memory://docs/hybrid/0",
                    "title": "Hybrid A",
                    "chunk_no": 0,
                    "snippet": "GraphRAG uses Source Trace and depends on Graph Memory.",
                },
                {
                    "document_id": "18181818-1818-1818-1818-181818181818",
                    "chunk_id": "17171717-1717-1717-1717-171717171717",
                    "source_uri": "memory://docs/hybrid/1",
                    "title": "Hybrid B",
                    "chunk_no": 1,
                    "snippet": "Graph Memory stores projection state for later use.",
                },
            ],
            confidence=0.96,
            timings={
                "strategy": "hybrid-rerank-v2",
                "candidate_count": top_k,
                "graph_limit": graph_limit,
                "rerank_applied": True,
            },
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
            ("entity_expand", {"entity_id": entity_id, "hops": hops, "limit": limit})
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


def _obj(**kwargs: Any) -> Any:
    class Obj:
        pass

    instance = Obj()
    for key, value in kwargs.items():
        setattr(instance, key, value)
    return instance


def _result(
    *,
    retrieval_id: uuid.UUID,
    mode: str,
    summary: str,
    supporting_chunks: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    confidence: float,
    timings: dict[str, Any],
) -> Any:
    return _obj(
        retrieval_id=retrieval_id,
        summary=summary,
        mode=mode,
        supporting_chunks=supporting_chunks,
        entities=entities,
        relationships=relationships,
        sources=sources,
        confidence=confidence,
        timings=timings,
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
        max_vector_candidates=10,
        max_graph_hops=2,
        max_return_chunks=6,
        max_return_entities=6,
        tls_cert_file="/certs/dev.crt",
        tls_key_file="/certs/dev.key",
        private_image="pggraphrag-mcp-private:local",
        auth_image="pggraphrag-mcp-auth:local",
        db_image="pggraphrag-db:local",
    )


def _service() -> tuple[GraphRAGApplicationService, FakeRetrievalQualityRepository]:
    repository = FakeRetrievalQualityRepository()
    service = GraphRAGApplicationService(repository=repository, config=_config())
    return service, repository


def test_naive_retrieval_preserves_top_ranked_chunk_order() -> None:
    service, repository = _service()

    payload = service.retrieve_naive(
        RetrievalCommand(query="GraphRAG source trace", top_k=5)
    )

    assert payload["mode"] == "naive"
    assert payload["retrieval_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["supporting_chunks"][0]["title"] == "Naive A"
    assert (
        payload["supporting_chunks"][0]["score"]
        > payload["supporting_chunks"][1]["score"]
    )
    assert repository.calls[-1] == (
        "retrieve_naive",
        {"query": "GraphRAG source trace", "top_k": 5},
    )


def test_naive_retrieval_returns_score_breakdown_metadata() -> None:
    service, _repository = _service()

    payload = service.retrieve_naive(
        RetrievalCommand(query="GraphRAG source trace", top_k=5)
    )

    first_chunk = payload["supporting_chunks"][0]
    breakdown = first_chunk["metadata"]["score_breakdown"]

    assert breakdown["embedding_similarity"] == 0.78
    assert breakdown["lexical_overlap"] == 0.95
    assert breakdown["entity_hit"] == 1.0
    assert breakdown["relation_hit"] == 0.0
    assert breakdown["final_score"] == 0.91


def test_naive_retrieval_reports_limits_applied() -> None:
    service, _repository = _service()

    payload = service.retrieve_naive(
        RetrievalCommand(query="GraphRAG source trace", top_k=50)
    )

    limits = payload["limits_applied"]
    assert limits["requested_supporting_chunks"] == 2
    assert limits["returned_supporting_chunks"] == 2
    assert limits["max_return_chunks"] == 6
    assert limits["requested_entities"] == 0
    assert limits["returned_entities"] == 0


def test_hybrid_retrieval_exposes_relation_backed_score_breakdown() -> None:
    service, repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG depends on Graph Memory", top_k=5, graph_limit=5
        )
    )

    assert payload["mode"] == "hybrid"
    assert payload["retrieval_id"] == "33333333-3333-3333-3333-333333333333"
    assert payload["supporting_chunks"][0]["title"] == "Hybrid A"
    assert payload["entities"][0]["canonical_name"] == "GraphRAG"
    assert payload["relationships"][0]["relation_type"] == "USES"
    assert repository.calls[-1] == (
        "retrieve_hybrid",
        {"query": "GraphRAG depends on Graph Memory", "top_k": 5, "graph_limit": 5},
    )

    relationship_breakdown = payload["relationships"][0]["metadata"]["score_breakdown"]
    assert relationship_breakdown["relation_hit"] == 1.0
    assert relationship_breakdown["supporting_chunk_score"] == 0.96
    assert relationship_breakdown["final_score"] == 0.95


def test_hybrid_retrieval_limits_applied_cover_entities_relationships_and_sources() -> (
    None
):
    service, _repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG depends on Graph Memory", top_k=5, graph_limit=5
        )
    )

    limits = payload["limits_applied"]
    assert limits["requested_supporting_chunks"] == 3
    assert limits["returned_supporting_chunks"] == 3
    assert limits["requested_entities"] == 3
    assert limits["returned_entities"] == 3
    assert limits["requested_relationships"] == 2
    assert limits["returned_relationships"] == 2
    assert limits["requested_sources"] == 2
    assert limits["returned_sources"] == 2


def test_hybrid_retrieval_timing_reports_operation_and_elapsed_fields() -> None:
    service, _repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG depends on Graph Memory", top_k=5, graph_limit=5
        )
    )

    timings = payload["timings"]
    assert timings["strategy"] == "hybrid-rerank-v2"
    assert timings["operation"] == "retrieval"
    assert timings["elapsed_ms"] >= 0.0
    assert timings["elapsed_seconds"] >= 0.0
    assert "finished_at" in timings


def test_hybrid_retrieval_prefers_relation_supported_chunk_over_weaker_candidate() -> (
    None
):
    service, _repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG depends on Graph Memory", top_k=5, graph_limit=5
        )
    )

    first = payload["supporting_chunks"][0]
    second = payload["supporting_chunks"][1]

    assert first["title"] == "Hybrid A"
    assert second["title"] == "Hybrid B"
    assert first["score"] > second["score"]

    first_breakdown = first["metadata"]["score_breakdown"]
    second_breakdown = second["metadata"]["score_breakdown"]
    assert first_breakdown["relation_hit"] > second_breakdown["relation_hit"]
    assert first_breakdown["final_score"] > second_breakdown["final_score"]

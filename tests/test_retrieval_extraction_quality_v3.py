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
from pggraphrag_mcp.repository import (
    GraphRagRepository,
    coverage_overlap_score,
    rerank_chunk_candidates,
)


class FakeRetrievalExtractionRepository:
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
            retrieval_id=uuid.UUID("31111111-1111-1111-1111-111111111111"),
            mode="naive",
            summary=f"naive summary for {query}",
            supporting_chunks=[
                {
                    "chunk_id": "31111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "document_id": "31111111-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_no": 0,
                    "text": "GraphRAG uses Source Trace for evidence navigation and Graph Memory persistence.",
                    "score": 0.94,
                    "source_uri": "memory://docs/naive/0",
                    "title": "Naive Strong",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.80,
                            "lexical_overlap": 0.88,
                            "coverage_overlap": 1.0,
                            "entity_hit": 1.0,
                            "exact_entity_match": 0.0,
                            "relation_hit": 0.0,
                            "final_score": 0.94,
                        }
                    },
                },
                {
                    "chunk_id": "31111111-cccc-cccc-cccc-cccccccccccc",
                    "document_id": "31111111-dddd-dddd-dddd-dddddddddddd",
                    "chunk_no": 1,
                    "text": "Source Trace appears here, but the graph memory dependency is not supported.",
                    "score": 0.66,
                    "source_uri": "memory://docs/naive/1",
                    "title": "Naive Weak",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.69,
                            "lexical_overlap": 0.51,
                            "coverage_overlap": 0.5,
                            "entity_hit": 1.0,
                            "exact_entity_match": 0.0,
                            "relation_hit": 0.0,
                            "final_score": 0.66,
                        }
                    },
                },
            ],
            entities=[],
            relationships=[],
            sources=[
                {
                    "document_id": "31111111-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_id": "31111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "source_uri": "memory://docs/naive/0",
                    "title": "Naive Strong",
                    "chunk_no": 0,
                    "snippet": "GraphRAG uses Source Trace for evidence navigation and Graph Memory persistence.",
                }
            ],
            confidence=0.94,
            timings={
                "strategy": "naive-rerank-v3",
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
            retrieval_id=uuid.UUID("32222222-2222-2222-2222-222222222222"),
            mode="local_graph",
            summary=f"local graph summary for {query}",
            supporting_chunks=[
                {
                    "chunk_id": "32222222-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "document_id": "32222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_no": 0,
                    "text": "GraphRAG uses Source Trace while Source Trace depends on Graph Memory.",
                    "score": 0.93,
                    "source_uri": "memory://docs/local/0",
                    "title": "Local Strong",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.79,
                            "lexical_overlap": 0.85,
                            "coverage_overlap": 1.0,
                            "entity_hit": 1.0,
                            "exact_entity_match": 0.0,
                            "relation_hit": 1.0,
                            "final_score": 0.93,
                        }
                    },
                }
            ],
            entities=[
                {
                    "entity_id": "32222222-1111-1111-1111-111111111111",
                    "canonical_name": "GraphRAG",
                    "entity_type": "concept",
                    "score": 0.93,
                    "aliases": ["GraphRAG"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.93,
                            "final_score": 0.93,
                        }
                    },
                },
                {
                    "entity_id": "32222222-2222-2222-2222-222222222222",
                    "canonical_name": "Source Trace",
                    "entity_type": "concept",
                    "score": 0.91,
                    "aliases": ["Source Trace", "SourceTrace"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.93,
                            "final_score": 0.91,
                        }
                    },
                },
                {
                    "entity_id": "32222222-3333-3333-3333-333333333333",
                    "canonical_name": "Graph Memory",
                    "entity_type": "concept",
                    "score": 0.89,
                    "aliases": ["Graph Memory", "GraphMemory"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.93,
                            "final_score": 0.89,
                        }
                    },
                },
            ],
            relationships=[
                {
                    "relation_fact_id": "32222222-4444-4444-4444-444444444444",
                    "source_entity_id": "32222222-1111-1111-1111-111111111111",
                    "source_entity_name": "GraphRAG",
                    "target_entity_id": "32222222-2222-2222-2222-222222222222",
                    "target_entity_name": "Source Trace",
                    "relation_type": "USES",
                    "weight": 1.0,
                    "evidence_chunk_id": "32222222-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.93,
                            "final_score": 0.94,
                        }
                    },
                },
                {
                    "relation_fact_id": "32222222-5555-5555-5555-555555555555",
                    "source_entity_id": "32222222-2222-2222-2222-222222222222",
                    "source_entity_name": "Source Trace",
                    "target_entity_id": "32222222-3333-3333-3333-333333333333",
                    "target_entity_name": "Graph Memory",
                    "relation_type": "DEPENDS_ON",
                    "weight": 1.0,
                    "evidence_chunk_id": "32222222-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.93,
                            "final_score": 0.92,
                        }
                    },
                },
            ],
            sources=[
                {
                    "document_id": "32222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_id": "32222222-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "source_uri": "memory://docs/local/0",
                    "title": "Local Strong",
                    "chunk_no": 0,
                    "snippet": "GraphRAG uses Source Trace while Source Trace depends on Graph Memory.",
                }
            ],
            confidence=0.93,
            timings={
                "strategy": "local-graph-rerank-v3",
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
                    "chunk_id": "33333333-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "document_id": "33333333-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_no": 0,
                    "text": "GraphRAG uses Source Trace and Source Trace depends on Graph Memory.",
                    "score": 0.97,
                    "source_uri": "memory://docs/hybrid/0",
                    "title": "Hybrid Best",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.82,
                            "lexical_overlap": 0.92,
                            "coverage_overlap": 1.0,
                            "entity_hit": 1.0,
                            "exact_entity_match": 0.0,
                            "relation_hit": 1.0,
                            "final_score": 0.97,
                        }
                    },
                },
                {
                    "chunk_id": "33333333-cccc-cccc-cccc-cccccccccccc",
                    "document_id": "33333333-dddd-dddd-dddd-dddddddddddd",
                    "chunk_no": 1,
                    "text": "Graph Memory stores projection state for later retrieval use.",
                    "score": 0.76,
                    "source_uri": "memory://docs/hybrid/1",
                    "title": "Hybrid Secondary",
                    "metadata": {
                        "score_breakdown": {
                            "embedding_similarity": 0.73,
                            "lexical_overlap": 0.58,
                            "coverage_overlap": 0.4,
                            "entity_hit": 0.5,
                            "exact_entity_match": 0.0,
                            "relation_hit": 0.2,
                            "final_score": 0.76,
                        }
                    },
                },
            ],
            entities=[
                {
                    "entity_id": "33333333-1111-1111-1111-111111111111",
                    "canonical_name": "GraphRAG",
                    "entity_type": "concept",
                    "score": 0.95,
                    "aliases": ["GraphRAG"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.97,
                            "final_score": 0.95,
                        }
                    },
                },
                {
                    "entity_id": "33333333-2222-2222-2222-222222222222",
                    "canonical_name": "Source Trace",
                    "entity_type": "concept",
                    "score": 0.93,
                    "aliases": ["Source Trace", "SourceTrace"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 1.0,
                            "supporting_chunk_score": 0.97,
                            "final_score": 0.93,
                        }
                    },
                },
                {
                    "entity_id": "33333333-3333-3333-3333-333333333333",
                    "canonical_name": "Graph Memory",
                    "entity_type": "concept",
                    "score": 0.90,
                    "aliases": ["Graph Memory", "GraphMemory"],
                    "metadata": {
                        "score_breakdown": {
                            "entity_hit": 0.95,
                            "supporting_chunk_score": 0.97,
                            "final_score": 0.90,
                        }
                    },
                },
            ],
            relationships=[
                {
                    "relation_fact_id": "33333333-4444-4444-4444-444444444444",
                    "source_entity_id": "33333333-1111-1111-1111-111111111111",
                    "source_entity_name": "GraphRAG",
                    "target_entity_id": "33333333-2222-2222-2222-222222222222",
                    "target_entity_name": "Source Trace",
                    "relation_type": "USES",
                    "weight": 1.0,
                    "evidence_chunk_id": "33333333-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.97,
                            "final_score": 0.95,
                        }
                    },
                },
                {
                    "relation_fact_id": "33333333-5555-5555-5555-555555555555",
                    "source_entity_id": "33333333-2222-2222-2222-222222222222",
                    "source_entity_name": "Source Trace",
                    "target_entity_id": "33333333-3333-3333-3333-333333333333",
                    "target_entity_name": "Graph Memory",
                    "relation_type": "DEPENDS_ON",
                    "weight": 1.0,
                    "evidence_chunk_id": "33333333-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "metadata": {
                        "score_breakdown": {
                            "relation_hit": 1.0,
                            "supporting_chunk_score": 0.97,
                            "final_score": 0.94,
                        }
                    },
                },
            ],
            sources=[
                {
                    "document_id": "33333333-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "chunk_id": "33333333-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "source_uri": "memory://docs/hybrid/0",
                    "title": "Hybrid Best",
                    "chunk_no": 0,
                    "snippet": "GraphRAG uses Source Trace and Source Trace depends on Graph Memory.",
                },
                {
                    "document_id": "33333333-dddd-dddd-dddd-dddddddddddd",
                    "chunk_id": "33333333-cccc-cccc-cccc-cccccccccccc",
                    "source_uri": "memory://docs/hybrid/1",
                    "title": "Hybrid Secondary",
                    "chunk_no": 1,
                    "snippet": "Graph Memory stores projection state for later retrieval use.",
                },
            ],
            confidence=0.97,
            timings={
                "strategy": "hybrid-rerank-v3",
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
            "timings": {"strategy": "hybrid-rerank-v3"},
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


def _service() -> tuple[GraphRAGApplicationService, FakeRetrievalExtractionRepository]:
    repository = FakeRetrievalExtractionRepository()
    service = GraphRAGApplicationService(repository=repository, config=_config())
    return service, repository


def _repository() -> GraphRagRepository:
    return GraphRagRepository(
        "postgresql://user:pass@localhost:5432/db",
        age_graph_name="pggraphrag_memory",
        embedding_dimensions=16,
        embedding_provider_name="deterministic",
        embedding_model_name="deterministic-placeholder-v1",
        max_return_chunks=8,
        max_return_entities=10,
        max_graph_hops=2,
        app_name="pggraphrag-mcp-test",
    )


def test_coverage_overlap_rewards_broader_query_term_support() -> None:
    query = "GraphRAG depends on Graph Memory"
    strong = "GraphRAG depends on Graph Memory through a stable relation."
    weak = "Graph Memory is mentioned, but dependency evidence is absent."

    assert coverage_overlap_score(query, strong) > coverage_overlap_score(query, weak)
    assert coverage_overlap_score(query, strong) == 1.0


def test_rerank_chunk_candidates_prefers_better_query_coverage() -> None:
    ranked = rerank_chunk_candidates(
        query="GraphRAG depends on Graph Memory",
        candidates=[
            {
                "chunk_id": uuid.UUID("41111111-1111-1111-1111-111111111111"),
                "document_id": uuid.UUID("41111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                "chunk_no": 0,
                "text": "GraphRAG depends on Graph Memory for projection state.",
                "embedding_score": 0.70,
                "score": 0.70,
                "metadata": {},
                "source_uri": "memory://docs/rank/0",
                "title": "Coverage Strong",
            },
            {
                "chunk_id": uuid.UUID("42222222-2222-2222-2222-222222222222"),
                "document_id": uuid.UUID("42222222-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                "chunk_no": 1,
                "text": "Graph Memory stores state for later use.",
                "embedding_score": 0.72,
                "score": 0.72,
                "metadata": {},
                "source_uri": "memory://docs/rank/1",
                "title": "Coverage Weak",
            },
        ],
        entity_names_by_chunk_id={},
        relation_count_by_chunk_id={},
        profile="naive",
    )

    assert ranked[0]["title"] == "Coverage Strong"
    assert (
        ranked[0]["score_breakdown"]["coverage_overlap"]
        > ranked[1]["score_breakdown"]["coverage_overlap"]
    )
    assert (
        ranked[0]["score_breakdown"]["final_score"]
        > ranked[1]["score_breakdown"]["final_score"]
    )


def test_rerank_chunk_candidates_rewards_exact_entity_match() -> None:
    exact_chunk_id = uuid.UUID("43333333-3333-3333-3333-333333333333")
    partial_chunk_id = uuid.UUID("44444444-4444-4444-4444-444444444444")

    ranked = rerank_chunk_candidates(
        query="Source Trace",
        candidates=[
            {
                "chunk_id": exact_chunk_id,
                "document_id": uuid.UUID("43333333-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                "chunk_no": 0,
                "text": "Source Trace provides evidence navigation.",
                "embedding_score": 0.60,
                "score": 0.60,
                "metadata": {},
                "source_uri": "memory://docs/exact/0",
                "title": "Exact Match",
            },
            {
                "chunk_id": partial_chunk_id,
                "document_id": uuid.UUID("44444444-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                "chunk_no": 1,
                "text": "Trace navigation exists in the source system.",
                "embedding_score": 0.60,
                "score": 0.60,
                "metadata": {},
                "source_uri": "memory://docs/exact/1",
                "title": "Partial Match",
            },
        ],
        entity_names_by_chunk_id={
            exact_chunk_id: ["Source Trace"],
            partial_chunk_id: ["Trace Navigation"],
        },
        relation_count_by_chunk_id={},
        profile="hybrid",
    )

    assert ranked[0]["title"] == "Exact Match"
    assert ranked[0]["score_breakdown"]["exact_entity_match"] == 1.0
    assert ranked[1]["score_breakdown"]["exact_entity_match"] == 0.0


def test_candidate_entities_split_compact_camel_case_names_into_aliasable_tokens() -> (
    None
):
    repository = _repository()

    entities = repository._extract_candidate_entities(
        "GraphRagService writes evidence into SourceTraceBuffer."
    )

    by_name = {item["canonical_name"]: item for item in entities}

    assert "GraphRagService" in by_name
    assert "SourceTraceBuffer" in by_name

    assert by_name["GraphRagService"]["aliases"] == []
    assert by_name["SourceTraceBuffer"]["aliases"] == []


def test_candidate_entities_prefer_longer_phrase_over_shorter_overlap() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        "Graph Memory Store is refreshed. Graph Memory Store remains canonical here."
    )

    names = [item["canonical_name"] for item in entities]

    assert "Graph Memory Store" in names
    assert "Graph Memory" not in names


def test_candidate_entities_trim_added_generic_boundaries_after_normalization() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        "The Platform GraphRagService Engine publishes to The SourceTrace Layer."
    )

    names = [item["canonical_name"] for item in entities]

    assert "GraphRagService Engine" in names
    assert "SourceTrace Layer" in names
    assert "Platform GraphRagService Engine" not in names
    assert "The SourceTrace Layer" not in names


def test_candidate_relations_remain_sentence_local_after_entity_normalization() -> None:
    repository = _repository()

    source_trace = type(
        "Entity",
        (),
        {
            "entity_id": uuid.UUID("45555555-5555-5555-5555-555555555555"),
            "canonical_name": "Source Trace",
        },
    )()
    graph_memory = type(
        "Entity",
        (),
        {
            "entity_id": uuid.UUID("46666666-6666-6666-6666-666666666666"),
            "canonical_name": "Graph Memory",
        },
    )()

    relations = repository._extract_candidate_relations(
        "SourceTrace depends on GraphMemory. Separate sentence only mentions buffering.",
        entity_records_by_id={
            source_trace.entity_id: source_trace,
            graph_memory.entity_id: graph_memory,
        },
    )

    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_entity_id"] == source_trace.entity_id
    assert relation["target_entity_id"] == graph_memory.entity_id
    assert relation["relation_type"] == "DEPENDS_ON"


def test_candidate_relations_drop_far_pairs_even_with_normalized_entities() -> None:
    repository = _repository()

    source_trace = type(
        "Entity",
        (),
        {
            "entity_id": uuid.UUID("47777777-7777-7777-7777-777777777777"),
            "canonical_name": "Source Trace",
        },
    )()
    graph_memory = type(
        "Entity",
        (),
        {
            "entity_id": uuid.UUID("48888888-8888-8888-8888-888888888888"),
            "canonical_name": "Graph Memory",
        },
    )()

    text = (
        "SourceTrace depends on many intermediate orchestration components and "
        "several unrelated buffering layers before GraphMemory is finally named."
    )

    relations = repository._extract_candidate_relations(
        text,
        entity_records_by_id={
            source_trace.entity_id: source_trace,
            graph_memory.entity_id: graph_memory,
        },
    )

    assert relations == []


def test_naive_retrieval_payload_exposes_coverage_overlap_metadata() -> None:
    service, repository = _service()

    payload = service.retrieve_naive(
        RetrievalCommand(query="GraphRAG Source Trace Graph Memory", top_k=5)
    )

    assert payload["mode"] == "naive"
    assert payload["supporting_chunks"][0]["title"] == "Naive Strong"
    breakdown = payload["supporting_chunks"][0]["metadata"]["score_breakdown"]
    assert breakdown["coverage_overlap"] == 1.0
    assert repository.calls[-1] == (
        "retrieve_naive",
        {"query": "GraphRAG Source Trace Graph Memory", "top_k": 5},
    )


def test_hybrid_retrieval_payload_preserves_relation_backed_top_rank() -> None:
    service, repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG depends on Graph Memory",
            top_k=5,
            graph_limit=5,
        )
    )

    assert payload["mode"] == "hybrid"
    assert payload["supporting_chunks"][0]["title"] == "Hybrid Best"
    assert payload["relationships"][0]["relation_type"] == "USES"
    assert payload["relationships"][1]["relation_type"] == "DEPENDS_ON"
    assert repository.calls[-1] == (
        "retrieve_hybrid",
        {"query": "GraphRAG depends on Graph Memory", "top_k": 5, "graph_limit": 5},
    )


def test_hybrid_retrieval_limits_and_rank_order_favor_relation_supported_chunk() -> (
    None
):
    service, _repository = _service()

    payload = service.retrieve_hybrid(
        RetrievalCommand(
            query="GraphRAG depends on Graph Memory",
            top_k=5,
            graph_limit=5,
        )
    )

    first = payload["supporting_chunks"][0]
    second = payload["supporting_chunks"][1]

    assert first["title"] == "Hybrid Best"
    assert second["title"] == "Hybrid Secondary"
    assert first["score"] > second["score"]

    limits = payload["limits_applied"]
    assert limits["requested_supporting_chunks"] == 2
    assert limits["returned_supporting_chunks"] == 2
    assert limits["requested_entities"] == 3
    assert limits["returned_entities"] == 3
    assert limits["requested_relationships"] == 2
    assert limits["returned_relationships"] == 2


def test_local_graph_retrieval_retains_extraction_backed_entities_and_relations() -> (
    None
):
    service, repository = _service()

    payload = service.retrieve_local_graph(
        RetrievalCommand(
            query="GraphRAG uses Source Trace",
            top_k=5,
            graph_limit=5,
        )
    )

    assert payload["mode"] == "local_graph"
    assert [item["canonical_name"] for item in payload["entities"]] == [
        "GraphRAG",
        "Source Trace",
        "Graph Memory",
    ]
    assert [item["relation_type"] for item in payload["relationships"]] == [
        "USES",
        "DEPENDS_ON",
    ]
    assert repository.calls[-1] == (
        "retrieve_local_graph",
        {"query": "GraphRAG uses Source Trace", "top_k": 5, "graph_limit": 5},
    )

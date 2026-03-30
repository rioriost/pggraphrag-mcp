from __future__ import annotations

import uuid

import pytest

from pggraphrag_mcp.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    OpenAILocalEmbeddingProvider,
    create_embedding_provider,
    normalize_embedding_input,
)
from pggraphrag_mcp.repository import GraphRagRepository, chunk_text


def _repository() -> GraphRagRepository:
    return GraphRagRepository(
        "postgresql://user:pass@localhost:5432/db",
        age_graph_name="pggraphrag_memory",
        embedding_dimensions=16,
        max_return_chunks=8,
        max_return_entities=10,
        max_graph_hops=2,
        app_name="pggraphrag-mcp-test",
    )


def test_normalize_embedding_input_collapses_whitespace() -> None:
    assert normalize_embedding_input("  Alpha   Beta\nGamma  ") == "Alpha Beta Gamma"


def test_normalize_embedding_input_rejects_empty_text() -> None:
    with pytest.raises(EmbeddingProviderError, match="must not be empty"):
        normalize_embedding_input("   \n\t  ")


def test_deterministic_embedding_provider_returns_stable_vector() -> None:
    provider = DeterministicEmbeddingProvider(
        provider_name="deterministic",
        model_name="deterministic-placeholder-v1",
        dimensions=8,
    )

    first = provider.embed_text("GraphRAG retrieval")
    second = provider.embed_text("GraphRAG retrieval")

    assert first.provider == "deterministic"
    assert first.model == "deterministic-placeholder-v1"
    assert first.dimensions == 8
    assert first.values == second.values
    assert len(first.values) == 8


def test_deterministic_embedding_provider_normalizes_vector_length() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=12)

    vector = provider.embed_text("Alpha Beta Gamma").values
    magnitude = sum(value * value for value in vector) ** 0.5

    assert len(vector) == 12
    assert magnitude == pytest.approx(1.0, rel=1e-6)


def test_openai_local_embedding_provider_uses_openai_metadata() -> None:
    provider = OpenAILocalEmbeddingProvider(
        model_name="text-embedding-3-small",
        dimensions=16,
    )

    vector = provider.embed_text("Source trace for GraphRAG")

    assert vector.provider == "openai"
    assert vector.model == "text-embedding-3-small"
    assert vector.dimensions == 16
    assert len(vector.values) == 16


def test_create_embedding_provider_supports_openai_and_deterministic() -> None:
    deterministic = create_embedding_provider(
        provider_name="deterministic",
        model_name="deterministic-placeholder-v1",
        dimensions=8,
    )
    openai = create_embedding_provider(
        provider_name="openai",
        model_name="text-embedding-3-small",
        dimensions=8,
    )

    assert deterministic.provider_name == "deterministic"
    assert openai.provider_name == "openai"


def test_create_embedding_provider_rejects_unknown_provider() -> None:
    with pytest.raises(
        EmbeddingConfigurationError, match="Unsupported embedding provider"
    ):
        create_embedding_provider(
            provider_name="unknown-provider",
            model_name="whatever",
            dimensions=8,
        )


def test_chunk_text_splits_long_input_with_overlap() -> None:
    text = (
        "Alpha Platform uses Beta Engine. "
        "Beta Engine depends on Gamma Store. "
        "Gamma Store contains Delta Cache. "
        "Delta Cache supports Epsilon API. "
        "Epsilon API serves Zeta Worker."
    )

    chunks = chunk_text(
        text,
        max_chunk_chars=70,
        overlap_chars=20,
    )

    assert len(chunks) >= 2
    assert any("Alpha Platform" in chunk for chunk in chunks)
    assert any("Epsilon API" in chunk for chunk in chunks)


def test_extract_candidate_entities_prefers_title_case_phrases() -> None:
    repository = _repository()
    text = (
        "GraphRAG retrieval uses Source Trace. "
        "Source Trace depends on Graph Memory. "
        "Evidence Bundle supports Source Trace."
    )

    entities = repository._extract_candidate_entities(text)
    names = [item["canonical_name"] for item in entities]

    assert "Source Trace" in names
    assert "Graph Memory" in names
    assert "Evidence Bundle" in names


def test_extract_candidate_entities_deduplicates_results() -> None:
    repository = _repository()
    text = (
        "Graph Memory depends on Source Trace. "
        "Graph Memory stores projection state. "
        "Source Trace reads Graph Memory."
    )

    entities = repository._extract_candidate_entities(text)
    names = [item["canonical_name"] for item in entities]

    assert names.count("Graph Memory") == 1
    assert names.count("Source Trace") == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Alpha depends on Beta", "DEPENDS_ON"),
        ("Alpha uses Beta", "USES"),
        ("Alpha contains Beta", "CONTAINS"),
        ("Alpha includes Beta", "CONTAINS"),
        ("Alpha relates to Beta", "RELATES_TO"),
        ("Alpha and Beta appear together", "CO_OCCURS_WITH"),
    ],
)
def test_infer_relation_type_handles_multiple_patterns(
    text: str,
    expected: str,
) -> None:
    repository = _repository()

    assert repository._infer_relation_type(text) == expected


def test_entity_type_inference_classifies_known_suffixes() -> None:
    repository = _repository()

    assert repository._infer_entity_type("Acme Inc") == "organization"
    assert repository._infer_entity_type("Platform Team") == "organization"
    assert repository._infer_entity_type("Graph Platform") == "system"
    assert repository._infer_entity_type("Source Trace") == "concept"


def test_execute_cypher_escapes_graph_name_and_query() -> None:
    repository = _repository()
    captured: dict[str, str] = {}

    class FakeCursor:
        def execute(self, query: str) -> None:
            captured["query"] = query

    repository._execute_cypher(
        FakeCursor(),
        "MATCH (n {name: 'Source Trace'}) RETURN n",
    )

    rendered = captured["query"]
    assert "ag_catalog.cypher(" in rendered
    assert "'pggraphrag_memory'" in rendered
    assert "Source Trace" in rendered


def test_cypher_string_literal_escapes_quotes_and_backslashes() -> None:
    repository = _repository()

    rendered = repository._cypher_string_literal("O'Reilly\\Graph")

    assert rendered == "'O\\'Reilly\\\\Graph'"


def test_graph_refresh_unique_entity_normalization_accepts_uuid_values() -> None:
    raw_uuid = uuid.uuid4()
    normalized = (
        raw_uuid if isinstance(raw_uuid, uuid.UUID) else uuid.UUID(str(raw_uuid))
    )

    assert isinstance(normalized, uuid.UUID)
    assert normalized == raw_uuid


def test_source_payload_normalizes_dict_ids_to_strings() -> None:
    repository = _repository()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    payload = repository._source_payload(
        {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "source_uri": "memory://docs/alpha",
            "title": "Alpha",
            "chunk_no": 0,
            "snippet": "Alpha snippet",
        }
    )

    assert payload["document_id"] == str(document_id)
    assert payload["chunk_id"] == str(chunk_id)
    assert payload["source_uri"] == "memory://docs/alpha"


def test_json_dumps_can_serialize_uuid_and_datetime_like_values() -> None:
    from datetime import UTC, datetime

    from pggraphrag_mcp.repository import json_dumps

    payload = {
        "retrieval_id": uuid.uuid4(),
        "created_at": datetime.now(UTC),
    }

    rendered = json_dumps(payload)

    assert "retrieval_id" in rendered
    assert "created_at" in rendered

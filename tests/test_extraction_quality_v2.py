# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pggraphrag_mcp.repository import GraphRagRepository


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


def test_candidate_entities_trim_leading_generic_prefix_tokens() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "The GraphRAG Retrieval Pipeline uses Source Trace. "
            "The Platform Graph Memory Store contains Evidence Bundle."
        )
    )

    names = [item["canonical_name"] for item in entities]

    assert "GraphRAG Retrieval Pipeline" in names
    assert "Graph Memory Store" in names
    assert "Source Trace" in names
    assert "Evidence Bundle" in names
    assert "The GraphRAG Retrieval Pipeline" not in names
    assert "The Platform Graph Memory Store" not in names


def test_candidate_entities_trim_trailing_generic_suffix_tokens() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "Source Trace Service depends on Graph Memory System. "
            "Evidence Bundle Module is written to Storage Layer."
        )
    )

    names = [item["canonical_name"] for item in entities]

    assert "Source Trace" in names
    assert "Graph Memory" in names
    assert "Evidence Bundle" in names
    assert "Storage Layer" in names
    assert "Source Trace Service" not in names
    assert "Graph Memory System" not in names
    assert "Evidence Bundle Module" not in names


def test_candidate_entities_merge_compact_and_spaced_aliases() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "Graph Rag depends on Source Trace. "
            "GraphRag is referenced again beside SourceTrace."
        )
    )

    by_name = {item["canonical_name"]: item for item in entities}

    assert "Graph Rag" in by_name
    assert "Source Trace" in by_name

    graph_rag_aliases = by_name["Graph Rag"]["aliases"]
    source_trace_aliases = by_name["Source Trace"]["aliases"]

    assert "GraphRag" in graph_rag_aliases
    assert "SourceTrace" in source_trace_aliases


def test_candidate_entities_prefer_longer_phrase_over_shorter_overlap() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "Graph Memory Store depends on Source Trace. "
            "Graph Memory Store is refreshed later."
        )
    )

    names = [item["canonical_name"] for item in entities]

    assert "Graph Memory Store" in names
    assert "Graph Memory" not in names


def test_candidate_entities_do_not_cross_sentence_boundaries() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        ("GraphRAG Retrieval completes here. Source Trace begins in the next sentence.")
    )

    names = [item["canonical_name"] for item in entities]

    assert "GraphRAG Retrieval" in names
    assert "Source Trace" in names
    assert "GraphRAG Retrieval Source Trace" not in names


def test_candidate_relations_are_sentence_local_for_explicit_patterns() -> None:
    repository = _repository()

    source_trace = type(
        "Entity",
        (),
        {"entity_id": "entity-source-trace", "canonical_name": "Source Trace"},
    )()
    graph_memory = type(
        "Entity",
        (),
        {"entity_id": "entity-graph-memory", "canonical_name": "Graph Memory"},
    )()
    evidence_bundle = type(
        "Entity",
        (),
        {"entity_id": "entity-evidence-bundle", "canonical_name": "Evidence Bundle"},
    )()

    relations = repository._extract_candidate_relations(
        (
            "Source Trace depends on Graph Memory. "
            "Evidence Bundle is mentioned in a separate sentence."
        ),
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
            "entity-evidence-bundle": evidence_bundle,
        },
    )

    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_entity_id"] == "entity-source-trace"
    assert relation["target_entity_id"] == "entity-graph-memory"
    assert relation["relation_type"] == "DEPENDS_ON"


def test_candidate_relations_ignore_cross_sentence_pattern_bracketing() -> None:
    repository = _repository()

    source_trace = type(
        "Entity",
        (),
        {"entity_id": "entity-source-trace", "canonical_name": "Source Trace"},
    )()
    graph_memory = type(
        "Entity",
        (),
        {"entity_id": "entity-graph-memory", "canonical_name": "Graph Memory"},
    )()

    relations = repository._extract_candidate_relations(
        (
            "Source Trace is introduced in one sentence. "
            "Depends on is described here as a phrase only. "
            "Graph Memory appears afterwards in another sentence."
        ),
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )

    assert relations == []


def test_candidate_relations_prefer_nearest_entities_within_same_sentence() -> None:
    repository = _repository()

    graph_rag = type(
        "Entity",
        (),
        {"entity_id": "entity-graphrag", "canonical_name": "GraphRAG"},
    )()
    source_trace = type(
        "Entity",
        (),
        {"entity_id": "entity-source-trace", "canonical_name": "Source Trace"},
    )()
    graph_memory = type(
        "Entity",
        (),
        {"entity_id": "entity-graph-memory", "canonical_name": "Graph Memory"},
    )()

    relations = repository._extract_candidate_relations(
        (
            "GraphRAG uses Source Trace while Graph Memory is described later "
            "in the same sentence."
        ),
        entity_records_by_id={
            "entity-graphrag": graph_rag,
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )

    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_entity_id"] == "entity-graphrag"
    assert relation["target_entity_id"] == "entity-source-trace"
    assert relation["relation_type"] == "USES"


def test_candidate_relations_drop_distant_pairs_even_if_pattern_exists() -> None:
    repository = _repository()

    source_trace = type(
        "Entity",
        (),
        {"entity_id": "entity-source-trace", "canonical_name": "Source Trace"},
    )()
    graph_memory = type(
        "Entity",
        (),
        {"entity_id": "entity-graph-memory", "canonical_name": "Graph Memory"},
    )()

    text = (
        "Source Trace depends on many intermediate orchestration components and "
        "several unrelated buffering layers before Graph Memory is finally named."
    )

    relations = repository._extract_candidate_relations(
        text,
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )

    assert relations == []


def test_candidate_relations_weight_nearer_pattern_pairs_higher() -> None:
    repository = _repository()

    source_trace = type(
        "Entity",
        (),
        {"entity_id": "entity-source-trace", "canonical_name": "Source Trace"},
    )()
    graph_memory = type(
        "Entity",
        (),
        {"entity_id": "entity-graph-memory", "canonical_name": "Graph Memory"},
    )()

    near_relations = repository._extract_candidate_relations(
        "Source Trace depends on Graph Memory.",
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )
    far_relations = repository._extract_candidate_relations(
        (
            "Source Trace depends on several buffering stages before Graph Memory "
            "is referenced."
        ),
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )

    assert len(near_relations) == 1
    assert len(far_relations) == 1
    assert near_relations[0]["weight"] > far_relations[0]["weight"]


def test_candidate_entities_keep_stable_offsets_after_trimming() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        "The Source Trace Service writes to Graph Memory System."
    )

    by_name = {item["canonical_name"]: item for item in entities}
    source_trace = by_name["Source Trace"]
    graph_memory = by_name["Graph Memory"]

    assert source_trace["start_offset"] < source_trace["end_offset"]
    assert graph_memory["start_offset"] < graph_memory["end_offset"]
    assert source_trace["mention_count"] >= 1
    assert graph_memory["mention_count"] >= 1

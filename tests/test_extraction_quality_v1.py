# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


def test_extract_candidate_entities_reduces_single_token_alias_noise() -> None:
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "GraphRAG uses Source Trace. "
            "Source Trace depends on Graph Memory. "
            "Graph Memory contains Evidence Bundle."
        )
    )

    by_name = {item["canonical_name"]: item for item in entities}

    assert "Source Trace" in by_name
    assert "Graph Memory" in by_name
    assert "Evidence Bundle" in by_name

    assert by_name["Source Trace"]["aliases"] == ["SourceTrace"]
    assert by_name["Graph Memory"]["aliases"] == ["GraphMemory"]
    assert by_name["Evidence Bundle"]["aliases"] == ["EvidenceBundle"]


def test_extract_candidate_entities_keeps_compound_entity_but_filters_generic_aliases() -> (
    None
):
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "Control Plane connects to Worker Node. "
            "Worker Node depends on Metadata Store."
        )
    )

    by_name = {item["canonical_name"]: item for item in entities}

    assert by_name["Control Plane"]["aliases"] == ["ControlPlane"]
    assert by_name["Worker Node"]["aliases"] == ["WorkerNode"]
    assert by_name["Metadata Store"]["aliases"] == ["MetadataStore"]


def test_extract_candidate_entities_deduplicates_repeated_mentions_without_alias_bloat() -> (
    None
):
    repository = _repository()

    entities = repository._extract_candidate_entities(
        (
            "Source Trace reads Graph Memory. "
            "Source Trace writes Graph Memory. "
            "Source Trace verifies Graph Memory."
        )
    )

    names = [item["canonical_name"] for item in entities]
    assert names.count("Source Trace") == 1
    assert names.count("Graph Memory") == 1

    by_name = {item["canonical_name"]: item for item in entities}
    assert by_name["Source Trace"]["aliases"] == ["SourceTrace"]
    assert by_name["Graph Memory"]["aliases"] == ["GraphMemory"]


def test_extract_candidate_relations_pairs_entities_by_local_pattern_order() -> None:
    repository = _repository()

    source_entity = type(
        "Entity",
        (),
        {"entity_id": "entity-source", "canonical_name": "Source Trace"},
    )()
    target_entity = type(
        "Entity",
        (),
        {"entity_id": "entity-target", "canonical_name": "Graph Memory"},
    )()
    distractor_entity = type(
        "Entity",
        (),
        {"entity_id": "entity-distractor", "canonical_name": "Evidence Bundle"},
    )()

    relations = repository._extract_candidate_relations(
        "Source Trace depends on Graph Memory. Evidence Bundle is also mentioned.",
        entity_records_by_id={
            "entity-source": source_entity,
            "entity-target": target_entity,
            "entity-distractor": distractor_entity,
        },
    )

    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_entity_id"] == "entity-source"
    assert relation["target_entity_id"] == "entity-target"
    assert relation["relation_type"] == "DEPENDS_ON"
    assert relation["pattern"] == "depends on"
    assert relation["weight"] == pytest.approx(0.97)


def test_extract_candidate_relations_prefers_nearest_entities_for_uses_pattern() -> (
    None
):
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
            "GraphRAG uses Source Trace while Graph Memory is described separately. "
            "Later Graph Memory is discussed again."
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


def test_extract_candidate_relations_ignores_pattern_when_entities_do_not_bracket_it() -> (
    None
):
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
            "Depends on is documented here as a phrase only. "
            "Source Trace and Graph Memory are mentioned later without the pattern between them."
        ),
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )

    assert relations == []


def test_extract_candidate_relations_deduplicates_same_relation_pattern() -> None:
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
            "Source Trace depends on Graph Memory. "
            "Source Trace depends on Graph Memory for retrieval."
        ),
        entity_records_by_id={
            "entity-source-trace": source_trace,
            "entity-graph-memory": graph_memory,
        },
    )

    assert len(relations) == 1
    assert relations[0]["source_entity_id"] == "entity-source-trace"
    assert relations[0]["target_entity_id"] == "entity-graph-memory"
    assert relations[0]["relation_type"] == "DEPENDS_ON"


def test_extract_candidate_relations_handles_contains_and_connects_to_patterns() -> (
    None
):
    repository = _repository()

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
    control_plane = type(
        "Entity",
        (),
        {"entity_id": "entity-control-plane", "canonical_name": "Control Plane"},
    )()
    worker_node = type(
        "Entity",
        (),
        {"entity_id": "entity-worker-node", "canonical_name": "Worker Node"},
    )()

    contains_relations = repository._extract_candidate_relations(
        "Graph Memory contains Evidence Bundle.",
        entity_records_by_id={
            "entity-graph-memory": graph_memory,
            "entity-evidence-bundle": evidence_bundle,
        },
    )
    connects_relations = repository._extract_candidate_relations(
        "Control Plane connects to Worker Node.",
        entity_records_by_id={
            "entity-control-plane": control_plane,
            "entity-worker-node": worker_node,
        },
    )

    assert len(contains_relations) == 1
    assert contains_relations[0]["relation_type"] == "CONTAINS"
    assert contains_relations[0]["source_entity_id"] == "entity-graph-memory"
    assert contains_relations[0]["target_entity_id"] == "entity-evidence-bundle"

    assert len(connects_relations) == 1
    assert connects_relations[0]["relation_type"] == "CONNECTS_TO"
    assert connects_relations[0]["source_entity_id"] == "entity-control-plane"
    assert connects_relations[0]["target_entity_id"] == "entity-worker-node"

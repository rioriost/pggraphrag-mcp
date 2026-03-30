from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import UUID

_MAX_PREVIEW_TEXT_LENGTH = 280
_MAX_SUMMARY_LENGTH = 800


class ValidationError(ValueError):
    """Raised when an incoming request or payload is invalid."""


@dataclass(frozen=True, slots=True)
class RetrievalBounds:
    """Boundaries applied to retrieval requests and shaped responses."""

    max_vector_candidates: int
    max_graph_hops: int
    max_return_chunks: int
    max_return_entities: int
    max_summary_length: int = _MAX_SUMMARY_LENGTH
    max_preview_text_length: int = _MAX_PREVIEW_TEXT_LENGTH

    def __post_init__(self) -> None:
        if self.max_vector_candidates < 1:
            raise ValidationError("max_vector_candidates must be >= 1")
        if self.max_graph_hops < 0:
            raise ValidationError("max_graph_hops must be >= 0")
        if self.max_return_chunks < 1:
            raise ValidationError("max_return_chunks must be >= 1")
        if self.max_return_entities < 1:
            raise ValidationError("max_return_entities must be >= 1")
        if self.max_summary_length < 1:
            raise ValidationError("max_summary_length must be >= 1")
        if self.max_preview_text_length < 1:
            raise ValidationError("max_preview_text_length must be >= 1")


def require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field_name} must be an object")
    return value


def normalize_text(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
    max_length: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")

    normalized = " ".join(value.split()).strip()
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must not be empty")

    if max_length is not None and len(normalized) > max_length:
        raise ValidationError(f"{field_name} must be <= {max_length} characters")

    return normalized


def normalize_optional_text(
    value: Any,
    *,
    field_name: str,
    max_length: int | None = None,
) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(
        value,
        field_name=field_name,
        allow_empty=True,
        max_length=max_length,
    )
    return normalized or None


def normalize_int(
    value: Any,
    *,
    field_name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field_name} must be an integer")

    if minimum is not None and value < minimum:
        raise ValidationError(f"{field_name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{field_name} must be <= {maximum}")

    return value


def normalize_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a boolean")
    return value


def normalize_uuid(value: Any, *, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a UUID string")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be a valid UUID") from exc


def normalize_metadata(value: Any, *, field_name: str = "metadata") -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field_name} must be an object")
    return {str(key): coerce_json_value(item) for key, item in value.items()}


def normalize_string_list(
    value: Any,
    *,
    field_name: str,
    max_items: int | None = None,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationError(f"{field_name} must be an array of strings")

    normalized: list[str] = []
    for item in value:
        normalized.append(normalize_text(item, field_name=field_name))

    if max_items is not None and len(normalized) > max_items:
        raise ValidationError(f"{field_name} must contain at most {max_items} items")

    return normalized


def validate_retrieval_request(
    arguments: Mapping[str, Any],
    *,
    bounds: RetrievalBounds,
) -> dict[str, Any]:
    query = normalize_text(arguments.get("query"), field_name="query", max_length=2000)
    top_k = normalize_int(
        arguments.get("top_k", min(5, bounds.max_return_chunks)),
        field_name="top_k",
        minimum=1,
        maximum=bounds.max_return_chunks,
    )
    graph_limit = normalize_int(
        arguments.get("graph_limit", bounds.max_return_entities),
        field_name="graph_limit",
        minimum=1,
        maximum=bounds.max_return_entities,
    )
    graph_hops = normalize_int(
        arguments.get("graph_hops", min(1, bounds.max_graph_hops)),
        field_name="graph_hops",
        minimum=0,
        maximum=bounds.max_graph_hops,
    )
    include_summary = normalize_bool(
        arguments.get("include_summary", True),
        field_name="include_summary",
    )

    return {
        "query": query,
        "top_k": top_k,
        "graph_limit": graph_limit,
        "graph_hops": graph_hops,
        "include_summary": include_summary,
    }


def validate_entity_search_request(
    arguments: Mapping[str, Any],
    *,
    bounds: RetrievalBounds,
) -> dict[str, Any]:
    query = normalize_text(arguments.get("query"), field_name="query", max_length=500)
    limit = normalize_int(
        arguments.get("limit", bounds.max_return_entities),
        field_name="limit",
        minimum=1,
        maximum=bounds.max_return_entities,
    )
    return {
        "query": query,
        "limit": limit,
    }


def validate_entity_expand_request(
    arguments: Mapping[str, Any],
    *,
    bounds: RetrievalBounds,
) -> dict[str, Any]:
    entity_id = normalize_uuid(arguments.get("entity_id"), field_name="entity_id")
    hops = normalize_int(
        arguments.get("hops", min(1, bounds.max_graph_hops)),
        field_name="hops",
        minimum=0,
        maximum=bounds.max_graph_hops,
    )
    limit = normalize_int(
        arguments.get("limit", bounds.max_return_entities),
        field_name="limit",
        minimum=1,
        maximum=bounds.max_return_entities,
    )
    return {
        "entity_id": entity_id,
        "hops": hops,
        "limit": limit,
    }


def validate_source_trace_request(arguments: Mapping[str, Any]) -> dict[str, Any]:
    retrieval_id = normalize_uuid(
        arguments.get("retrieval_id"),
        field_name="retrieval_id",
    )
    return {"retrieval_id": retrieval_id}


def validate_document_ingest_request(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": normalize_text(
            arguments.get("tenant_id", "default"),
            field_name="tenant_id",
            max_length=200,
        ),
        "source_uri": normalize_text(
            arguments.get("source_uri"),
            field_name="source_uri",
            max_length=2000,
        ),
        "title": normalize_text(
            arguments.get("title"),
            field_name="title",
            max_length=500,
        ),
        "text": normalize_text(
            arguments.get("text", arguments.get("content")),
            field_name="text",
            max_length=200_000,
        ),
        "mime_type": normalize_text(
            arguments.get("mime_type", "text/plain"),
            field_name="mime_type",
            max_length=200,
        ),
        "metadata": normalize_metadata(arguments.get("metadata")),
        "reingest": bool(arguments.get("reingest", True)),
    }


def validate_graph_refresh_request(
    arguments: Mapping[str, Any],
    *,
    allow_full_rebuild: bool = True,
) -> dict[str, Any]:
    full_rebuild = bool(arguments.get("full_rebuild", False))
    document_id_raw = arguments.get("document_id")

    if full_rebuild and not allow_full_rebuild:
        raise ValidationError("full_rebuild is not allowed")

    if full_rebuild and document_id_raw is not None:
        raise ValidationError("document_id cannot be combined with full_rebuild=true")

    document_id = (
        normalize_uuid(document_id_raw, field_name="document_id")
        if document_id_raw is not None
        else None
    )

    return {
        "full_rebuild": full_rebuild,
        "document_id": document_id,
    }


def coerce_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): coerce_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [coerce_json_value(item) for item in value]
    return str(value)


def truncate_text(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    if len(value) <= max_length:
        return value
    if max_length <= 1:
        return value[:max_length]
    return f"{value[: max_length - 1]}…"


def shape_supporting_chunks(
    chunks: Sequence[Mapping[str, Any]],
    *,
    bounds: RetrievalBounds,
) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for chunk in list(chunks)[: bounds.max_return_chunks]:
        shaped.append(
            {
                "chunk_id": _string_or_none(chunk.get("chunk_id")),
                "document_id": _string_or_none(chunk.get("document_id")),
                "chunk_no": _int_or_default(chunk.get("chunk_no"), 0),
                "text": truncate_text(
                    _string_or_default(chunk.get("text")),
                    bounds.max_preview_text_length,
                )
                or "",
                "score": _float_or_default(chunk.get("score"), 0.0),
                "source_uri": _string_or_none(chunk.get("source_uri")),
                "title": _string_or_none(chunk.get("title")),
                "metadata": normalize_metadata(chunk.get("metadata", {})),
            }
        )
    return shaped


def shape_entities(
    entities: Sequence[Mapping[str, Any]],
    *,
    bounds: RetrievalBounds,
) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for entity in list(entities)[: bounds.max_return_entities]:
        shaped.append(
            {
                "entity_id": _string_or_none(entity.get("entity_id")),
                "canonical_name": _string_or_default(entity.get("canonical_name")),
                "entity_type": _string_or_default(entity.get("entity_type")),
                "score": _float_or_default(entity.get("score"), 0.0),
                "aliases": normalize_string_list(
                    entity.get("aliases", []),
                    field_name="aliases",
                    max_items=20,
                ),
                "metadata": normalize_metadata(entity.get("metadata", {})),
            }
        )
    return shaped


def shape_relationships(
    relationships: Sequence[Mapping[str, Any]],
    *,
    bounds: RetrievalBounds,
) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for relationship in list(relationships)[: bounds.max_return_entities]:
        shaped.append(
            {
                "relation_fact_id": _string_or_none(
                    relationship.get("relation_fact_id")
                ),
                "source_entity_id": _string_or_none(
                    relationship.get("source_entity_id")
                ),
                "source_entity_name": _string_or_none(
                    relationship.get("source_entity_name")
                ),
                "target_entity_id": _string_or_none(
                    relationship.get("target_entity_id")
                ),
                "target_entity_name": _string_or_none(
                    relationship.get("target_entity_name")
                ),
                "relation_type": _string_or_default(relationship.get("relation_type")),
                "weight": _float_or_default(relationship.get("weight"), 0.0),
                "evidence_chunk_id": _string_or_none(
                    relationship.get("evidence_chunk_id")
                ),
                "metadata": normalize_metadata(relationship.get("metadata", {})),
            }
        )
    return shaped


def shape_sources(
    sources: Sequence[Mapping[str, Any]],
    *,
    bounds: RetrievalBounds,
) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for source in list(sources)[: bounds.max_return_chunks]:
        shaped.append(
            {
                "document_id": _string_or_none(source.get("document_id")),
                "chunk_id": _string_or_none(source.get("chunk_id")),
                "source_uri": _string_or_none(source.get("source_uri")),
                "title": _string_or_none(source.get("title")),
                "chunk_no": _int_or_default(source.get("chunk_no"), 0),
                "snippet": truncate_text(
                    _string_or_none(source.get("snippet")),
                    bounds.max_preview_text_length,
                ),
            }
        )
    return shaped


def shape_retrieval_payload(
    payload: Mapping[str, Any],
    *,
    bounds: RetrievalBounds,
) -> dict[str, Any]:
    summary = (
        truncate_text(
            _string_or_default(payload.get("summary")),
            bounds.max_summary_length,
        )
        or ""
    )

    return {
        "retrieval_id": _string_or_none(payload.get("retrieval_id")),
        "summary": summary,
        "mode": _string_or_default(payload.get("mode")),
        "supporting_chunks": shape_supporting_chunks(
            payload.get("supporting_chunks", []),
            bounds=bounds,
        ),
        "entities": shape_entities(payload.get("entities", []), bounds=bounds),
        "relationships": shape_relationships(
            payload.get("relationships", []),
            bounds=bounds,
        ),
        "sources": shape_sources(payload.get("sources", []), bounds=bounds),
        "confidence": _float_or_default(payload.get("confidence"), 0.0),
        "timings": normalize_metadata(payload.get("timings", {}), field_name="timings"),
    }


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_or_default(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _int_or_default(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_or_default(value: Any, default: float) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


__all__ = [
    "RetrievalBounds",
    "ValidationError",
    "coerce_json_value",
    "normalize_bool",
    "normalize_int",
    "normalize_metadata",
    "normalize_optional_text",
    "normalize_string_list",
    "normalize_text",
    "normalize_uuid",
    "require_mapping",
    "shape_entities",
    "shape_relationships",
    "shape_retrieval_payload",
    "shape_sources",
    "shape_supporting_chunks",
    "truncate_text",
    "validate_document_ingest_request",
    "validate_entity_expand_request",
    "validate_entity_search_request",
    "validate_graph_refresh_request",
    "validate_retrieval_request",
    "validate_source_trace_request",
]

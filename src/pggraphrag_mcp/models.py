from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class StatusEnum(StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    deleted = "deleted"


class RetrievalMode(StrEnum):
    naive = "naive"
    local_graph = "local_graph"
    hybrid = "hybrid"


class EntityType(StrEnum):
    unknown = "unknown"
    person = "person"
    organization = "organization"
    location = "location"
    concept = "concept"
    technology = "technology"
    event = "event"
    document = "document"


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    title: str = Field(min_length=1)
    mime_type: str = Field(default="text/plain", min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_no: int = Field(ge=0)
    text: str = Field(min_length=1)
    token_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(min_length=1)
    entity_type: EntityType = EntityType.unknown
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str = Field(min_length=1)
    weight: float = Field(default=1.0, ge=0.0)
    evidence_chunk_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    title: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    status: StatusEnum = StatusEnum.pending
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    chunk_no: int = Field(ge=0)
    text: str = Field(min_length=1)
    token_count: int = Field(default=0, ge=0)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EntityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: UUID = Field(default_factory=uuid4)
    canonical_name: str = Field(min_length=1)
    entity_type: EntityType = EntityType.unknown
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ChunkEntityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    entity_id: UUID
    mention_count: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationFactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_fact_id: UUID = Field(default_factory=uuid4)
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str = Field(min_length=1)
    weight: float = Field(default=1.0, ge=0.0)
    evidence_chunk_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class IngestionJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestion_job_id: UUID = Field(default_factory=uuid4)
    document_id: UUID | None = None
    status: StatusEnum = StatusEnum.pending
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestion_job: IngestionJobRecord
    document: DocumentRecord
    chunks: list[ChunkRecord] = Field(default_factory=list)
    entities: list[EntityRecord] = Field(default_factory=list)
    relations: list[RelationFactRecord] = Field(default_factory=list)


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    mode: RetrievalMode = RetrievalMode.naive
    top_k: int = Field(default=5, ge=1)
    max_graph_hops: int = Field(default=1, ge=0)
    include_summary: bool = True
    filters: dict[str, Any] = Field(default_factory=dict)


class SupportingChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    document_id: UUID
    chunk_no: int = Field(ge=0)
    text: str
    source_uri: str
    title: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    canonical_name: str
    entity_type: EntityType = EntityType.unknown
    score: float = 0.0
    evidence_chunk_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_fact_id: UUID | None = None
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str
    weight: float = 1.0
    evidence_chunk_id: UUID | None = None
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    chunk_id: UUID | None = None
    source_uri: str
    title: str
    snippet: str | None = None
    score: float = 0.0


class RetrievalLogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_id: UUID = Field(default_factory=uuid4)
    query_text: str = Field(min_length=1)
    mode: RetrievalMode
    returned_source_ids: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_id: UUID = Field(default_factory=uuid4)
    mode: RetrievalMode
    summary: str | None = None
    supporting_chunks: list[SupportingChunk] = Field(default_factory=list)
    entities: list[RetrievedEntity] = Field(default_factory=list)
    relationships: list[RetrievedRelationship] = Field(default_factory=list)
    sources: list[RetrievalSource] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    timings: dict[str, float] = Field(default_factory=dict)


class GraphNodeType(StrEnum):
    document = "Document"
    chunk = "Chunk"
    entity = "Entity"


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: GraphNodeType
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphRefreshScope(StrEnum):
    document = "document"
    full = "full"


class GraphRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: GraphRefreshScope = GraphRefreshScope.full
    document_id: UUID | None = None


class GraphRefreshResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_name: str = Field(min_length=1)
    scope: GraphRefreshScope
    refreshed_document_id: UUID | None = None
    node_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)
    status: StatusEnum = StatusEnum.completed
    updated_at: datetime = Field(default_factory=utc_now)


class GraphStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_name: str = Field(min_length=1)
    age_extension_installed: bool = False
    graph_exists: bool = False
    node_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)
    last_refresh_at: datetime | None = None
    status: str = "unknown"


class EntitySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    entities: list[RetrievedEntity] = Field(default_factory=list)


class EntityExpandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    hops: int = Field(default=1, ge=0)
    root_entity: RetrievedEntity
    neighbor_entities: list[RetrievedEntity] = Field(default_factory=list)
    relationships: list[RetrievedRelationship] = Field(default_factory=list)
    sources: list[RetrievalSource] = Field(default_factory=list)


class TraceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    document_id: UUID
    chunk_no: int = Field(ge=0)
    text: str
    source_uri: str
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    canonical_name: str
    entity_type: EntityType = EntityType.unknown
    evidence_chunk_ids: list[UUID] = Field(default_factory=list)


class TraceRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_fact_id: UUID | None = None
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str
    evidence_chunk_id: UUID | None = None
    weight: float = 1.0


class SourceTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_id: UUID
    query_text: str
    mode: RetrievalMode
    chunks: list[TraceChunk] = Field(default_factory=list)
    entities: list[TraceEntity] = Field(default_factory=list)
    relationships: list[TraceRelationship] = Field(default_factory=list)
    sources: list[RetrievalSource] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class HealthCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    app_name: str
    version: str
    environment: str
    database: dict[str, Any] = Field(default_factory=dict)


class IndexStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int = Field(ge=0)
    max_vector_candidates: int = Field(ge=0)
    max_return_chunks: int = Field(ge=0)
    database_ready: bool = False
    vector_extension_installed: bool = False
    document_table_exists: bool = False
    chunk_table_exists: bool = False

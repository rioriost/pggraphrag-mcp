from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

WORD_RE = re.compile(r"\b[\w][\w\-/.:]*\b", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n{2,}")
ENTITY_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9_-]{1,}\b")
RELATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "contains",
        re.compile(
            r"\b(?P<source>[A-Z][A-Za-z0-9_-]{1,})\s+contains\s+(?P<target>[A-Z][A-Za-z0-9_-]{1,})\b"
        ),
    ),
    (
        "uses",
        re.compile(
            r"\b(?P<source>[A-Z][A-Za-z0-9_-]{1,})\s+uses\s+(?P<target>[A-Z][A-Za-z0-9_-]{1,})\b"
        ),
    ),
    (
        "connects_to",
        re.compile(
            r"\b(?P<source>[A-Z][A-Za-z0-9_-]{1,})\s+connects(?:\s+to)?\s+(?P<target>[A-Z][A-Za-z0-9_-]{1,})\b"
        ),
    ),
    (
        "depends_on",
        re.compile(
            r"\b(?P<source>[A-Z][A-Za-z0-9_-]{1,})\s+depends\s+on\s+(?P<target>[A-Z][A-Za-z0-9_-]{1,})\b"
        ),
    ),
    (
        "part_of",
        re.compile(
            r"\b(?P<source>[A-Z][A-Za-z0-9_-]{1,})\s+part\s+of\s+(?P<target>[A-Z][A-Za-z0-9_-]{1,})\b"
        ),
    ),
)


@dataclass(slots=True, frozen=True)
class DocumentInput:
    tenant_id: str
    source_uri: str
    title: str
    mime_type: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class DocumentRecord:
    document_id: uuid.UUID
    tenant_id: str
    source_uri: str
    title: str
    mime_type: str
    content_hash: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ChunkRecord:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_no: int
    text: str
    token_count: int
    content_hash: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class EntityRecord:
    entity_id: uuid.UUID
    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ChunkEntityRecord:
    chunk_id: uuid.UUID
    entity_id: uuid.UUID
    mention_count: int
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RelationFactRecord:
    relation_fact_id: uuid.UUID
    source_entity_name: str
    target_entity_name: str
    relation_type: str
    weight: float
    evidence_chunk_id: uuid.UUID
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class IngestionBundle:
    document: DocumentRecord
    chunks: tuple[ChunkRecord, ...]
    entities: tuple[EntityRecord, ...]
    chunk_entities: tuple[ChunkEntityRecord, ...]
    relation_facts: tuple[RelationFactRecord, ...]


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def sha256_hexdigest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_uuid(namespace: uuid.UUID, *parts: object) -> uuid.UUID:
    raw = "::".join(str(part) for part in parts)
    return uuid.uuid5(namespace, raw)


def tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text)


def estimate_token_count(text: str) -> int:
    return len(tokenize(text))


def split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(normalized)]
    return [part for part in parts if part]


def chunk_text(
    text: str,
    *,
    target_tokens: int = 180,
    max_tokens: int = 240,
    overlap_tokens: int = 24,
) -> list[str]:
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if max_tokens < target_tokens:
        raise ValueError("max_tokens must be greater than or equal to target_tokens")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must not be negative")

    sentences = split_sentences(text)
    if not sentences:
        normalized = normalize_text(text)
        return [normalized] if normalized else []

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = estimate_token_count(sentence)
        if sentence_tokens == 0:
            continue

        if sentence_tokens >= max_tokens:
            if current_sentences:
                chunks.append(" ".join(current_sentences).strip())
                current_sentences = []
                current_tokens = 0

            long_sentence_tokens = tokenize(sentence)
            start = 0
            step = max(1, max_tokens - overlap_tokens)
            while start < len(long_sentence_tokens):
                end = min(start + max_tokens, len(long_sentence_tokens))
                segment = " ".join(long_sentence_tokens[start:end]).strip()
                if segment:
                    chunks.append(segment)
                if end == len(long_sentence_tokens):
                    break
                start += step
            continue

        would_exceed = current_tokens + sentence_tokens > max_tokens
        reached_target = current_tokens >= target_tokens

        if current_sentences and (would_exceed or reached_target):
            chunks.append(" ".join(current_sentences).strip())
            overlap = _take_overlap_tokens(" ".join(current_sentences), overlap_tokens)
            current_sentences = [overlap] if overlap else []
            current_tokens = estimate_token_count(overlap)

        current_sentences.append(sentence)
        current_tokens += sentence_tokens

    if current_sentences:
        chunks.append(" ".join(current_sentences).strip())

    return [chunk for chunk in chunks if chunk]


def _take_overlap_tokens(text: str, overlap_tokens: int) -> str:
    if overlap_tokens == 0:
        return ""
    words = tokenize(text)
    if not words:
        return ""
    return " ".join(words[-overlap_tokens:])


def infer_entity_type(name: str) -> str:
    if "/" in name or "." in name:
        return "resource"
    if name.endswith(("DB", "API", "MCP", "SQL", "HTTP", "HTTPS")):
        return "system"
    if name.isupper():
        return "concept"
    return "entity"


def extract_entities(text: str) -> list[tuple[str, int]]:
    candidates = ENTITY_TOKEN_RE.findall(text)
    counter = Counter(candidates)
    return sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))


def extract_relations(text: str) -> list[tuple[str, str, str]]:
    relations: list[tuple[str, str, str]] = []
    for relation_type, pattern in RELATION_PATTERNS:
        for match in pattern.finditer(text):
            source = match.group("source")
            target = match.group("target")
            if source != target:
                relations.append((source, target, relation_type))
    return relations


def pseudo_embedding(
    text: str,
    *,
    dimensions: int = 1536,
) -> list[float]:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")

    tokens = tokenize(text.lower())
    if not tokens:
        return [0.0] * dimensions

    vector = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(0, min(len(digest), dimensions)):
            value = digest[index] / 255.0
            vector[index] += value

    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return vector

    return [component / norm for component in vector]


class DocumentPipeline:
    def __init__(
        self,
        *,
        chunk_target_tokens: int = 180,
        chunk_max_tokens: int = 240,
        chunk_overlap_tokens: int = 24,
        embedding_dimensions: int = 1536,
        document_namespace: uuid.UUID = uuid.UUID(
            "4baf9796-5668-4a9a-a6d2-c62543470111"
        ),
        chunk_namespace: uuid.UUID = uuid.UUID("0b6812c3-cd95-4e9e-9a7f-d80ed3d84e6d"),
        entity_namespace: uuid.UUID = uuid.UUID("e808aaaf-73ec-4e78-8163-98079b4175d1"),
        relation_namespace: uuid.UUID = uuid.UUID(
            "b0c67f4e-662a-4e58-a6f1-a76f5f9367e8"
        ),
    ) -> None:
        self.chunk_target_tokens = chunk_target_tokens
        self.chunk_max_tokens = chunk_max_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.embedding_dimensions = embedding_dimensions
        self.document_namespace = document_namespace
        self.chunk_namespace = chunk_namespace
        self.entity_namespace = entity_namespace
        self.relation_namespace = relation_namespace

    def build_bundle(self, document_input: DocumentInput) -> IngestionBundle:
        normalized_text = normalize_text(document_input.text)
        content_hash = sha256_hexdigest(normalized_text)
        timestamp = utc_now()

        document_id = stable_uuid(
            self.document_namespace,
            document_input.tenant_id,
            document_input.source_uri,
            content_hash,
        )

        document = DocumentRecord(
            document_id=document_id,
            tenant_id=document_input.tenant_id,
            source_uri=document_input.source_uri,
            title=document_input.title,
            mime_type=document_input.mime_type,
            content_hash=content_hash,
            status="ready",
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(document_input.metadata),
        )

        chunk_texts = chunk_text(
            normalized_text,
            target_tokens=self.chunk_target_tokens,
            max_tokens=self.chunk_max_tokens,
            overlap_tokens=self.chunk_overlap_tokens,
        )

        chunks: list[ChunkRecord] = []
        entity_index: dict[str, EntityRecord] = {}
        chunk_entities: list[ChunkEntityRecord] = []
        relation_facts: list[RelationFactRecord] = []

        for chunk_no, chunk_body in enumerate(chunk_texts):
            chunk_hash = sha256_hexdigest(chunk_body)
            chunk_id = stable_uuid(
                self.chunk_namespace,
                document_id,
                chunk_no,
                chunk_hash,
            )

            chunk_record = ChunkRecord(
                chunk_id=chunk_id,
                document_id=document_id,
                chunk_no=chunk_no,
                text=chunk_body,
                token_count=estimate_token_count(chunk_body),
                content_hash=chunk_hash,
                metadata={
                    "embedding_dimensions": self.embedding_dimensions,
                    "pseudo_embedding_preview": pseudo_embedding(
                        chunk_body,
                        dimensions=min(16, self.embedding_dimensions),
                    ),
                },
            )
            chunks.append(chunk_record)

            extracted_entities = extract_entities(chunk_body)
            for name, mention_count in extracted_entities:
                entity_record = entity_index.get(name)
                if entity_record is None:
                    entity_record = EntityRecord(
                        entity_id=stable_uuid(self.entity_namespace, name.lower()),
                        canonical_name=name,
                        entity_type=infer_entity_type(name),
                        aliases=(),
                        metadata={},
                    )
                    entity_index[name] = entity_record

                chunk_entities.append(
                    ChunkEntityRecord(
                        chunk_id=chunk_id,
                        entity_id=entity_record.entity_id,
                        mention_count=mention_count,
                        metadata={},
                    )
                )

            for source_name, target_name, relation_type in extract_relations(
                chunk_body
            ):
                if source_name not in entity_index:
                    entity_index[source_name] = EntityRecord(
                        entity_id=stable_uuid(
                            self.entity_namespace, source_name.lower()
                        ),
                        canonical_name=source_name,
                        entity_type=infer_entity_type(source_name),
                        aliases=(),
                        metadata={},
                    )
                if target_name not in entity_index:
                    entity_index[target_name] = EntityRecord(
                        entity_id=stable_uuid(
                            self.entity_namespace, target_name.lower()
                        ),
                        canonical_name=target_name,
                        entity_type=infer_entity_type(target_name),
                        aliases=(),
                        metadata={},
                    )

                relation_facts.append(
                    RelationFactRecord(
                        relation_fact_id=stable_uuid(
                            self.relation_namespace,
                            source_name.lower(),
                            target_name.lower(),
                            relation_type,
                            chunk_id,
                        ),
                        source_entity_name=source_name,
                        target_entity_name=target_name,
                        relation_type=relation_type,
                        weight=1.0,
                        evidence_chunk_id=chunk_id,
                        metadata={},
                    )
                )

        entities = tuple(
            sorted(entity_index.values(), key=lambda item: item.canonical_name.lower())
        )

        return IngestionBundle(
            document=document,
            chunks=tuple(chunks),
            entities=entities,
            chunk_entities=tuple(chunk_entities),
            relation_facts=tuple(relation_facts),
        )

    def build_document_record(self, document_input: DocumentInput) -> DocumentRecord:
        return self.build_bundle(document_input).document

    def build_chunks(self, document_input: DocumentInput) -> tuple[ChunkRecord, ...]:
        return self.build_bundle(document_input).chunks


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_list = list(left)
    right_list = list(right)

    if len(left_list) != len(right_list):
        raise ValueError("Vectors must have the same length")

    numerator = sum(a * b for a, b in zip(left_list, right_list))
    left_norm = math.sqrt(sum(a * a for a in left_list))
    right_norm = math.sqrt(sum(b * b for b in right_list))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return numerator / (left_norm * right_norm)

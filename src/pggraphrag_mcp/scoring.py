from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    if math.isnan(value) or math.isinf(value):
        return minimum
    return max(minimum, min(maximum, value))


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return numerator / (left_norm * right_norm)


def lexical_overlap(
    query_tokens: Iterable[str],
    candidate_tokens: Iterable[str],
) -> float:
    query_set = {token for token in query_tokens if token}
    candidate_set = {token for token in candidate_tokens if token}

    if not query_set:
        return 0.0

    overlap = query_set & candidate_set
    return clamp(safe_divide(len(overlap), len(query_set)))


def jaccard_similarity(
    left_tokens: Iterable[str],
    right_tokens: Iterable[str],
) -> float:
    left_set = {token for token in left_tokens if token}
    right_set = {token for token in right_tokens if token}

    if not left_set and not right_set:
        return 0.0

    intersection = left_set & right_set
    union = left_set | right_set
    return clamp(safe_divide(len(intersection), len(union)))


def normalize_recency_rank(rank: int, total_count: int) -> float:
    if total_count <= 1:
        return 1.0
    if rank < 0:
        rank = 0
    if rank >= total_count:
        rank = total_count - 1
    return clamp(1.0 - safe_divide(rank, total_count - 1))


def score_presence(count: int, *, max_count: int = 5) -> float:
    if max_count <= 0:
        return 0.0
    return clamp(safe_divide(max(count, 0), max_count))


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    embedding: float = 0.55
    lexical: float = 0.25
    jaccard: float = 0.05
    entity: float = 0.05
    relation: float = 0.07
    recency: float = 0.03

    @property
    def total(self) -> float:
        return (
            self.embedding
            + self.lexical
            + self.jaccard
            + self.entity
            + self.relation
            + self.recency
        )

    def normalized(self) -> "ScoreWeights":
        total = self.total
        if total <= 0:
            return ScoreWeights()
        return ScoreWeights(
            embedding=self.embedding / total,
            lexical=self.lexical / total,
            jaccard=self.jaccard / total,
            entity=self.entity / total,
            relation=self.relation / total,
            recency=self.recency / total,
        )


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    embedding_similarity: float = 0.0
    lexical_overlap: float = 0.0
    jaccard_similarity: float = 0.0
    entity_evidence: float = 0.0
    relation_evidence: float = 0.0
    recency: float = 0.0
    raw_score: float = 0.0
    weighted_score: float = 0.0
    confidence: float = 0.0
    rank_hint: float = 0.0
    weights: Mapping[str, float] = field(default_factory=dict)
    normalized_contributions: Mapping[str, float] = field(default_factory=dict)
    evidence: Mapping[str, float | int | str] = field(default_factory=dict)

    def to_dict(
        self,
    ) -> dict[
        str,
        float | dict[str, float] | dict[str, float | int | str],
    ]:
        return {
            "embedding_similarity": round(self.embedding_similarity, 4),
            "lexical_overlap": round(self.lexical_overlap, 4),
            "jaccard_similarity": round(self.jaccard_similarity, 4),
            "entity_evidence": round(self.entity_evidence, 4),
            "relation_evidence": round(self.relation_evidence, 4),
            "recency": round(self.recency, 4),
            "raw_score": round(self.raw_score, 4),
            "weighted_score": round(self.weighted_score, 4),
            "confidence": round(self.confidence, 4),
            "rank_hint": round(self.rank_hint, 4),
            "weights": {key: round(value, 4) for key, value in self.weights.items()},
            "normalized_contributions": {
                key: round(value, 4)
                for key, value in self.normalized_contributions.items()
            },
            "evidence": {
                key: round(value, 4) if isinstance(value, float) else value
                for key, value in self.evidence.items()
            },
        }


@dataclass(frozen=True, slots=True)
class CandidateSignals:
    embedding_similarity: float = 0.0
    lexical_overlap: float = 0.0
    jaccard_similarity: float = 0.0
    entity_evidence: float = 0.0
    relation_evidence: float = 0.0
    recency: float = 0.0
    evidence: Mapping[str, float | int | str] = field(default_factory=dict)

    def normalized(self) -> "CandidateSignals":
        return CandidateSignals(
            embedding_similarity=clamp(self.embedding_similarity),
            lexical_overlap=clamp(self.lexical_overlap),
            jaccard_similarity=clamp(self.jaccard_similarity),
            entity_evidence=clamp(self.entity_evidence),
            relation_evidence=clamp(self.relation_evidence),
            recency=clamp(self.recency),
            evidence=dict(self.evidence),
        )


@dataclass(frozen=True, slots=True)
class RerankResult:
    score: float
    breakdown: ScoreBreakdown

    def to_dict(self) -> dict[str, float | dict[str, float]]:
        return {
            "score": round(self.score, 4),
            "score_breakdown": self.breakdown.to_dict(),
        }


def build_breakdown(
    signals: CandidateSignals,
    *,
    weights: ScoreWeights | None = None,
) -> ScoreBreakdown:
    normalized_signals = signals.normalized()
    normalized_weights = (weights or ScoreWeights()).normalized()

    contributions = {
        "embedding": normalized_signals.embedding_similarity
        * normalized_weights.embedding,
        "lexical": normalized_signals.lexical_overlap * normalized_weights.lexical,
        "jaccard": normalized_signals.jaccard_similarity * normalized_weights.jaccard,
        "entity": normalized_signals.entity_evidence * normalized_weights.entity,
        "relation": normalized_signals.relation_evidence * normalized_weights.relation,
        "recency": normalized_signals.recency * normalized_weights.recency,
    }

    raw_score = (
        normalized_signals.embedding_similarity
        + normalized_signals.lexical_overlap
        + normalized_signals.jaccard_similarity
        + normalized_signals.entity_evidence
        + normalized_signals.relation_evidence
        + normalized_signals.recency
    ) / 6.0

    weighted_score = sum(contributions.values())
    contribution_total = sum(contributions.values())
    normalized_contributions = (
        {
            key: clamp(safe_divide(value, contribution_total))
            for key, value in contributions.items()
        }
        if contribution_total > 0
        else {
            "embedding": 0.0,
            "lexical": 0.0,
            "jaccard": 0.0,
            "entity": 0.0,
            "relation": 0.0,
            "recency": 0.0,
        }
    )

    confidence = clamp((raw_score * 0.35) + (weighted_score * 0.65))
    rank_hint = clamp(
        max(
            contributions["embedding"],
            contributions["lexical"],
            contributions["entity"],
            contributions["relation"],
        )
    )

    return ScoreBreakdown(
        embedding_similarity=normalized_signals.embedding_similarity,
        lexical_overlap=normalized_signals.lexical_overlap,
        jaccard_similarity=normalized_signals.jaccard_similarity,
        entity_evidence=normalized_signals.entity_evidence,
        relation_evidence=normalized_signals.relation_evidence,
        recency=normalized_signals.recency,
        raw_score=clamp(raw_score),
        weighted_score=clamp(weighted_score),
        confidence=confidence,
        rank_hint=rank_hint,
        weights={
            "embedding": normalized_weights.embedding,
            "lexical": normalized_weights.lexical,
            "jaccard": normalized_weights.jaccard,
            "entity": normalized_weights.entity,
            "relation": normalized_weights.relation,
            "recency": normalized_weights.recency,
        },
        normalized_contributions=normalized_contributions,
        evidence=dict(normalized_signals.evidence),
    )


def rerank(
    signals: CandidateSignals,
    *,
    weights: ScoreWeights | None = None,
) -> RerankResult:
    breakdown = build_breakdown(signals, weights=weights)
    return RerankResult(
        score=breakdown.weighted_score,
        breakdown=breakdown,
    )


def naive_signals(
    *,
    embedding_similarity_value: float,
    lexical_overlap_value: float,
    jaccard_similarity_value: float = 0.0,
    recency_value: float = 0.0,
    query_token_count: int = 0,
    overlap_token_count: int = 0,
    candidate_token_count: int = 0,
) -> CandidateSignals:
    return CandidateSignals(
        embedding_similarity=embedding_similarity_value,
        lexical_overlap=lexical_overlap_value,
        jaccard_similarity=jaccard_similarity_value,
        recency=recency_value,
        evidence={
            "query_token_count": query_token_count,
            "overlap_token_count": overlap_token_count,
            "candidate_token_count": candidate_token_count,
            "profile": "naive",
        },
    )


def hybrid_signals(
    *,
    embedding_similarity_value: float,
    lexical_overlap_value: float,
    entity_evidence_count: int,
    relation_evidence_count: int,
    jaccard_similarity_value: float = 0.0,
    recency_value: float = 0.0,
    max_entity_count: int = 5,
    max_relation_count: int = 5,
    query_token_count: int = 0,
    overlap_token_count: int = 0,
) -> CandidateSignals:
    return CandidateSignals(
        embedding_similarity=embedding_similarity_value,
        lexical_overlap=lexical_overlap_value,
        jaccard_similarity=jaccard_similarity_value,
        entity_evidence=score_presence(
            entity_evidence_count, max_count=max_entity_count
        ),
        relation_evidence=score_presence(
            relation_evidence_count,
            max_count=max_relation_count,
        ),
        recency=recency_value,
        evidence={
            "entity_evidence_count": entity_evidence_count,
            "relation_evidence_count": relation_evidence_count,
            "query_token_count": query_token_count,
            "overlap_token_count": overlap_token_count,
            "profile": "hybrid",
        },
    )


def balanced_weights() -> ScoreWeights:
    return ScoreWeights(
        embedding=0.45,
        lexical=0.25,
        jaccard=0.08,
        entity=0.08,
        relation=0.10,
        recency=0.04,
    ).normalized()


def graph_heavy_weights() -> ScoreWeights:
    return ScoreWeights(
        embedding=0.30,
        lexical=0.15,
        jaccard=0.05,
        entity=0.15,
        relation=0.25,
        recency=0.10,
    ).normalized()


def lexical_heavy_weights() -> ScoreWeights:
    return ScoreWeights(
        embedding=0.28,
        lexical=0.40,
        jaccard=0.12,
        entity=0.08,
        relation=0.08,
        recency=0.04,
    ).normalized()


__all__ = [
    "CandidateSignals",
    "RerankResult",
    "ScoreBreakdown",
    "ScoreWeights",
    "balanced_weights",
    "build_breakdown",
    "clamp",
    "cosine_similarity",
    "graph_heavy_weights",
    "hybrid_signals",
    "jaccard_similarity",
    "lexical_heavy_weights",
    "lexical_overlap",
    "naive_signals",
    "normalize_recency_rank",
    "rerank",
    "safe_divide",
    "score_presence",
]

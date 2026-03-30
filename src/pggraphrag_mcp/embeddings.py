from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot produce embeddings."""


@dataclass(slots=True, frozen=True)
class EmbeddingRequest:
    """Normalized request sent to an embedding provider."""

    text: str
    input_type: str = "document"


@dataclass(slots=True, frozen=True)
class EmbeddingVector:
    """Embedding result with provider metadata."""

    values: list[float]
    provider: str
    model: str
    dimensions: int

    def to_list(self) -> list[float]:
        return list(self.values)


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers used by ingestion and retrieval flows."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed_text(
        self, text: str, *, input_type: str = "document"
    ) -> EmbeddingVector: ...

    def embed_many(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[EmbeddingVector]: ...


def normalize_embedding_input(text: str) -> str:
    """
    Normalize text before embedding.

    This intentionally stays simple and deterministic so the same logical input
    always maps to the same embedding in placeholder mode.
    """
    normalized = " ".join(text.strip().split())
    if not normalized:
        raise EmbeddingProviderError("Embedding input must not be empty.")
    return normalized


class DeterministicEmbeddingProvider:
    """
    Deterministic placeholder embedding provider.

    This provider is useful for:
    - local development
    - tests
    - smoke scenarios
    - environments where a real embedding API is not yet configured

    It generates stable vectors from a SHA-256 digest so the same input always
    yields the same embedding for a given model and dimension count.
    """

    def __init__(
        self,
        *,
        provider_name: str = "deterministic",
        model_name: str = "deterministic-placeholder-v1",
        dimensions: int = 1536,
    ) -> None:
        if dimensions <= 0:
            raise EmbeddingProviderError(
                "Embedding dimensions must be greater than zero."
            )

        self._provider_name = provider_name
        self._model_name = model_name
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_text(self, text: str, *, input_type: str = "document") -> EmbeddingVector:
        request = EmbeddingRequest(
            text=normalize_embedding_input(text),
            input_type=input_type,
        )
        values = self._vector_from_request(request)
        return EmbeddingVector(
            values=values,
            provider=self.provider_name,
            model=self.model_name,
            dimensions=self.dimensions,
        )

    def embed_many(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[EmbeddingVector]:
        return [self.embed_text(text, input_type=input_type) for text in texts]

    def _vector_from_request(self, request: EmbeddingRequest) -> list[float]:
        seed = f"{self.provider_name}|{self.model_name}|{request.input_type}|{request.text}"
        vector: list[float] = []

        counter = 0
        while len(vector) < self.dimensions:
            digest = hashlib.sha256(f"{seed}|{counter}".encode("utf-8")).digest()
            counter += 1

            for offset in range(0, len(digest), 4):
                chunk = digest[offset : offset + 4]
                if len(chunk) < 4:
                    continue

                integer = int.from_bytes(chunk, byteorder="big", signed=False)
                value = (integer / 4294967295.0) * 2.0 - 1.0
                vector.append(value)

                if len(vector) >= self.dimensions:
                    break

        return self._l2_normalize(vector)

    @staticmethod
    def _l2_normalize(values: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return [0.0 for _ in values]
        return [value / norm for value in values]


class OpenAICompatiblePlaceholderProvider(DeterministicEmbeddingProvider):
    """
    OpenAI-compatible placeholder provider.

    This class deliberately does not call an external API. Instead, it provides a
    drop-in shape compatible with an eventual OpenAI-backed implementation while
    remaining deterministic for local use.

    Use this when:
    - config says provider is `openai`
    - an API key is not available yet
    - you still want stable ingestion/retrieval behavior in dev and test
    """

    def __init__(
        self,
        *,
        model_name: str = "text-embedding-3-small",
        dimensions: int = 1536,
    ) -> None:
        super().__init__(
            provider_name="openai",
            model_name=model_name,
            dimensions=dimensions,
        )


def create_embedding_provider(
    *,
    provider_name: str,
    model_name: str,
    dimensions: int,
) -> EmbeddingProvider:
    """
    Factory for constructing the configured embedding provider.

    Supported providers:
    - `deterministic`
    - `openai` (placeholder, deterministic local implementation)
    """
    normalized_provider = provider_name.strip().lower()

    if normalized_provider == "deterministic":
        return DeterministicEmbeddingProvider(
            provider_name="deterministic",
            model_name=model_name or "deterministic-placeholder-v1",
            dimensions=dimensions,
        )

    if normalized_provider == "openai":
        return OpenAICompatiblePlaceholderProvider(
            model_name=model_name or "text-embedding-3-small",
            dimensions=dimensions,
        )

    raise EmbeddingProviderError(f"Unsupported embedding provider: {provider_name!r}")

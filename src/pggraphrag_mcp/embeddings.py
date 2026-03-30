from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot produce embeddings."""


class EmbeddingConfigurationError(EmbeddingProviderError):
    """Raised when provider configuration is invalid."""


class EmbeddingRemoteCallError(EmbeddingProviderError):
    """Raised when a remote provider call fails."""


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """Retry configuration for transient embedding failures."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.25
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 2.0
    retryable_exceptions: tuple[type[BaseException], ...] = (
        TimeoutError,
        ConnectionError,
    )

    def validate(self) -> None:
        if self.max_attempts < 1:
            raise EmbeddingConfigurationError("RetryPolicy.max_attempts must be >= 1.")
        if self.initial_delay_seconds < 0:
            raise EmbeddingConfigurationError(
                "RetryPolicy.initial_delay_seconds must be >= 0."
            )
        if self.backoff_multiplier < 1:
            raise EmbeddingConfigurationError(
                "RetryPolicy.backoff_multiplier must be >= 1."
            )
        if self.max_delay_seconds < 0:
            raise EmbeddingConfigurationError(
                "RetryPolicy.max_delay_seconds must be >= 0."
            )


@dataclass(slots=True, frozen=True)
class RemoteCallPolicy:
    """HTTP configuration for remote embedding providers."""

    timeout_seconds: float = 15.0
    endpoint_url: str = "https://api.openai.com/v1/embeddings"
    extra_headers: tuple[tuple[str, str], ...] = ()

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise EmbeddingConfigurationError(
                "RemoteCallPolicy.timeout_seconds must be > 0."
            )
        if not self.endpoint_url.strip():
            raise EmbeddingConfigurationError(
                "RemoteCallPolicy.endpoint_url must not be empty."
            )


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
    mode: str = "local"

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

    This intentionally stays simple and deterministic so equivalent logical input
    maps to the same embedding in local and test modes.
    """
    normalized = " ".join(text.strip().split())
    if not normalized:
        raise EmbeddingProviderError("Embedding input must not be empty.")
    return normalized


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def _vector_from_seed(seed: str, dimensions: int) -> list[float]:
    vector: list[float] = []
    counter = 0

    while len(vector) < dimensions:
        digest = hashlib.sha256(f"{seed}|{counter}".encode("utf-8")).digest()
        counter += 1

        for offset in range(0, len(digest), 4):
            chunk = digest[offset : offset + 4]
            if len(chunk) < 4:
                continue

            integer = int.from_bytes(chunk, byteorder="big", signed=False)
            value = (integer / 4294967295.0) * 2.0 - 1.0
            vector.append(value)

            if len(vector) >= dimensions:
                break

    return _l2_normalize(vector)


class BaseEmbeddingProvider:
    """Common provider behavior including retry handling."""

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if dimensions <= 0:
            raise EmbeddingConfigurationError(
                "Embedding dimensions must be greater than zero."
            )

        self._provider_name = provider_name
        self._model_name = model_name
        self._dimensions = dimensions
        self._retry_policy = retry_policy or RetryPolicy()
        self._retry_policy.validate()

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    def embed_text(self, text: str, *, input_type: str = "document") -> EmbeddingVector:
        request = EmbeddingRequest(
            text=normalize_embedding_input(text),
            input_type=input_type,
        )
        return self._execute_with_retry(request)

    def embed_many(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[EmbeddingVector]:
        return [self.embed_text(text, input_type=input_type) for text in texts]

    def _execute_with_retry(self, request: EmbeddingRequest) -> EmbeddingVector:
        delay = self.retry_policy.initial_delay_seconds
        last_error: BaseException | None = None

        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                return self._embed_request(request)
            except self.retry_policy.retryable_exceptions as exc:
                last_error = exc
                if attempt >= self.retry_policy.max_attempts:
                    break
                if delay > 0:
                    time.sleep(delay)
                delay = min(
                    max(delay * self.retry_policy.backoff_multiplier, delay),
                    self.retry_policy.max_delay_seconds,
                )
            except BaseException as exc:
                raise EmbeddingProviderError(
                    f"{self.provider_name} provider failed: {exc}"
                ) from exc

        raise EmbeddingProviderError(
            f"{self.provider_name} provider exhausted retries."
        ) from last_error

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        raise NotImplementedError


class DeterministicEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic provider for local development, tests, and fallback behavior.
    """

    def __init__(
        self,
        *,
        provider_name: str = "deterministic",
        model_name: str = "deterministic-placeholder-v1",
        dimensions: int = 1536,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        super().__init__(
            provider_name=provider_name,
            model_name=model_name,
            dimensions=dimensions,
            retry_policy=retry_policy,
        )

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        seed = (
            f"{self.provider_name}|{self.model_name}|"
            f"{request.input_type}|{request.text}"
        )
        values = _vector_from_seed(seed, self.dimensions)
        return EmbeddingVector(
            values=values,
            provider=self.provider_name,
            model=self.model_name,
            dimensions=self.dimensions,
            mode="local",
        )


class OpenAILocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    OpenAI local mode.

    This provider does not call the remote OpenAI API. Instead it offers an
    OpenAI-compatible local behavior using deterministic embeddings while still
    validating configuration such as the API key requirement when strict mode is
    enabled.
    """

    def __init__(
        self,
        *,
        model_name: str = "text-embedding-3-small",
        dimensions: int = 1536,
        api_key: str | None = None,
        require_api_key: bool = False,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._require_api_key = require_api_key

        if self._require_api_key and not self._api_key:
            raise EmbeddingConfigurationError(
                "OPENAI_API_KEY is required when require_api_key=True."
            )

        super().__init__(
            provider_name="openai",
            model_name=model_name,
            dimensions=dimensions,
            retry_policy=retry_policy,
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        mode = "local-openai-compatible"
        key_marker = "configured" if self.has_api_key else "missing"
        seed = (
            f"{self.provider_name}|{self.model_name}|{mode}|{key_marker}|"
            f"{request.input_type}|{request.text}"
        )
        values = _vector_from_seed(seed, self.dimensions)
        return EmbeddingVector(
            values=values,
            provider=self.provider_name,
            model=self.model_name,
            dimensions=self.dimensions,
            mode="local",
        )


class OpenAIRemoteEmbeddingProvider(BaseEmbeddingProvider):
    """
    Real OpenAI-backed embedding provider.

    This provider calls the OpenAI embeddings endpoint directly. It is intended to
    be used only when an API key is available and remote mode is explicitly enabled.
    """

    def __init__(
        self,
        *,
        model_name: str = "text-embedding-3-small",
        dimensions: int = 1536,
        api_key: str | None = None,
        retry_policy: RetryPolicy | None = None,
        remote_call_policy: RemoteCallPolicy | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        if not self._api_key:
            raise EmbeddingConfigurationError(
                "OPENAI_API_KEY is required for remote OpenAI embeddings."
            )

        self._remote_call_policy = remote_call_policy or RemoteCallPolicy()
        self._remote_call_policy.validate()
        self._client_factory = client_factory or httpx.Client

        super().__init__(
            provider_name="openai",
            model_name=model_name,
            dimensions=dimensions,
            retry_policy=retry_policy,
        )

    @property
    def remote_call_policy(self) -> RemoteCallPolicy:
        return self._remote_call_policy

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        for key, value in self.remote_call_policy.extra_headers:
            headers[key] = value

        payload = {
            "input": request.text,
            "model": self.model_name,
            "dimensions": self.dimensions,
        }

        try:
            with self._client_factory(
                timeout=self.remote_call_policy.timeout_seconds
            ) as client:
                response = client.post(
                    self.remote_call_policy.endpoint_url,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError("OpenAI embedding request timed out.") from exc
        except httpx.ConnectError as exc:
            raise ConnectionError("OpenAI embedding connection failed.") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingRemoteCallError(
                f"OpenAI embedding request failed before response: {exc}"
            ) from exc

        if response.status_code == 429:
            raise ConnectionError("OpenAI embedding rate limited.")
        if response.status_code >= 500:
            raise ConnectionError(
                f"OpenAI embedding server error: {response.status_code}"
            )
        if response.status_code >= 400:
            raise EmbeddingRemoteCallError(
                f"OpenAI embedding request rejected: {response.status_code} {response.text}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise EmbeddingRemoteCallError(
                "OpenAI embedding response was not valid JSON."
            ) from exc

        values = self._extract_embedding_values(body)
        if self.dimensions and len(values) != self.dimensions:
            raise EmbeddingRemoteCallError(
                f"OpenAI embedding dimensions mismatch: expected {self.dimensions}, got {len(values)}."
            )

        return EmbeddingVector(
            values=values,
            provider=self.provider_name,
            model=self.model_name,
            dimensions=self.dimensions,
            mode="remote",
        )

    def _extract_embedding_values(self, body: dict[str, Any]) -> list[float]:
        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingRemoteCallError("OpenAI embedding response missing data.")
        first = data[0]
        if not isinstance(first, dict):
            raise EmbeddingRemoteCallError("OpenAI embedding data entry was invalid.")
        embedding = first.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingRemoteCallError(
                "OpenAI embedding response missing embedding vector."
            )

        values: list[float] = []
        for item in embedding:
            try:
                values.append(float(item))
            except (TypeError, ValueError) as exc:
                raise EmbeddingRemoteCallError(
                    "OpenAI embedding vector contained a non-numeric value."
                ) from exc
        return values


class FallbackEmbeddingProvider(BaseEmbeddingProvider):
    """
    Wrapper provider that prefers a primary provider and falls back to a secondary
    provider when the primary path fails at runtime.
    """

    def __init__(
        self,
        *,
        primary_provider: EmbeddingProvider,
        fallback_provider: EmbeddingProvider,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._primary_provider = primary_provider
        self._fallback_provider = fallback_provider
        super().__init__(
            provider_name=primary_provider.provider_name,
            model_name=primary_provider.model_name,
            dimensions=primary_provider.dimensions,
            retry_policy=retry_policy,
        )

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        try:
            return self._primary_provider.embed_text(
                request.text,
                input_type=request.input_type,
            )
        except EmbeddingProviderError:
            return self._fallback_provider.embed_text(
                request.text,
                input_type=request.input_type,
            )


def create_embedding_provider(
    *,
    provider_name: str,
    model_name: str,
    dimensions: int,
    retry_policy: RetryPolicy | None = None,
    openai_api_key: str | None = None,
    openai_local_mode: bool = True,
    require_api_key: bool = False,
    remote_call_policy: RemoteCallPolicy | None = None,
    client_factory: Any | None = None,
) -> EmbeddingProvider:
    """
    Factory for constructing the configured embedding provider.

    Supported providers:
    - `deterministic`
    - `openai`

    For `openai`:
    - local mode uses deterministic OpenAI-compatible embeddings
    - remote mode calls the OpenAI embeddings API directly
    - remote mode falls back to local mode if the remote path fails at runtime
    """
    normalized_provider = provider_name.strip().lower()

    if normalized_provider == "deterministic":
        return DeterministicEmbeddingProvider(
            provider_name="deterministic",
            model_name=model_name or "deterministic-placeholder-v1",
            dimensions=dimensions,
            retry_policy=retry_policy,
        )

    if normalized_provider == "openai":
        local_provider = OpenAILocalEmbeddingProvider(
            model_name=model_name or "text-embedding-3-small",
            dimensions=dimensions,
            api_key=openai_api_key or os.getenv("OPENAI_API_KEY"),
            require_api_key=require_api_key and openai_local_mode,
            retry_policy=retry_policy,
        )

        if openai_local_mode:
            return local_provider

        remote_provider = OpenAIRemoteEmbeddingProvider(
            model_name=model_name or "text-embedding-3-small",
            dimensions=dimensions,
            api_key=openai_api_key or os.getenv("OPENAI_API_KEY"),
            retry_policy=retry_policy,
            remote_call_policy=remote_call_policy,
            client_factory=client_factory,
        )

        return FallbackEmbeddingProvider(
            primary_provider=remote_provider,
            fallback_provider=local_provider,
            retry_policy=retry_policy,
        )

    raise EmbeddingConfigurationError(
        f"Unsupported embedding provider: {provider_name!r}"
    )


__all__ = [
    "BaseEmbeddingProvider",
    "DeterministicEmbeddingProvider",
    "EmbeddingConfigurationError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingRemoteCallError",
    "EmbeddingRequest",
    "EmbeddingVector",
    "FallbackEmbeddingProvider",
    "OpenAILocalEmbeddingProvider",
    "OpenAIRemoteEmbeddingProvider",
    "RemoteCallPolicy",
    "RetryPolicy",
    "create_embedding_provider",
    "normalize_embedding_input",
]

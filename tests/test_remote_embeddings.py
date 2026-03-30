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

from pggraphrag_mcp.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingVector,
    OpenAILocalEmbeddingProvider,
    RetryPolicy,
    create_embedding_provider,
)


class FlakyDeterministicProvider(DeterministicEmbeddingProvider):
    def __init__(
        self,
        *,
        failures_before_success: int,
        retry_policy: RetryPolicy | None = None,
        dimensions: int = 8,
    ) -> None:
        super().__init__(
            provider_name="deterministic",
            model_name="deterministic-flaky-test",
            dimensions=dimensions,
            retry_policy=retry_policy,
        )
        self.failures_before_success = failures_before_success
        self.attempts = 0

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        self.attempts += 1
        if self.attempts <= self.failures_before_success:
            raise TimeoutError("simulated transient timeout")
        return super()._embed_request(request)


class AlwaysFailingProvider(DeterministicEmbeddingProvider):
    def __init__(
        self,
        *,
        retry_policy: RetryPolicy | None = None,
        dimensions: int = 8,
    ) -> None:
        super().__init__(
            provider_name="deterministic",
            model_name="deterministic-always-fail-test",
            dimensions=dimensions,
            retry_policy=retry_policy,
        )
        self.attempts = 0

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        self.attempts += 1
        raise TimeoutError("always failing timeout")


class NonRetryableFailingProvider(DeterministicEmbeddingProvider):
    def __init__(
        self,
        *,
        retry_policy: RetryPolicy | None = None,
        dimensions: int = 8,
    ) -> None:
        super().__init__(
            provider_name="deterministic",
            model_name="deterministic-non-retryable-test",
            dimensions=dimensions,
            retry_policy=retry_policy,
        )
        self.attempts = 0

    def _embed_request(self, request: EmbeddingRequest) -> EmbeddingVector:
        self.attempts += 1
        raise RuntimeError("non-retryable failure")


def test_openai_local_provider_without_api_key_still_embeds() -> None:
    provider = OpenAILocalEmbeddingProvider(
        model_name="text-embedding-3-small",
        dimensions=16,
        api_key=None,
        require_api_key=False,
    )

    vector = provider.embed_text("GraphRAG source trace", input_type="document")

    assert provider.provider_name == "openai"
    assert provider.model_name == "text-embedding-3-small"
    assert provider.has_api_key is False
    assert vector.provider == "openai"
    assert vector.model == "text-embedding-3-small"
    assert vector.dimensions == 16
    assert len(vector.values) == 16


def test_openai_local_provider_with_api_key_changes_seed_but_remains_stable() -> None:
    provider = OpenAILocalEmbeddingProvider(
        model_name="text-embedding-3-small",
        dimensions=12,
        api_key="test-openai-key",
        require_api_key=False,
    )

    first = provider.embed_text("GraphRAG retrieval", input_type="query")
    second = provider.embed_text("GraphRAG retrieval", input_type="query")

    assert provider.has_api_key is True
    assert first.values == second.values
    assert len(first.values) == 12


def test_openai_local_provider_requires_api_key_when_strict_mode_enabled() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="OPENAI_API_KEY is required"):
        OpenAILocalEmbeddingProvider(
            model_name="text-embedding-3-small",
            dimensions=8,
            api_key=None,
            require_api_key=True,
        )


def test_create_embedding_provider_returns_openai_local_mode_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = create_embedding_provider(
        provider_name="openai",
        model_name="text-embedding-3-small",
        dimensions=8,
    )

    assert provider.provider_name == "openai"
    assert provider.model_name == "text-embedding-3-small"
    assert provider.dimensions == 8


def test_create_embedding_provider_uses_environment_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")

    provider = create_embedding_provider(
        provider_name="openai",
        model_name="text-embedding-3-small",
        dimensions=8,
        require_api_key=True,
    )

    vector = provider.embed_text("GraphRAG hybrid retrieval")

    assert provider.provider_name == "openai"
    assert provider.model_name == "text-embedding-3-small"
    assert len(vector.values) == 8


def test_create_embedding_provider_requires_api_key_for_remote_openai_mode() -> None:
    with pytest.raises(
        EmbeddingConfigurationError,
        match="OPENAI_API_KEY is required for remote OpenAI embeddings",
    ):
        create_embedding_provider(
            provider_name="openai",
            model_name="text-embedding-3-small",
            dimensions=8,
            openai_local_mode=False,
        )


def test_retry_policy_eventually_succeeds_after_transient_failures() -> None:
    provider = FlakyDeterministicProvider(
        failures_before_success=2,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.0,
            backoff_multiplier=1.0,
            max_delay_seconds=0.0,
        ),
        dimensions=8,
    )

    vector = provider.embed_text("retryable deterministic embedding")

    assert provider.attempts == 3
    assert vector.provider == "deterministic"
    assert len(vector.values) == 8


def test_retry_policy_raises_after_exhausting_retries() -> None:
    provider = AlwaysFailingProvider(
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.0,
            backoff_multiplier=1.0,
            max_delay_seconds=0.0,
        ),
        dimensions=8,
    )

    with pytest.raises(EmbeddingProviderError, match="exhausted retries"):
        provider.embed_text("this will never succeed")

    assert provider.attempts == 3


def test_non_retryable_error_does_not_retry() -> None:
    provider = NonRetryableFailingProvider(
        retry_policy=RetryPolicy(
            max_attempts=5,
            initial_delay_seconds=0.0,
            backoff_multiplier=1.0,
            max_delay_seconds=0.0,
        ),
        dimensions=8,
    )

    with pytest.raises(EmbeddingProviderError, match="provider failed"):
        provider.embed_text("non retryable failure path")

    assert provider.attempts == 1


def test_retry_policy_validates_invalid_configuration() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="max_attempts"):
        RetryPolicy(max_attempts=0).validate()

    with pytest.raises(EmbeddingConfigurationError, match="initial_delay_seconds"):
        RetryPolicy(initial_delay_seconds=-1.0).validate()

    with pytest.raises(EmbeddingConfigurationError, match="backoff_multiplier"):
        RetryPolicy(backoff_multiplier=0.5).validate()

    with pytest.raises(EmbeddingConfigurationError, match="max_delay_seconds"):
        RetryPolicy(max_delay_seconds=-1.0).validate()

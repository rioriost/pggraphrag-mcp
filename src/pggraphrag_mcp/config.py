from __future__ import annotations

from functools import cached_property
from typing import Literal

from pydantic import AnyHttpUrl, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PGGRAPHRAG_MCP_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "pggraphrag-mcp"
    app_version: str = "0.1.0"
    env: Literal["local", "development", "test", "staging", "production"] = "local"

    http_host: str = "0.0.0.0"
    http_port: int = 8080
    http_path: str = "/mcp"
    public_base_url: AnyHttpUrl = "https://localhost:8443"
    enable_debug_endpoints: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    small_auth_token: str = Field(
        default="change-me-local-token",
        description="Shared bearer token validated by the auth gateway.",
    )
    auth_header_name: str = "X-Authenticated-Identity"
    auth_identity: str = "local-client"

    db_name: str = "pggraphrag"
    db_user: str = "pggraphrag_app"
    db_password: str = "change-me-db-password"
    db_host: str = "pggraphrag-db"
    db_port: int = 5432
    database_url: str = "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag"
    database_migration_url: str | None = None
    age_graph_name: str = "pggraphrag_memory"

    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    max_vector_candidates: int = 30
    max_graph_hops: int = 2
    max_return_chunks: int = 12
    max_return_entities: int = 20

    tls_cert_file: str = "/certs/dev.crt"
    tls_key_file: str = "/certs/dev.key"

    private_image: str = "pggraphrag-mcp-private:local"
    auth_image: str = "pggraphrag-mcp-auth:local"
    db_image: str = "pggraphrag-db:local"

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @computed_field
    @property
    def database_host_port(self) -> str:
        return f"{self.db_host}:{self.db_port}"

    @computed_field
    @property
    def mcp_url(self) -> str:
        base = str(self.public_base_url).rstrip("/")
        path = (
            self.http_path if self.http_path.startswith("/") else f"/{self.http_path}"
        )
        return f"{base}{path}"

    @cached_property
    def redacted_database_url(self) -> str:
        if "://" not in self.database_url or "@" not in self.database_url:
            return self.database_url

        scheme, remainder = self.database_url.split("://", 1)
        credentials, host_part = remainder.split("@", 1)

        if ":" not in credentials:
            return f"{scheme}://***@{host_part}"

        username, _password = credentials.split(":", 1)
        return f"{scheme}://{username}:***@{host_part}"

    @classmethod
    def load(cls) -> "AppConfig":
        """Create a configuration instance from the current environment."""
        return cls()

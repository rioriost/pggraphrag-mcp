from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI, Header, Response


@dataclass(frozen=True, slots=True)
class AuthSettings:
    expected_bearer_token: str
    auth_user: str
    auth_mode: str
    health_path: str
    verify_path: str
    auth_user_header: str
    auth_mode_header: str


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip()
    return normalized if normalized else default


def load_settings() -> AuthSettings:
    expected_bearer_token = _get_env("PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN")
    if expected_bearer_token is None:
        raise RuntimeError("PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN is required")

    return AuthSettings(
        expected_bearer_token=expected_bearer_token,
        auth_user=_get_env("PGGRAPHRAG_MCP_AUTH_IDENTITY", "local-dev") or "local-dev",
        auth_mode=_get_env("PGGRAPHRAG_MCP_AUTH_MODE", "static-token")
        or "static-token",
        health_path=_get_env("PGGRAPHRAG_MCP_AUTH_HEALTH_PATH", "/healthz")
        or "/healthz",
        verify_path=_get_env("PGGRAPHRAG_MCP_AUTH_PATH", "/auth/verify")
        or "/auth/verify",
        auth_user_header=_get_env("PGGRAPHRAG_MCP_AUTH_USER_HEADER", "X-Auth-User")
        or "X-Auth-User",
        auth_mode_header=_get_env("PGGRAPHRAG_MCP_AUTH_MODE_HEADER", "X-Auth-Mode")
        or "X-Auth-Mode",
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None

    normalized = authorization.strip()
    if not normalized:
        return None

    scheme, separator, token = normalized.partition(" ")
    if separator == "" or scheme.lower() != "bearer":
        return None

    token = token.strip()
    return token or None


def create_app(settings: AuthSettings | None = None) -> FastAPI:
    resolved_settings = settings or load_settings()
    app = FastAPI(title="pggraphrag-mcp-auth", version="0.1.0")

    @app.get(resolved_settings.health_path)
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route(
        resolved_settings.verify_path,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    def verify(
        response: Response,
        x_forwarded_uri: str | None = Header(default=None),
        x_forwarded_method: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        presented_token = _extract_bearer_token(authorization)
        if presented_token is None:
            response.status_code = 401
            response.headers["www-authenticate"] = 'Bearer realm="pggraphrag-mcp-proxy"'
            return {
                "error": "missing_bearer_token",
                "message": "Authorization header must contain a bearer token",
            }

        if presented_token != resolved_settings.expected_bearer_token:
            response.status_code = 401
            response.headers["www-authenticate"] = 'Bearer realm="pggraphrag-mcp-proxy"'
            return {
                "error": "invalid_bearer_token",
                "message": "Bearer token is invalid",
            }

        response.headers[resolved_settings.auth_user_header] = (
            resolved_settings.auth_user
        )
        response.headers[resolved_settings.auth_mode_header] = (
            resolved_settings.auth_mode
        )
        response.headers["X-Authenticated-Identity"] = resolved_settings.auth_user

        if x_forwarded_uri:
            response.headers["X-Forwarded-Authenticated-Uri"] = x_forwarded_uri
        if x_forwarded_method:
            response.headers["X-Forwarded-Authenticated-Method"] = x_forwarded_method
        if x_request_id:
            response.headers["X-Request-Id"] = x_request_id

        return {
            "status": "ok",
            "user": resolved_settings.auth_user,
            "mode": resolved_settings.auth_mode,
        }

    return app


try:
    app = create_app()
except RuntimeError:
    app = FastAPI(title="pggraphrag-mcp-auth", version="0.1.0")

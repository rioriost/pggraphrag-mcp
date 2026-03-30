from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from pggraphrag_mcp.auth_app import AuthSettings
from pggraphrag_mcp.auth_app import create_app as create_auth_app
from pggraphrag_mcp.config import AppConfig
from pggraphrag_mcp.db import DatabaseStatus
from pggraphrag_mcp.graphrag_service import GraphRAGValidationError
from pggraphrag_mcp.http_app import create_app as create_http_app
from pggraphrag_mcp.http_app import normalize_tool_params
from scripts.mcp_http_smoke import (
    auth_headers,
    build_mcp_url,
    check_authorized_health,
    check_minimal_tool_invocation,
    check_unauthorized_access,
    health_check_request,
    minimal_mcp_request,
    minimal_tool_request,
    normalize_path,
    parse_json_response,
    summarize_response,
)


class DummyDatabase:
    def __init__(self, status: DatabaseStatus | None = None) -> None:
        self._status = status or DatabaseStatus(
            database="pggraphrag",
            current_user="pggraphrag_app",
            vector_extension_installed=True,
            age_extension_installed=True,
            age_graph_exists=True,
            schema_version_table_exists=True,
            document_table_exists=True,
            chunk_table_exists=True,
            entity_table_exists=True,
            relation_fact_table_exists=True,
            chunk_entity_table_exists=True,
            ingestion_job_table_exists=True,
            retrieval_log_table_exists=True,
            graph_refresh_log_table_exists=True,
            document_content_column_exists=True,
        )
        self.bootstrap_calls = 0

    def bootstrap(self) -> None:
        self.bootstrap_calls += 1

    def get_status(self) -> DatabaseStatus:
        return self._status


class DummyGraphRAGService:
    def document_ingest(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "document_ingest",
            "status": "accepted",
            "document": {
                "document_id": "11111111-1111-1111-1111-111111111111",
                "source_uri": command.source_uri,
                "title": command.title,
            },
            "chunk_count": 1,
            "entity_count": 1,
            "relation_count": 0,
        }

    def document_reingest(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "document_reingest",
            "status": "accepted",
            "document": {
                "document_id": "11111111-1111-1111-1111-111111111111",
                "source_uri": command.source_uri,
                "title": command.title,
            },
            "chunk_count": 1,
            "entity_count": 1,
            "relation_count": 0,
        }

    def document_delete(self, *, document_id: str) -> dict[str, Any]:
        return {
            "workflow": "document_delete",
            "deleted": True,
            "document_id": document_id,
        }

    def graph_refresh(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "graph_refresh",
            "graph_name": "pggraphrag_memory",
            "full_rebuild": command.full_rebuild,
            "document_scope": str(command.document_id)
            if command.document_id
            else "all",
        }

    def retrieve_naive(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "retrieve_naive",
            "retrieval_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "mode": "naive",
            "summary": f"naive result for {command.query}",
            "supporting_chunks": [],
            "entities": [],
            "relationships": [],
            "sources": [],
            "confidence": 0.5,
            "timings": {"elapsed_ms": 1.0},
        }

    def entity_search(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "entity_search",
            "query": command.query,
            "results": [],
            "elapsed_ms": 1.0,
        }

    def entity_expand(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "entity_expand",
            "root_entity": {"entity_id": str(command.entity_id)},
            "entities": [],
            "relationships": [],
            "sources": [],
            "hops": command.hops,
            "elapsed_ms": 1.0,
        }

    def retrieve_local_graph(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "retrieve_local_graph",
            "retrieval_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "mode": "local_graph",
            "summary": f"local graph result for {command.query}",
            "supporting_chunks": [],
            "entities": [],
            "relationships": [],
            "sources": [],
            "confidence": 0.6,
            "timings": {"elapsed_ms": 1.0},
        }

    def retrieve_hybrid(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "retrieve_hybrid",
            "retrieval_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "mode": "hybrid",
            "summary": f"hybrid result for {command.query}",
            "supporting_chunks": [],
            "entities": [],
            "relationships": [],
            "sources": [],
            "confidence": 0.7,
            "timings": {"elapsed_ms": 1.0},
        }

    def source_trace(self, command: Any) -> dict[str, Any]:
        return {
            "workflow": "source_trace",
            "retrieval_id": str(command.retrieval_id),
            "mode": "hybrid",
            "sources": [],
            "timings": {"elapsed_ms": 1.0},
        }


@pytest.fixture
def auth_client() -> TestClient:
    app = create_auth_app(
        AuthSettings(
            expected_bearer_token="test-token",
            auth_user="test-client",
            auth_mode="static-token",
            health_path="/healthz",
            verify_path="/auth/verify",
            auth_user_header="X-Auth-User",
            auth_mode_header="X-Auth-Mode",
        )
    )
    return TestClient(app)


@pytest.fixture
def http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, DummyDatabase, DummyGraphRAGService]:
    config = AppConfig(
        app_name="pggraphrag-mcp",
        app_version="0.1.0",
        env="test",
        http_host="127.0.0.1",
        http_port=8080,
        http_path="/mcp",
        public_base_url="https://localhost:8443",
        enable_debug_endpoints=True,
        log_level="INFO",
        small_auth_token="test-token",
        auth_header_name="X-Authenticated-Identity",
        auth_identity="test-client",
        db_name="pggraphrag",
        db_user="pggraphrag_app",
        db_password="secret",
        db_host="pggraphrag-db",
        db_port=5432,
        database_url="postgresql://pggraphrag_app:secret@pggraphrag-db:5432/pggraphrag",
        age_graph_name="pggraphrag_memory",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        max_vector_candidates=30,
        max_graph_hops=2,
        max_return_chunks=12,
        max_return_entities=20,
        tls_cert_file="/certs/dev.crt",
        tls_key_file="/certs/dev.key",
        private_image="pggraphrag-mcp-private:local",
        auth_image="pggraphrag-mcp-auth:local",
        db_image="pggraphrag-db:local",
    )
    database = DummyDatabase()
    graphrag = DummyGraphRAGService()

    monkeypatch.setattr(
        "pggraphrag_mcp.http_app.create_database", lambda _config: database
    )
    monkeypatch.setattr(
        "pggraphrag_mcp.http_app.create_graphrag_service",
        lambda _config: graphrag,
    )

    app = create_http_app(config)
    client = TestClient(app)
    return client, database, graphrag


def test_auth_health_endpoint(auth_client: TestClient) -> None:
    response = auth_client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_rejects_missing_token(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/verify")

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"] == "missing_bearer_token"
    assert "Authorization header must contain a bearer token" in payload["message"]


def test_auth_accepts_valid_token_and_propagates_headers(
    auth_client: TestClient,
) -> None:
    response = auth_client.get(
        "/auth/verify",
        headers={
            "Authorization": "Bearer test-token",
            "X-Request-Id": "req-123",
            "X-Forwarded-Uri": "/mcp",
            "X-Forwarded-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Auth-User"] == "test-client"
    assert response.headers["X-Auth-Mode"] == "static-token"
    assert response.headers["X-Authenticated-Identity"] == "test-client"
    assert response.headers["X-Forwarded-Authenticated-Uri"] == "/mcp"
    assert response.headers["X-Forwarded-Authenticated-Method"] == "POST"
    assert response.headers["X-Request-Id"] == "req-123"


def test_http_readyz_returns_database_status(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    response = client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"]["is_ready"] is True
    assert payload["age_graph_name"] == "pggraphrag_memory"


def test_http_startup_bootstraps_database(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, database, _graphrag = http_client

    with client:
        pass

    assert database.bootstrap_calls >= 1


def test_http_requires_authenticated_identity_header(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    response = client.post(
        "/mcp",
        json=health_check_request(),
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["error"]["code"] == -32001


def test_http_mcp_get_returns_tool_listing(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    response = client.get(
        "/mcp",
        headers={"X-Authenticated-Identity": "test-client"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert "health_check" in payload["result"]["tools"]
    assert "index_status" in payload["result"]["tools"]
    assert "graph_status" in payload["result"]["tools"]
    assert "document_ingest" in payload["result"]["tools"]
    assert "document_reingest" in payload["result"]["tools"]
    assert "document_delete" in payload["result"]["tools"]
    assert "graph_refresh" in payload["result"]["tools"]
    assert "rebuild_embeddings" in payload["result"]["tools"]
    assert "retrieve_naive" in payload["result"]["tools"]
    assert "entity_search" in payload["result"]["tools"]
    assert "entity_expand" in payload["result"]["tools"]
    assert "retrieve_local_graph" in payload["result"]["tools"]
    assert "retrieve_hybrid" in payload["result"]["tools"]
    assert "source_trace" in payload["result"]["tools"]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "result_key", "expected_value"),
    [
        ("health_check", {}, "database", None),
        ("index_status", {}, "embedding_provider", "openai"),
        ("graph_status", {}, "graph_name", "pggraphrag_memory"),
        (
            "document_ingest",
            {"source_uri": "memory://doc", "title": "Doc", "text": "Alpha Beta"},
            "workflow",
            "document_ingest",
        ),
        (
            "document_reingest",
            {"source_uri": "memory://doc", "title": "Doc", "text": "Alpha Beta"},
            "workflow",
            "document_reingest",
        ),
        (
            "document_delete",
            {"document_id": "00000000-0000-0000-0000-000000000001"},
            "workflow",
            "document_delete",
        ),
        ("graph_refresh", {"full_rebuild": False}, "workflow", "graph_refresh"),
        ("rebuild_embeddings", {}, "workflow", "rebuild_embeddings"),
        ("retrieve_naive", {"query": "Alpha Beta"}, "workflow", "retrieve_naive"),
        ("entity_search", {"query": "Alpha"}, "workflow", "entity_search"),
        (
            "entity_expand",
            {"entity_id": "00000000-0000-0000-0000-000000000001"},
            "workflow",
            "entity_expand",
        ),
        (
            "retrieve_local_graph",
            {"query": "Alpha Beta"},
            "workflow",
            "retrieve_local_graph",
        ),
        ("retrieve_hybrid", {"query": "Alpha Beta"}, "workflow", "retrieve_hybrid"),
        (
            "source_trace",
            {"retrieval_id": "00000000-0000-0000-0000-000000000001"},
            "workflow",
            "source_trace",
        ),
    ],
)
def test_http_supported_tools_return_jsonrpc_results(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
    tool_name: str,
    arguments: dict[str, Any],
    result_key: str,
    expected_value: Any,
) -> None:
    client, _database, _graphrag = http_client

    response = client.post(
        "/mcp",
        headers={"X-Authenticated-Identity": "test-client"},
        json={
            "jsonrpc": "2.0",
            "id": f"req-{tool_name}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == f"req-{tool_name}"
    assert result_key in payload["result"]
    if expected_value is not None:
        assert payload["result"][result_key] == expected_value


def test_http_returns_method_not_found_for_unsupported_method(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    response = client.post(
        "/mcp",
        headers={"X-Authenticated-Identity": "test-client"},
        json={
            "jsonrpc": "2.0",
            "id": "bad-method",
            "method": "tools/list",
            "params": {},
        },
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == -32601


def test_http_returns_not_found_for_unsupported_tool(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    response = client.post(
        "/mcp",
        headers={"X-Authenticated-Identity": "test-client"},
        json={
            "jsonrpc": "2.0",
            "id": "bad-tool",
            "method": "tools/call",
            "params": {
                "name": "does_not_exist",
                "arguments": {},
            },
        },
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == -32601
    assert "Unsupported tool" in payload["error"]["message"]


def test_http_debug_config_redacts_database_url(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    response = client.get("/debug/config")

    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["database_url"]
        == "postgresql://pggraphrag_app:***@pggraphrag-db:5432/pggraphrag"
    )


def test_normalize_tool_params_accepts_dict() -> None:
    params = normalize_tool_params(
        {
            "name": "health_check",
            "arguments": {"verbose": True},
        }
    )

    assert params.name == "health_check"
    assert params.arguments == {"verbose": True}


def test_normalize_tool_params_rejects_missing_name() -> None:
    with pytest.raises(ValueError, match="Tool name is required"):
        normalize_tool_params({"arguments": {}})


def test_smoke_helper_builders() -> None:
    assert normalize_path("mcp") == "/mcp"
    assert normalize_path("/mcp") == "/mcp"
    assert (
        build_mcp_url(
            type(
                "SmokeConfigLike",
                (),
                {"base_url": "https://localhost:8443", "mcp_path": "/mcp"},
            )()
        )
        == "https://localhost:8443/mcp"
    )

    headers = auth_headers("abc")
    assert headers["Authorization"] == "Bearer abc"
    assert headers["Content-Type"] == "application/json"

    assert minimal_mcp_request()["params"]["name"] == "health_check"
    assert health_check_request()["params"]["name"] == "health_check"
    assert minimal_tool_request()["params"]["name"] == "index_status"


def test_smoke_helper_parse_and_summarize_response(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client
    response = client.post(
        "/mcp",
        headers={"X-Authenticated-Identity": "test-client"},
        json=health_check_request(),
    )

    parsed = parse_json_response(response)
    summary = summarize_response(response)

    assert parsed is not None
    assert parsed["jsonrpc"] == "2.0"
    assert summary["status_code"] == 200
    assert summary["json"]["result"]["status"] == "ok"


def test_smoke_checks_against_test_client(
    http_client: tuple[TestClient, DummyDatabase, DummyGraphRAGService],
) -> None:
    client, _database, _graphrag = http_client

    unauthorized = check_unauthorized_access(client, "/mcp")
    assert unauthorized.status_code == 401

    authorized = check_authorized_health(client, "/mcp", "ignored-token")
    assert authorized.status_code == 200
    assert authorized.json()["result"]["status"] == "ok"

    tool_response = check_minimal_tool_invocation(client, "/mcp", "ignored-token")
    assert tool_response.status_code == 200
    assert tool_response.json()["result"]["embedding_provider"] == "openai"


@pytest.fixture(autouse=True)
def patch_smoke_auth_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    def _auth_headers(_bearer_token: str) -> dict[str, str]:
        return {
            "X-Authenticated-Identity": "test-client",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    monkeypatch.setattr("scripts.mcp_http_smoke.auth_headers", _auth_headers)

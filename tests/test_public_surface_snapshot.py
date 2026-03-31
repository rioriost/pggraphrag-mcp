# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from starlette.testclient import TestClient

from pggraphrag_mcp.auth_app import AuthSettings
from pggraphrag_mcp.auth_app import create_app as create_auth_app
from pggraphrag_mcp.config import AppConfig
from pggraphrag_mcp.db import DatabaseStatus
from pggraphrag_mcp.http_app import create_app as create_http_app

SNAPSHOT_PATH = PROJECT_ROOT / "schemas/mcp/public-surface.v0.1.0.json"


class DummyDatabase:
    def __init__(self) -> None:
        self._status = DatabaseStatus(
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
    def document_ingest(self, command) -> dict:
        return {
            "ingestion_job_id": "11111111-1111-1111-1111-111111111111",
            "document": {
                "document_id": "22222222-2222-2222-2222-222222222222",
                "source_uri": command.source_uri,
                "title": command.title,
            },
            "chunk_count": 1,
            "entity_count": 1,
            "relation_count": 0,
        }

    def document_reingest(self, command) -> dict:
        return self.document_ingest(command)

    def document_delete(self, *, document_id: str) -> dict:
        return {
            "document_id": document_id,
            "deleted": True,
        }

    def graph_refresh(self, command) -> dict:
        return {
            "graph_name": "pggraphrag_memory",
            "document_scope": (
                str(command.document_id) if command.document_id is not None else "all"
            ),
            "full_rebuild": command.full_rebuild,
            "projected_documents": 1,
            "projected_chunks": 1,
            "projected_entities": 1,
            "projected_relations": 0,
        }

    def retrieve_naive(self, command) -> dict:
        return {
            "retrieval_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "summary": f"naive result for {command.query}",
            "mode": "naive",
            "supporting_chunks": [],
            "entities": [],
            "relationships": [],
            "sources": [],
            "confidence": 0.5,
            "timings": {"elapsed_ms": 1.0},
        }

    def entity_search(self, command) -> dict:
        return {
            "query": command.query,
            "results": [],
            "elapsed_ms": 1.0,
        }

    def entity_expand(self, command) -> dict:
        return {
            "root_entity": {"entity_id": str(command.entity_id)},
            "entities": [],
            "relationships": [],
            "sources": [],
            "hops": command.hops,
            "elapsed_ms": 1.0,
        }

    def retrieve_local_graph(self, command) -> dict:
        return {
            "retrieval_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "summary": f"local graph result for {command.query}",
            "mode": "local_graph",
            "supporting_chunks": [],
            "entities": [],
            "relationships": [],
            "sources": [],
            "confidence": 0.6,
            "timings": {"elapsed_ms": 1.0},
        }

    def retrieve_hybrid(self, command) -> dict:
        return {
            "retrieval_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "summary": f"hybrid result for {command.query}",
            "mode": "hybrid",
            "supporting_chunks": [],
            "entities": [],
            "relationships": [],
            "sources": [],
            "confidence": 0.7,
            "timings": {"elapsed_ms": 1.0},
        }

    def source_trace(self, command) -> dict:
        return {
            "retrieval_id": str(command.retrieval_id),
            "mode": "hybrid",
            "sources": [],
            "timings": {"elapsed_ms": 1.0},
        }


def _load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _app_config() -> AppConfig:
    return AppConfig(
        app_name="pggraphrag-mcp",
        app_version="0.1.0",
        env="test",
        http_host="127.0.0.1",
        http_port=8080,
        http_path="/mcp",
        public_base_url="https://localhost:9443",
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


def _runtime_tool_listing() -> list[str]:
    app = create_http_app(_app_config())
    app.state.database = DummyDatabase()
    app.state.graphrag = DummyGraphRAGService()

    with TestClient(app) as client:
        response = client.get(
            "/mcp",
            headers={
                "X-Authenticated-Identity": "test-client",
                "X-Auth-User": "test-client",
                "X-Auth-Mode": "static-token",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    return list(payload["result"]["tools"])


def _auth_headers_from_runtime() -> list[str]:
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

    with TestClient(app) as client:
        response = client.get(
            "/auth/verify",
            headers={
                "Authorization": "Bearer test-token",
                "X-Forwarded-Uri": "/mcp",
                "X-Forwarded-Method": "POST",
                "X-Request-Id": "req-123",
            },
        )

    assert response.status_code == 200
    return sorted(
        [
            header_name
            for header_name in response.headers.keys()
            if header_name.lower().startswith("x-")
        ]
    )


def test_public_surface_snapshot_file_exists() -> None:
    assert SNAPSHOT_PATH.exists(), f"Missing snapshot file: {SNAPSHOT_PATH}"


def test_public_surface_snapshot_has_expected_top_level_shape() -> None:
    snapshot = _load_snapshot()

    assert snapshot["version"] == "0.1.0"
    assert snapshot["protocol"] == "remote-mcp-http"
    assert snapshot["http_path"] == "/mcp"
    assert isinstance(snapshot["tools"], list)
    assert isinstance(snapshot["resources"], list)


def test_public_surface_snapshot_tools_match_runtime_listing() -> None:
    snapshot = _load_snapshot()
    snapshot_tools = sorted(tool["name"] for tool in snapshot["tools"])
    runtime_tools = sorted(_runtime_tool_listing())

    assert snapshot_tools == runtime_tools


def test_public_surface_snapshot_contains_expected_frozen_tools() -> None:
    snapshot = _load_snapshot()
    tool_names = {tool["name"] for tool in snapshot["tools"]}

    expected_tools = {
        "health_check",
        "index_status",
        "graph_status",
        "document_ingest",
        "document_reingest",
        "document_delete",
        "graph_refresh",
        "retrieve_naive",
        "entity_search",
        "entity_expand",
        "retrieve_local_graph",
        "retrieve_hybrid",
        "source_trace",
    }

    assert tool_names == expected_tools


def test_public_surface_snapshot_resources_match_expected_set() -> None:
    snapshot = _load_snapshot()
    resource_uris = {resource["uri_template"] for resource in snapshot["resources"]}

    expected_resources = {
        "graphrag://document/{document_id}",
        "graphrag://chunk/{chunk_id}",
        "graphrag://entity/{entity_id}",
        "graphrag://retrieval/{retrieval_id}",
        "graphrag://graph/status",
    }

    assert resource_uris == expected_resources


def test_public_surface_snapshot_records_proxy_auth_headers() -> None:
    snapshot = _load_snapshot()
    snapshot_headers = sorted(snapshot["auth"]["forwarded_identity_headers"])
    runtime_headers = _auth_headers_from_runtime()

    assert "x-auth-user" in snapshot_headers
    assert "x-auth-mode" in snapshot_headers
    assert "x-auth-user" in runtime_headers
    assert "x-auth-mode" in runtime_headers

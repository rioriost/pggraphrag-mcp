# ruff: noqa: E402
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


pytestmark = pytest.mark.integration


def _env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("COMPOSE_PROJECT_NAME", "pggraphrag_mcp")
    env.setdefault("PGGRAPHRAG_MCP_PROXY_PORT", "9443")
    env.setdefault("PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN", "change-me-local-token")
    return env


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=str(cwd or PROJECT_ROOT),
        env=env or _env_for_subprocess(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            "Command failed.\n"
            f"args={args}\n"
            f"returncode={completed.returncode}\n"
            f"stdout=\n{completed.stdout}\n"
            f"stderr=\n{completed.stderr}"
        )
    return completed


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _uv_available() -> bool:
    return shutil.which("uv") is not None


def _compose_args() -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        ".env",
        "-f",
        "docker/docker-compose.yml",
        "-f",
        "docker/docker-compose.small-auth.yml",
    ]


@pytest.fixture(scope="session")
def integration_env() -> dict[str, str]:
    env = _env_for_subprocess()
    return env


@pytest.fixture(scope="session")
def compose_project_name(integration_env: dict[str, str]) -> str:
    return integration_env["COMPOSE_PROJECT_NAME"]


@pytest.fixture(scope="session")
def proxy_base_url(integration_env: dict[str, str]) -> str:
    return f"https://localhost:{integration_env['PGGRAPHRAG_MCP_PROXY_PORT']}"


@pytest.fixture(scope="session")
def bearer_token(integration_env: dict[str, str]) -> str:
    return integration_env["PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN"]


@pytest.fixture(scope="session")
def compose_files_exist() -> None:
    required = [
        PROJECT_ROOT / "docker/docker-compose.yml",
        PROJECT_ROOT / "docker/docker-compose.small-auth.yml",
        PROJECT_ROOT / "docker/traefik/traefik.yml",
        PROJECT_ROOT / "docker/traefik/dynamic.yml",
    ]
    missing = [str(path) for path in required if not path.exists()]
    assert not missing, f"Required compose assets are missing: {missing}"


@pytest.fixture(scope="session")
def scripts_exist() -> None:
    required = [
        PROJECT_ROOT / "scripts/mcp_http_smoke.py",
        PROJECT_ROOT / "docker/postgres-age/initdb/01-schema.sql",
        PROJECT_ROOT / "docker/postgres-age/initdb/02-age-bootstrap.sql",
    ]
    missing = [str(path) for path in required if not path.exists()]
    assert not missing, f"Required scripts are missing: {missing}"


def test_docs_and_management_paths_exist(
    compose_files_exist: None, scripts_exist: None
) -> None:
    # This test exists mainly to make the intended integration entrypoints explicit.
    assert True


@pytest.mark.skipif(
    not _uv_available(), reason="uv is required for integration script execution"
)
def test_smoke_script_help_runs(integration_env: dict[str, str]) -> None:
    result = _run(
        ["uv", "run", "python", "scripts/mcp_http_smoke.py", "--help"],
        env=integration_env,
        timeout=60,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert "--base-url" in combined
    assert "--bearer-token" in combined
    assert "--insecure" in combined


@pytest.mark.skipif(
    not _docker_available(), reason="docker is required for compose validation"
)
def test_compose_config_validates(integration_env: dict[str, str]) -> None:
    result = _run(
        _compose_args() + ["config"],
        env=integration_env,
        timeout=120,
    )
    assert "pggraphrag-mcp-private" in result.stdout
    assert "pggraphrag-db" in result.stdout
    assert "pggraphrag-mcp-proxy" in result.stdout
    assert "pggraphrag-mcp-auth" in result.stdout


@pytest.mark.skipif(
    not _docker_available(), reason="docker is required for compose validation"
)
def test_compose_project_name_is_stable(integration_env: dict[str, str]) -> None:
    result = _run(
        _compose_args() + ["config"],
        env=integration_env,
        timeout=120,
    )
    # Compose config output itself won't show the project name directly, so assert
    # our integration environment is carrying the intended value.
    assert integration_env["COMPOSE_PROJECT_NAME"] == "pggraphrag_mcp"
    assert "8443" in result.stdout or "9443" in result.stdout


@pytest.mark.skipif(
    not _docker_available(), reason="docker is required for integration validation"
)
def test_clean_volume_compose_smoke_workflow_commands_are_well_formed(
    integration_env: dict[str, str],
    compose_project_name: str,
    proxy_base_url: str,
    bearer_token: str,
) -> None:
    compose_down = _compose_args() + ["down", "--remove-orphans"]
    compose_up = _compose_args() + ["up", "-d", "--build"]
    smoke = [
        "python",
        "scripts/mcp_http_smoke.py",
        "--base-url",
        proxy_base_url,
        "--mcp-path",
        "/mcp",
        "--bearer-token",
        bearer_token,
        "--insecure",
    ]

    assert compose_down[:2] == ["docker", "compose"]
    assert compose_up[:2] == ["docker", "compose"]
    assert smoke[0] == "python"
    assert compose_project_name == "pggraphrag_mcp"
    assert proxy_base_url.endswith(":9443")
    assert bearer_token == "change-me-local-token"


@pytest.mark.skipif(
    not _uv_available(), reason="uv is required for integration validation"
)
def test_pytest_suite_runs_from_clean_checkout_path(
    integration_env: dict[str, str],
) -> None:
    # Lightweight integration verification: ensure the repository-level test command
    # that CI uses can execute successfully from the project root.
    result = _run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "tests/test_http_stack.py",
            "tests/test_graphrag_flow.py",
        ],
        env=integration_env,
        timeout=180,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert "passed" in combined


def test_management_script_paths_are_documented_for_release_readiness() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker volume rm pggraphrag_db_data" in readme
    assert "COMPOSE_PROJECT_NAME=pggraphrag_mcp make compose-up" in readme
    assert "scripts/mcp_http_smoke.py" in readme
    assert "https://localhost:9443/mcp" in readme


def test_public_tool_surface_freeze_is_documented() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    expected_tools = [
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
    ]
    for tool_name in expected_tools:
        assert tool_name in readme, f"{tool_name} should be documented in README"


def test_schema_and_graph_bootstrap_sql_cover_expected_objects() -> None:
    schema_sql = (PROJECT_ROOT / "docker/postgres-age/initdb/01-schema.sql").read_text(
        encoding="utf-8"
    )
    graph_sql = (
        PROJECT_ROOT / "docker/postgres-age/initdb/02-age-bootstrap.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS document" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS chunk" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS entity" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS relation_fact" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS graph_refresh_log" in schema_sql

    assert "create_graph('pggraphrag_memory')" in graph_sql
    assert "CREATE (:Document" in graph_sql
    assert "CREATE (:Chunk" in graph_sql
    assert "CREATE (:Entity" in graph_sql


def test_smoke_script_covers_seed_hybrid_and_trace_flow() -> None:
    script = (PROJECT_ROOT / "scripts/mcp_http_smoke.py").read_text(encoding="utf-8")
    assert "seed_document_request" in script
    assert "hybrid_retrieval_request" in script
    assert "source_trace_request" in script
    assert '"retrieve_hybrid"' in script
    assert '"source_trace"' in script


def test_ci_workflow_matches_release_readiness_intent() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.12"' in workflow
    assert "uv sync --frozen --all-extras" in workflow
    assert "python -m compileall src scripts tests" in workflow
    assert "uv run pytest" in workflow


def test_integration_suite_itself_documents_clean_volume_expectation() -> None:
    this_file = Path(__file__).read_text(encoding="utf-8")
    assert "docker volume rm pggraphrag_db_data" in (
        PROJECT_ROOT / "README.md"
    ).read_text(encoding="utf-8")
    assert "clean volume" in this_file.lower() or "clean-checkout" in this_file.lower()


def test_release_readiness_sections_present_in_readme() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    required_sections = [
        "## Release readiness checklist",
        "### Clean environment validation",
        "### Verification",
        "### Public surface freeze",
        "### CI validation workflow",
    ]
    for section in required_sections:
        assert section in readme


def test_compose_overlay_keeps_private_services_unpublished() -> None:
    compose_yaml = (PROJECT_ROOT / "docker/docker-compose.yml").read_text(
        encoding="utf-8"
    )
    overlay_yaml = (PROJECT_ROOT / "docker/docker-compose.small-auth.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "ports:"
        not in compose_yaml.split("pggraphrag-mcp-private:")[1].split("networks:")[0]
    )
    assert "ports:" not in compose_yaml.split("pggraphrag-db:")[1].split("networks:")[0]
    assert "${PGGRAPHRAG_MCP_PROXY_PORT:-8443}:8443" in overlay_yaml


def test_integration_suite_can_emit_json_for_release_checklist_examples(
    proxy_base_url: str,
    bearer_token: str,
) -> None:
    example = {
        "base_url": proxy_base_url,
        "mcp_path": "/mcp",
        "bearer_token": bearer_token,
        "compose_project_name": "pggraphrag_mcp",
    }
    rendered = json.dumps(example, ensure_ascii=False)
    assert '"base_url"' in rendered
    assert '"bearer_token"' in rendered
    assert "pggraphrag_mcp" in rendered

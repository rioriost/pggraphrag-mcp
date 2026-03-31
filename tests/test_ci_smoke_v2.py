# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

WORKFLOW_PATH = PROJECT_ROOT / ".github/workflows/ci.yml"
SMOKE_SCRIPT_PATH = PROJECT_ROOT / "scripts/mcp_http_smoke.py"
BOOTSTRAP_SCRIPT_PATH = PROJECT_ROOT / "scripts/bootstrap_graph.py"


def _load_workflow() -> dict:
    assert WORKFLOW_PATH.exists(), f"Missing workflow file: {WORKFLOW_PATH}"
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), "Workflow file must parse to a mapping"
    return data


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _smoke_steps() -> list[dict]:
    workflow = _load_workflow()
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "Workflow jobs must be a mapping"

    smoke_job = jobs.get("smoke")
    assert isinstance(smoke_job, dict), "Workflow must define a smoke job"

    steps = smoke_job.get("steps")
    assert isinstance(steps, list), "Smoke job steps must be a list"
    return [step for step in steps if isinstance(step, dict)]


def _step_by_name(name: str) -> dict:
    for step in _smoke_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"Missing smoke step: {name}")


def _joined_smoke_run_commands() -> str:
    return "\n".join(
        str(step.get("run", "")) for step in _smoke_steps() if isinstance(step, dict)
    )


def test_ci_workflow_and_smoke_assets_exist() -> None:
    assert WORKFLOW_PATH.exists()
    assert SMOKE_SCRIPT_PATH.exists()
    assert BOOTSTRAP_SCRIPT_PATH.exists()


def test_ci_workflow_has_smoke_job_with_expected_gate_and_timeout() -> None:
    workflow = _load_workflow()
    smoke_job = workflow["jobs"]["smoke"]

    assert smoke_job["runs-on"] == "ubuntu-latest"
    assert smoke_job["timeout-minutes"] >= 30
    assert smoke_job["if"] == (
        "github.event_name == 'workflow_dispatch' || "
        "github.ref == 'refs/heads/main' || "
        "github.ref == 'refs/heads/master'"
    )

    needs = smoke_job.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]

    assert "test" in needs


def test_smoke_job_has_expected_environment_defaults() -> None:
    workflow = _load_workflow()
    smoke_job = workflow["jobs"]["smoke"]
    env = smoke_job.get("env", {})

    assert env["COMPOSE_PROJECT_NAME"] == "pggraphrag_mcp"
    assert env["PGGRAPHRAG_MCP_PROXY_PORT"] == "9443"
    assert env["PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN"] == "change-me-local-token"
    assert env["PGGRAPHRAG_MCP_DB_PASSWORD"] == "change-me-db-password"
    assert (
        env["PGGRAPHRAG_MCP_DATABASE_URL"]
        == "postgresql://pggraphrag_app:change-me-db-password@pggraphrag-db:5432/pggraphrag"
    )
    assert env["OPENAI_API_KEY"] == ""


def test_smoke_job_contains_v2_operational_readiness_steps() -> None:
    names = [step.get("name") for step in _smoke_steps()]

    assert "Check out repository" in names
    assert "Set up Python 3.12" in names
    assert "Set up uv" in names
    assert "Create environment file" in names
    assert "Create local TLS certificate" in names
    assert "Sync dependencies" in names
    assert "Start compose stack" in names
    assert "Wait for services" in names
    assert "Run smoke test" in names
    assert "Collect compose logs on failure" in names
    assert "Tear down compose stack" in names


def test_smoke_job_creates_env_file_with_required_runtime_values() -> None:
    step = _step_by_name("Create environment file")
    run = str(step.get("run", ""))

    assert "cp .env.example .env" in run
    assert "COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}" in run
    assert "PGGRAPHRAG_MCP_PROXY_PORT=${PGGRAPHRAG_MCP_PROXY_PORT}" in run
    assert "PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN=${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN}" in run
    assert "PGGRAPHRAG_MCP_DB_PASSWORD=${PGGRAPHRAG_MCP_DB_PASSWORD}" in run
    assert "PGGRAPHRAG_MCP_DATABASE_URL=${PGGRAPHRAG_MCP_DATABASE_URL}" in run
    assert "OPENAI_API_KEY=${OPENAI_API_KEY}" in run


def test_smoke_job_generates_local_tls_certificate_assets() -> None:
    step = _step_by_name("Create local TLS certificate")
    run = str(step.get("run", ""))

    assert "mkdir -p docker/traefik/certs" in run
    assert "openssl req -x509" in run
    assert "-keyout docker/traefik/certs/dev.key" in run
    assert "-out docker/traefik/certs/dev.crt" in run
    assert '-subj "/CN=localhost"' in run


def test_smoke_job_starts_compose_with_expected_files() -> None:
    step = _step_by_name("Start compose stack")
    run = str(step.get("run", ""))

    assert "docker compose --env-file .env" in run
    assert "-f docker/docker-compose.yml" in run
    assert "-f docker/docker-compose.small-auth.yml" in run
    assert "up -d --build" in run


def test_smoke_job_waits_for_service_startup_before_smoke_execution() -> None:
    step = _step_by_name("Wait for services")
    run = str(step.get("run", ""))

    assert "sleep 10" in run


def test_smoke_job_runs_https_smoke_script_with_authentication() -> None:
    step = _step_by_name("Run smoke test")
    run = str(step.get("run", ""))

    assert "uv run python scripts/mcp_http_smoke.py" in run
    assert '--base-url "https://localhost:${PGGRAPHRAG_MCP_PROXY_PORT}"' in run
    assert "--mcp-path /mcp" in run
    assert '--bearer-token "${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN}"' in run
    assert "--insecure" in run


def test_smoke_job_failure_and_teardown_paths_are_hardened() -> None:
    failure_step = _step_by_name("Collect compose logs on failure")
    teardown_step = _step_by_name("Tear down compose stack")

    failure_run = str(failure_step.get("run", ""))
    teardown_run = str(teardown_step.get("run", ""))

    assert failure_step.get("if") == "failure()"
    assert "docker compose --env-file .env" in failure_run
    assert "ps" in failure_run
    assert "logs --no-color" in failure_run

    assert teardown_step.get("if") == "always()"
    assert "docker compose --env-file .env" in teardown_run
    assert "down --remove-orphans --volumes" in teardown_run


def test_workflow_still_uses_expected_top_level_ci_triggers() -> None:
    workflow_text = _workflow_text()

    assert "workflow_dispatch:" in workflow_text
    assert "push:" in workflow_text
    assert "pull_request:" in workflow_text
    assert "branches:" in workflow_text
    assert "- main" in workflow_text
    assert "- master" in workflow_text


def test_smoke_script_exposes_v2_end_to_end_checks() -> None:
    content = SMOKE_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "check_unauthorized_access" in content
    assert "check_authorized_health" in content
    assert "check_minimal_tool_invocation" in content
    assert "seed_smoke_document" in content
    assert "check_hybrid_retrieval" in content
    assert "check_source_trace" in content

    assert '"unauthorized"' in content
    assert '"health_check"' in content
    assert '"minimal_tool_invocation"' in content
    assert '"seed_document"' in content
    assert '"hybrid_retrieval"' in content
    assert '"source_trace"' in content


def test_smoke_script_validates_authenticated_hybrid_flow_internally() -> None:
    content = SMOKE_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'expected_id="smoke-health"' in content
    assert 'expected_id="smoke-tool"' in content
    assert 'expected_id="smoke-seed"' in content
    assert 'expected_id="smoke-hybrid"' in content
    assert "retrieval_id" in content
    assert '"sources"' in content
    assert "source_trace_request(retrieval_id)" in content


def test_smoke_script_uses_tls_and_bearer_token_inputs() -> None:
    content = SMOKE_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--base-url" in content
    assert "--mcp-path" in content
    assert "--bearer-token" in content
    assert "--timeout-seconds" in content
    assert "--insecure" in content
    assert '"Authorization": f"Bearer {bearer_token}"' in content


def test_bootstrap_graph_script_exists_for_operations_automation_path() -> None:
    content = BOOTSTRAP_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "class GraphBootstrapManager" in content
    assert "def bootstrap(" in content
    assert "def bootstrap_document(" in content
    assert "def status(" in content
    assert "graph_bootstrap_completed" in content
    assert "graph_document_bootstrap_completed" in content
    assert "graph_status_checked" in content


def test_ci_smoke_v2_focuses_on_workflow_plus_runtime_smoke_contract() -> None:
    joined = _joined_smoke_run_commands()

    assert "scripts/mcp_http_smoke.py" in joined
    assert "docker/docker-compose.yml" in joined
    assert "docker/docker-compose.small-auth.yml" in joined
    assert "docker/traefik/certs" in joined

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


def _load_workflow() -> dict:
    assert WORKFLOW_PATH.exists(), f"Missing workflow file: {WORKFLOW_PATH}"
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), "Workflow file must parse to a mapping"
    return data


def test_ci_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.exists()


def test_ci_workflow_has_smoke_job() -> None:
    workflow = _load_workflow()
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    assert "smoke" in jobs


def test_smoke_job_uses_github_actions_compatible_runner() -> None:
    workflow = _load_workflow()
    smoke_job = workflow["jobs"]["smoke"]

    assert smoke_job["runs-on"] == "ubuntu-latest"


def test_smoke_job_has_expected_dependencies() -> None:
    workflow = _load_workflow()
    smoke_job = workflow["jobs"]["smoke"]

    needs = smoke_job.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]

    assert "test" in needs


def test_smoke_job_has_timeout() -> None:
    workflow = _load_workflow()
    smoke_job = workflow["jobs"]["smoke"]

    assert isinstance(smoke_job.get("timeout-minutes"), int)
    assert smoke_job["timeout-minutes"] >= 10


def test_smoke_job_steps_include_checkout_python_and_uv() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["smoke"]["steps"]

    names = [step.get("name") for step in steps if isinstance(step, dict)]

    assert "Check out repository" in names
    assert "Set up Python 3.12" in names
    assert "Set up uv" in names


def test_smoke_job_generates_tls_assets() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["smoke"]["steps"]

    joined = "\n".join(step.get("run", "") for step in steps if isinstance(step, dict))

    assert "docker/traefik/certs" in joined
    assert "openssl req -x509" in joined
    assert "dev.crt" in joined
    assert "dev.key" in joined


def test_smoke_job_prepares_env_file_values() -> None:
    workflow = _load_workflow()
    smoke_job = workflow["jobs"]["smoke"]
    env = smoke_job.get("env", {})
    steps = smoke_job["steps"]

    joined = "\n".join(step.get("run", "") for step in steps if isinstance(step, dict))

    assert "cp .env.example .env" in joined
    assert env["COMPOSE_PROJECT_NAME"] == "pggraphrag_mcp"
    assert env["PGGRAPHRAG_MCP_PROXY_PORT"] == "9443"
    assert "PGGRAPHRAG_MCP_PROXY_PORT=${PGGRAPHRAG_MCP_PROXY_PORT}" in joined


def test_smoke_job_starts_compose_stack() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["smoke"]["steps"]

    joined = "\n".join(step.get("run", "") for step in steps if isinstance(step, dict))

    assert "docker compose" in joined
    assert "docker/docker-compose.yml" in joined
    assert "docker/docker-compose.small-auth.yml" in joined
    assert "up -d --build" in joined


def test_smoke_job_runs_https_smoke_script() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["smoke"]["steps"]

    joined = "\n".join(step.get("run", "") for step in steps if isinstance(step, dict))

    assert "scripts/mcp_http_smoke.py" in joined
    assert '--base-url "https://localhost:${PGGRAPHRAG_MCP_PROXY_PORT}"' in joined
    assert "--mcp-path /mcp" in joined
    assert '--bearer-token "${PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN}"' in joined
    assert "--insecure" in joined


def test_smoke_job_collects_logs_on_failure() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["smoke"]["steps"]

    failure_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("if") == "failure()"
    ]
    joined = "\n".join(step.get("run", "") for step in failure_steps)

    assert failure_steps, "Expected at least one failure() step"
    assert "docker compose" in joined
    assert "logs" in joined


def test_smoke_job_tears_down_stack() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["smoke"]["steps"]

    teardown_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("if") == "always()"
    ]
    joined = "\n".join(step.get("run", "") for step in teardown_steps)

    assert teardown_steps, "Expected at least one always() teardown step"
    assert "docker compose" in joined
    assert "down --remove-orphans" in joined


def test_smoke_job_trigger_is_not_every_push_by_default() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow_text
    assert "push:" in workflow_text
    assert "pull_request:" in workflow_text
    assert "branches:" in workflow_text

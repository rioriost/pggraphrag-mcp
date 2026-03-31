# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pggraphrag_mcp.ops_automation import (
    OpsAutomation,
    OpsAutomationError,
    Settings,
    build_parser,
)


class FakeCompletedProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        python_executable="python",
        database_url="postgresql://user:pass@localhost:5432/db",
        age_graph_name="pggraphrag_memory",
        app_name="pggraphrag-mcp",
        log_level="INFO",
        poll_interval_seconds=0.01,
        wait_timeout_seconds=0.05,
    )


def _write_bootstrap_script(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / "bootstrap_graph.py"
    script_path.write_text("# fake bootstrap script\n", encoding="utf-8")
    return script_path


def test_build_parser_accepts_status_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["status"])

    assert args.command == "status"
    assert args.project_root


def test_build_parser_accepts_bootstrap_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["bootstrap", "--full-rebuild", "--wait-ready"])

    assert args.command == "bootstrap"
    assert args.full_rebuild is True
    assert args.wait_ready is True


def test_build_parser_requires_document_id_for_bootstrap_document() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["bootstrap-document", "--document-id", "doc-123", "--wait-ready"]
    )

    assert args.command == "bootstrap-document"
    assert args.document_id == "doc-123"
    assert args.wait_ready is True


def test_build_parser_accepts_plan_actions() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "plan",
            "--actions",
            "status",
            "bootstrap",
            "ensure-ready",
            "--full-rebuild",
            "--wait-ready",
        ]
    )

    assert args.command == "plan"
    assert args.actions == ["status", "bootstrap", "ensure-ready"]
    assert args.full_rebuild is True
    assert args.wait_ready is True


def test_status_returns_graph_payload(monkeypatch: Any, tmp_path: Path) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == ["--status"]
        return {
            "graph_name": "pggraphrag_memory",
            "graph_exists": True,
            "node_count": 12,
            "edge_count": 18,
            "latest_refresh": {"status": "completed"},
        }

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)

    result = automation.status()

    assert result["status"] == "ok"
    assert result["operation"] == "graph_status"
    assert result["graph"]["graph_exists"] is True
    assert result["graph"]["node_count"] == 12


def test_bootstrap_without_wait_ready_returns_bootstrap_payload(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == ["--full-rebuild"]
        return {
            "graph_name": "pggraphrag_memory",
            "graph_refresh_id": "refresh-1",
            "status": "completed",
        }

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)

    result = automation.bootstrap(full_rebuild=True, wait_ready=False)

    assert result["status"] == "ok"
    assert result["operation"] == "graph_bootstrap"
    assert result["bootstrap"]["graph_refresh_id"] == "refresh-1"
    assert result["readiness"] is None


def test_bootstrap_with_wait_ready_includes_readiness(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == []
        return {
            "graph_name": "pggraphrag_memory",
            "graph_refresh_id": "refresh-2",
            "status": "completed",
        }

    def fake_wait_until_ready() -> dict[str, Any]:
        return {
            "status": "ok",
            "operation": "graph_wait_ready",
            "checks": {"ready": True},
        }

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)
    monkeypatch.setattr(automation, "wait_until_ready", fake_wait_until_ready)

    result = automation.bootstrap(full_rebuild=False, wait_ready=True)

    assert result["status"] == "ok"
    assert result["bootstrap"]["graph_refresh_id"] == "refresh-2"
    assert result["readiness"]["checks"]["ready"] is True


def test_bootstrap_document_requires_document_id_and_returns_payload(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == ["--document-id", "doc-42"]
        return {
            "graph_name": "pggraphrag_memory",
            "graph_refresh_id": "refresh-doc-42",
            "document_id": "doc-42",
            "status": "completed",
        }

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)

    result = automation.bootstrap_document(document_id="doc-42", wait_ready=False)

    assert result["status"] == "ok"
    assert result["operation"] == "graph_bootstrap_document"
    assert result["document_id"] == "doc-42"
    assert result["bootstrap"]["graph_refresh_id"] == "refresh-doc-42"


def test_ensure_ready_reports_not_ready_when_checks_fail(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == ["--status"]
        return {
            "graph_name": "pggraphrag_memory",
            "graph_exists": False,
            "node_count": 0,
            "edge_count": 0,
            "latest_refresh": None,
        }

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)

    result = automation.ensure_ready()

    assert result["status"] == "not_ready"
    assert result["checks"]["ready"] is False
    assert result["checks"]["graph_exists"] is False
    assert result["checks"]["latest_refresh_completed"] is False


def test_evaluate_graph_readiness_requires_graph_nodes_and_completed_refresh(
    tmp_path: Path,
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    checks = automation._evaluate_graph_readiness(
        {
            "graph_exists": True,
            "node_count": 3,
            "edge_count": 2,
            "latest_refresh": {"status": "completed"},
        }
    )

    assert checks["graph_exists"] is True
    assert checks["has_nodes"] is True
    assert checks["has_edges"] is True
    assert checks["latest_refresh_completed"] is True
    assert checks["ready"] is True


def test_wait_until_ready_returns_when_graph_becomes_ready(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    responses = iter(
        [
            {
                "graph_name": "pggraphrag_memory",
                "graph_exists": True,
                "node_count": 0,
                "edge_count": 0,
                "latest_refresh": None,
            },
            {
                "graph_name": "pggraphrag_memory",
                "graph_exists": True,
                "node_count": 9,
                "edge_count": 12,
                "latest_refresh": {"status": "completed"},
            },
        ]
    )

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == ["--status"]
        return next(responses)

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)
    monkeypatch.setattr("pggraphrag_mcp.ops_automation.time.sleep", lambda _: None)

    result = automation.wait_until_ready()

    assert result["status"] == "ok"
    assert result["operation"] == "graph_wait_ready"
    assert result["attempts"] == 2
    assert result["checks"]["ready"] is True
    assert result["graph"]["node_count"] == 9


def test_wait_until_ready_times_out_when_graph_never_becomes_ready(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run_bootstrap_graph(args: list[str]) -> dict[str, Any]:
        assert args == ["--status"]
        return {
            "graph_name": "pggraphrag_memory",
            "graph_exists": True,
            "node_count": 0,
            "edge_count": 0,
            "latest_refresh": None,
        }

    timeline = iter([0.0, 0.02, 0.06, 0.07])

    monkeypatch.setattr(automation, "_run_bootstrap_graph", fake_run_bootstrap_graph)
    monkeypatch.setattr("pggraphrag_mcp.ops_automation.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "pggraphrag_mcp.ops_automation.time.monotonic", lambda: next(timeline)
    )

    try:
        automation.wait_until_ready()
    except OpsAutomationError as exc:
        payload = json.loads(str(exc))
    else:
        raise AssertionError("Expected wait_until_ready to time out")

    assert payload["message"] == "Timed out waiting for graph readiness."
    assert payload["checks"]["ready"] is False
    assert payload["graph"]["graph_exists"] is True


def test_run_plan_executes_actions_in_order(monkeypatch: Any, tmp_path: Path) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))
    calls: list[str] = []

    def fake_status() -> dict[str, Any]:
        calls.append("status")
        return {"status": "ok", "operation": "graph_status"}

    def fake_bootstrap(*, full_rebuild: bool, wait_ready: bool) -> dict[str, Any]:
        calls.append(f"bootstrap:{full_rebuild}:{wait_ready}")
        return {"status": "ok", "operation": "graph_bootstrap"}

    def fake_ensure_ready() -> dict[str, Any]:
        calls.append("ensure-ready")
        return {"status": "ok", "operation": "graph_ensure_ready"}

    monkeypatch.setattr(automation, "status", fake_status)
    monkeypatch.setattr(automation, "bootstrap", fake_bootstrap)
    monkeypatch.setattr(automation, "ensure_ready", fake_ensure_ready)

    result = automation.run_plan(
        actions=["status", "bootstrap", "ensure-ready"],
        full_rebuild=True,
        wait_ready=True,
    )

    assert calls == ["status", "bootstrap:True:True", "ensure-ready"]
    assert result["status"] == "ok"
    assert result["operation"] == "plan"
    assert len(result["results"]) == 3


def test_run_plan_requires_document_id_for_bootstrap_document(
    tmp_path: Path,
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    try:
        automation.run_plan(actions=["bootstrap-document"])
    except OpsAutomationError as exc:
        assert (
            str(exc) == "document_id is required when plan includes bootstrap-document"
        )
    else:
        raise AssertionError("Expected plan without document_id to fail")


def test_run_bootstrap_graph_invokes_subprocess_and_parses_json(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))
    seen: dict[str, Any] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> FakeCompletedProcess:
        seen["command"] = command
        seen["cwd"] = cwd
        seen["capture_output"] = capture_output
        seen["text"] = text
        seen["check"] = check
        assert env["PATH"]
        return FakeCompletedProcess(
            returncode=0,
            stdout=json.dumps(
                {
                    "graph_name": "pggraphrag_memory",
                    "graph_exists": True,
                    "node_count": 4,
                    "edge_count": 5,
                    "latest_refresh": {"status": "completed"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("pggraphrag_mcp.ops_automation.subprocess.run", fake_run)

    result = automation._run_bootstrap_graph(["status"])

    assert seen["command"][0] == "python"
    assert seen["command"][1].endswith("scripts/bootstrap_graph.py")
    assert seen["command"][2:] == ["status"]
    assert seen["cwd"] == str(tmp_path)
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["check"] is False
    assert result["graph_exists"] is True
    assert result["node_count"] == 4


def test_run_bootstrap_graph_raises_on_nonzero_exit(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run(*args: Any, **kwargs: Any) -> FakeCompletedProcess:
        return FakeCompletedProcess(
            returncode=2,
            stdout="partial output",
            stderr="boom",
        )

    monkeypatch.setattr("pggraphrag_mcp.ops_automation.subprocess.run", fake_run)

    try:
        automation._run_bootstrap_graph(["status"])
    except OpsAutomationError as exc:
        payload = json.loads(str(exc))
    else:
        raise AssertionError("Expected subprocess failure to raise")

    assert payload["message"] == "bootstrap_graph command failed"
    assert payload["args"] == ["status"]
    assert payload["returncode"] == 2
    assert payload["stderr"] == "boom"


def test_run_bootstrap_graph_raises_when_stdout_is_not_json(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run(*args: Any, **kwargs: Any) -> FakeCompletedProcess:
        return FakeCompletedProcess(
            returncode=0,
            stdout="not-json",
            stderr="",
        )

    monkeypatch.setattr("pggraphrag_mcp.ops_automation.subprocess.run", fake_run)

    try:
        automation._run_bootstrap_graph(["status"])
    except OpsAutomationError as exc:
        payload = json.loads(str(exc))
    else:
        raise AssertionError("Expected invalid JSON to raise")

    assert payload["message"] == "Failed to parse JSON output"
    assert payload["stdout"] == "not-json"


def test_run_bootstrap_graph_accepts_last_json_line_output(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _write_bootstrap_script(tmp_path)
    automation = OpsAutomation(_settings(tmp_path))

    def fake_run(*args: Any, **kwargs: Any) -> FakeCompletedProcess:
        return FakeCompletedProcess(
            returncode=0,
            stdout='progress line\n{"graph_exists": true, "node_count": 7}',
            stderr="",
        )

    monkeypatch.setattr("pggraphrag_mcp.ops_automation.subprocess.run", fake_run)

    result = automation._run_bootstrap_graph(["status"])

    assert result["graph_exists"] is True
    assert result["node_count"] == 7


def test_run_bootstrap_graph_requires_bootstrap_script_exists(tmp_path: Path) -> None:
    automation = OpsAutomation(_settings(tmp_path))

    try:
        automation._ensure_bootstrap_script_exists()
    except OpsAutomationError as exc:
        assert "Missing bootstrap script:" in str(exc)
    else:
        raise AssertionError("Expected missing bootstrap script to fail")

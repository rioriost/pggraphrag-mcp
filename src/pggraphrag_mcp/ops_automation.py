from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "timestamp": utc_now().isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    print(json_dumps(payload), file=sys.stderr)


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip()
    return normalized if normalized else default


class OpsAutomationError(RuntimeError):
    """Raised when an operational automation action fails."""


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    python_executable: str
    database_url: str | None
    age_graph_name: str
    app_name: str
    log_level: str
    poll_interval_seconds: float
    wait_timeout_seconds: float

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Settings":
        project_root = Path(args.project_root).resolve()
        return cls(
            project_root=project_root,
            python_executable=args.python or sys.executable,
            database_url=env("PGGRAPHRAG_MCP_DATABASE_URL"),
            age_graph_name=env("PGGRAPHRAG_MCP_AGE_GRAPH_NAME", "pggraphrag_memory")
            or "pggraphrag_memory",
            app_name=env("PGGRAPHRAG_MCP_APP_NAME", "pggraphrag-mcp")
            or "pggraphrag-mcp",
            log_level=env("PGGRAPHRAG_MCP_LOG_LEVEL", "INFO") or "INFO",
            poll_interval_seconds=float(args.poll_interval_seconds),
            wait_timeout_seconds=float(args.wait_timeout_seconds),
        )


class OpsAutomation:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bootstrap_script = (
            self.settings.project_root / "scripts" / "bootstrap_graph.py"
        )

    def status(self) -> dict[str, Any]:
        result = self._run_bootstrap_graph(["--status"])
        payload = {
            "status": "ok",
            "operation": "graph_status",
            "graph": result,
        }
        log_event(
            "ops_automation_status_completed",
            operation="graph_status",
            graph_name=result.get("graph_name"),
            graph_exists=result.get("graph_exists"),
            node_count=result.get("node_count"),
            edge_count=result.get("edge_count"),
        )
        return payload

    def bootstrap(
        self,
        *,
        full_rebuild: bool = False,
        wait_ready: bool = False,
    ) -> dict[str, Any]:
        command: list[str] = []
        if full_rebuild:
            command.append("--full-rebuild")

        started_at = utc_now()
        bootstrap_result = self._run_bootstrap_graph(command)

        readiness: dict[str, Any] | None = None
        if wait_ready:
            readiness = self.wait_until_ready()

        payload = {
            "status": "ok",
            "operation": "graph_bootstrap",
            "started_at": started_at.isoformat(),
            "finished_at": utc_now().isoformat(),
            "bootstrap": bootstrap_result,
            "readiness": readiness,
        }
        log_event(
            "ops_automation_bootstrap_completed",
            operation="graph_bootstrap",
            full_rebuild=full_rebuild,
            wait_ready=wait_ready,
            graph_name=bootstrap_result.get("graph_name"),
            graph_refresh_id=bootstrap_result.get("graph_refresh_id"),
        )
        return payload

    def bootstrap_document(
        self,
        *,
        document_id: str,
        wait_ready: bool = False,
    ) -> dict[str, Any]:
        started_at = utc_now()
        bootstrap_result = self._run_bootstrap_graph(["--document-id", document_id])

        readiness: dict[str, Any] | None = None
        if wait_ready:
            readiness = self.wait_until_ready()

        payload = {
            "status": "ok",
            "operation": "graph_bootstrap_document",
            "started_at": started_at.isoformat(),
            "finished_at": utc_now().isoformat(),
            "document_id": document_id,
            "bootstrap": bootstrap_result,
            "readiness": readiness,
        }
        log_event(
            "ops_automation_document_bootstrap_completed",
            operation="graph_bootstrap_document",
            document_id=document_id,
            wait_ready=wait_ready,
            graph_name=bootstrap_result.get("graph_name"),
            graph_refresh_id=bootstrap_result.get("graph_refresh_id"),
        )
        return payload

    def ensure_ready(self) -> dict[str, Any]:
        graph = self._run_bootstrap_graph(["--status"])
        checks = self._evaluate_graph_readiness(graph)
        payload = {
            "status": "ok" if checks["ready"] else "not_ready",
            "operation": "graph_ensure_ready",
            "graph": graph,
            "checks": checks,
        }
        log_event(
            "ops_automation_ensure_ready_completed",
            operation="graph_ensure_ready",
            ready=checks["ready"],
            graph_name=graph.get("graph_name"),
        )
        return payload

    def wait_until_ready(self) -> dict[str, Any]:
        started = time.monotonic()
        attempts = 0
        last_graph: dict[str, Any] | None = None
        last_checks: dict[str, Any] | None = None

        while True:
            attempts += 1
            graph = self._run_bootstrap_graph(["--status"])
            checks = self._evaluate_graph_readiness(graph)
            last_graph = graph
            last_checks = checks

            if checks["ready"]:
                payload = {
                    "status": "ok",
                    "operation": "graph_wait_ready",
                    "attempts": attempts,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "graph": graph,
                    "checks": checks,
                }
                log_event(
                    "ops_automation_wait_ready_completed",
                    operation="graph_wait_ready",
                    attempts=attempts,
                    elapsed_seconds=payload["elapsed_seconds"],
                    graph_name=graph.get("graph_name"),
                )
                return payload

            elapsed = time.monotonic() - started
            if elapsed >= self.settings.wait_timeout_seconds:
                raise OpsAutomationError(
                    json_dumps(
                        {
                            "message": "Timed out waiting for graph readiness.",
                            "attempts": attempts,
                            "elapsed_seconds": round(elapsed, 3),
                            "graph": last_graph,
                            "checks": last_checks,
                        }
                    )
                )

            time.sleep(self.settings.poll_interval_seconds)

    def run_plan(
        self,
        *,
        actions: Sequence[str],
        full_rebuild: bool = False,
        document_id: str | None = None,
        wait_ready: bool = False,
    ) -> dict[str, Any]:
        executed: list[dict[str, Any]] = []

        for action in actions:
            if action == "status":
                executed.append(self.status())
            elif action == "bootstrap":
                executed.append(
                    self.bootstrap(
                        full_rebuild=full_rebuild,
                        wait_ready=wait_ready,
                    )
                )
            elif action == "bootstrap-document":
                if not document_id:
                    raise OpsAutomationError(
                        "document_id is required when plan includes bootstrap-document"
                    )
                executed.append(
                    self.bootstrap_document(
                        document_id=document_id,
                        wait_ready=wait_ready,
                    )
                )
            elif action == "ensure-ready":
                executed.append(self.ensure_ready())
            elif action == "wait-ready":
                executed.append(self.wait_until_ready())
            else:
                raise OpsAutomationError(f"Unsupported plan action: {action}")

        payload = {
            "status": "ok",
            "operation": "plan",
            "actions": list(actions),
            "results": executed,
        }
        log_event(
            "ops_automation_plan_completed",
            operation="plan",
            actions=list(actions),
            result_count=len(executed),
        )
        return payload

    def _run_bootstrap_graph(self, args: Sequence[str]) -> dict[str, Any]:
        self._ensure_bootstrap_script_exists()

        command = [
            self.settings.python_executable,
            str(self.bootstrap_script),
            *args,
        ]
        env_map = os.environ.copy()

        completed = subprocess.run(
            command,
            cwd=str(self.settings.project_root),
            env=env_map,
            capture_output=True,
            text=True,
            check=False,
        )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

        if completed.returncode != 0:
            raise OpsAutomationError(
                json_dumps(
                    {
                        "message": "bootstrap_graph command failed",
                        "args": list(args),
                        "returncode": completed.returncode,
                        "stdout": stdout,
                        "stderr": stderr,
                    }
                )
            )

        payload = self._parse_json_payload(stdout)
        if not isinstance(payload, dict):
            raise OpsAutomationError(
                json_dumps(
                    {
                        "message": "bootstrap_graph did not return a JSON object",
                        "args": list(args),
                        "stdout": stdout,
                        "stderr": stderr,
                    }
                )
            )
        return payload

    def _ensure_bootstrap_script_exists(self) -> None:
        if not self.bootstrap_script.exists():
            raise OpsAutomationError(
                f"Missing bootstrap script: {self.bootstrap_script}"
            )

    def _parse_json_payload(self, stdout: str) -> Any:
        if not stdout:
            raise OpsAutomationError("bootstrap_graph returned empty stdout")

        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            last_line = stdout.splitlines()[-1].strip()
            try:
                return json.loads(last_line)
            except json.JSONDecodeError as exc:
                raise OpsAutomationError(
                    json_dumps(
                        {
                            "message": "Failed to parse JSON output",
                            "stdout": stdout,
                        }
                    )
                ) from exc

    def _evaluate_graph_readiness(self, graph: dict[str, Any]) -> dict[str, Any]:
        latest_refresh = graph.get("latest_refresh")
        latest_refresh_completed = isinstance(latest_refresh, dict) and (
            latest_refresh.get("status") == "completed"
        )

        graph_exists = bool(graph.get("graph_exists"))
        node_count = int(graph.get("node_count", 0) or 0)
        edge_count = int(graph.get("edge_count", 0) or 0)

        checks = {
            "graph_exists": graph_exists,
            "has_nodes": node_count > 0,
            "has_edges": edge_count >= 0,
            "latest_refresh_completed": latest_refresh_completed,
        }
        checks["ready"] = all(
            [
                checks["graph_exists"],
                checks["has_nodes"],
                checks["latest_refresh_completed"],
            ]
        )
        return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ops_automation.py",
        description=(
            "Operational automation CLI for pggraphrag-mcp graph status, "
            "bootstrap, and readiness workflows."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Project root that contains the scripts directory.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to invoke sibling management scripts.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval used by wait-ready flows.",
    )
    parser.add_argument(
        "--wait-timeout-seconds",
        type=float,
        default=60.0,
        help="Maximum time to wait for graph readiness.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "status",
        help="Return current graph status via bootstrap_graph.py status.",
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Run full graph bootstrap flow.",
    )
    bootstrap_parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Truncate and fully rebuild the AGE projection before projecting data.",
    )
    bootstrap_parser.add_argument(
        "--wait-ready",
        action="store_true",
        help="Poll graph status until readiness checks pass after bootstrap.",
    )

    bootstrap_document_parser = subparsers.add_parser(
        "bootstrap-document",
        help="Re-project one document into the graph.",
    )
    bootstrap_document_parser.add_argument(
        "--document-id",
        required=True,
        help="Document identifier to re-project.",
    )
    bootstrap_document_parser.add_argument(
        "--wait-ready",
        action="store_true",
        help="Poll graph status until readiness checks pass after document bootstrap.",
    )

    subparsers.add_parser(
        "ensure-ready",
        help="Evaluate whether the graph is currently ready for use.",
    )

    subparsers.add_parser(
        "wait-ready",
        help="Poll graph status until readiness checks pass or timeout is reached.",
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help="Execute multiple operations in sequence.",
    )
    plan_parser.add_argument(
        "--actions",
        nargs="+",
        required=True,
        choices=[
            "status",
            "bootstrap",
            "bootstrap-document",
            "ensure-ready",
            "wait-ready",
        ],
        help="Ordered list of actions to execute.",
    )
    plan_parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Apply full rebuild behavior to bootstrap actions in the plan.",
    )
    plan_parser.add_argument(
        "--document-id",
        help="Document identifier used by bootstrap-document plan actions.",
    )
    plan_parser.add_argument(
        "--wait-ready",
        action="store_true",
        help="Apply readiness waiting behavior to eligible plan actions.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_args(args)
    automation = OpsAutomation(settings)

    try:
        if args.command == "status":
            result = automation.status()
        elif args.command == "bootstrap":
            result = automation.bootstrap(
                full_rebuild=bool(args.full_rebuild),
                wait_ready=bool(args.wait_ready),
            )
        elif args.command == "bootstrap-document":
            result = automation.bootstrap_document(
                document_id=str(args.document_id),
                wait_ready=bool(args.wait_ready),
            )
        elif args.command == "ensure-ready":
            result = automation.ensure_ready()
        elif args.command == "wait-ready":
            result = automation.wait_until_ready()
        elif args.command == "plan":
            result = automation.run_plan(
                actions=args.actions,
                full_rebuild=bool(args.full_rebuild),
                document_id=args.document_id,
                wait_ready=bool(args.wait_ready),
            )
        else:
            raise OpsAutomationError(f"Unsupported command: {args.command}")

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except OpsAutomationError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


__all__ = [
    "OpsAutomation",
    "OpsAutomationError",
    "Settings",
    "build_parser",
    "main",
]

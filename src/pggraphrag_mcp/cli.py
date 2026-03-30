from __future__ import annotations

import argparse
from collections.abc import Sequence

from .config import AppConfig
from .http_app import main as http_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pggraphrag-mcp",
        description="Local orchestration utilities for pggraphrag-mcp.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the HTTP application server.",
    )
    serve_parser.add_argument(
        "--host",
        dest="host",
        default=None,
        help="Override the HTTP bind host.",
    )
    serve_parser.add_argument(
        "--port",
        dest="port",
        type=int,
        default=None,
        help="Override the HTTP bind port.",
    )
    serve_parser.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        help="Enable auto-reload for local development.",
    )

    subparsers.add_parser(
        "print-config",
        help="Print a short summary of the active runtime configuration.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "serve":
        serve_args: list[str] = []
        if args.host is not None:
            serve_args.extend(["--host", args.host])
        if args.port is not None:
            serve_args.extend(["--port", str(args.port)])
        if args.reload:
            serve_args.append("--reload")
        return http_main(serve_args)

    if args.command == "print-config":
        settings = AppConfig.load()
        print(f"app_name={settings.app_name}")
        print(f"app_version={settings.app_version}")
        print(f"environment={settings.env}")
        print(f"http_host={settings.http_host}")
        print(f"http_port={settings.http_port}")
        print(f"http_path={settings.http_path}")
        print(f"database_host={settings.db_host}")
        print(f"database_port={settings.db_port}")
        print(f"database_name={settings.db_name}")
        print(f"database_url={settings.redacted_database_url}")
        print(f"age_graph_name={settings.age_graph_name}")
        print(f"auth_header_name={settings.auth_header_name}")
        print(f"auth_identity={settings.auth_identity}")
        print(f"mcp_url={settings.mcp_url}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2

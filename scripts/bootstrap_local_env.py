from __future__ import annotations

import argparse
import getpass
import secrets
import shutil
import socket
import sys
from pathlib import Path

DEFAULT_COMPOSE_PROJECT_NAME = "pggraphrag_mcp"
DEFAULT_PROXY_PORT = "9443"
DEFAULT_DB_PASSWORD_LENGTH = 24
DEFAULT_OPENAI_API_KEY = ""


def parse_env_file(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}

    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return lines, values


def ensure_line(lines: list[str], key: str, value: str) -> list[str]:
    updated = False
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            result.append(f"{key}={value}")
            updated = True
        else:
            result.append(line)

    if not updated:
        result.append(f"{key}={value}")

    return result


def is_local_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def select_local_proxy_port() -> str:
    preferred_ports = [
        9443,
        8443,
        10443,
        11443,
        12443,
        13443,
        14443,
    ]
    for port in preferred_ports:
        if is_local_port_free(port):
            return str(port)
    raise RuntimeError(
        "Could not find a free local proxy port. "
        "Free one of 9443/8443/10443/11443/12443/13443/14443 or set "
        "PGGRAPHRAG_MCP_PROXY_PORT manually after bootstrap."
    )


def ensure_required_values(lines: list[str], values: dict[str, str]) -> list[str]:
    configured_proxy_port = values.get("PGGRAPHRAG_MCP_PROXY_PORT", "").strip()

    if configured_proxy_port:
        try:
            proxy_port_int = int(configured_proxy_port)
        except ValueError:
            proxy_port = select_local_proxy_port()
        else:
            if proxy_port_int == 8443:
                proxy_port = (
                    configured_proxy_port
                    if is_local_port_free(proxy_port_int)
                    else select_local_proxy_port()
                )
            elif is_local_port_free(proxy_port_int):
                proxy_port = configured_proxy_port
            else:
                proxy_port = select_local_proxy_port()
    else:
        proxy_port = select_local_proxy_port()

    configured_auth_token = values.get("PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN", "").strip()
    auth_token = configured_auth_token or secrets.token_urlsafe(32)

    configured_db_password = values.get("PGGRAPHRAG_MCP_DB_PASSWORD", "").strip()
    db_password = configured_db_password or secrets.token_urlsafe(
        DEFAULT_DB_PASSWORD_LENGTH
    )

    configured_db_user = (
        values.get("PGGRAPHRAG_MCP_DB_USER", "").strip() or "pggraphrag_app"
    )
    configured_db_host = (
        values.get("PGGRAPHRAG_MCP_DB_HOST", "").strip() or "pggraphrag-db"
    )
    configured_db_port = values.get("PGGRAPHRAG_MCP_DB_PORT", "").strip() or "5432"
    configured_db_name = (
        values.get("PGGRAPHRAG_MCP_DB_NAME", "").strip() or "pggraphrag"
    )

    configured_database_url = values.get("PGGRAPHRAG_MCP_DATABASE_URL", "").strip()
    database_url = (
        configured_database_url
        or f"postgresql://{configured_db_user}:{db_password}@{configured_db_host}:{configured_db_port}/{configured_db_name}"
    )

    required_defaults = {
        "COMPOSE_PROJECT_NAME": DEFAULT_COMPOSE_PROJECT_NAME,
        "PGGRAPHRAG_MCP_PROXY_PORT": proxy_port,
        "PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN": auth_token,
        "AUTH_SMALL_BEARER_TOKEN": auth_token,
        "PGGRAPHRAG_MCP_DB_PASSWORD": db_password,
        "PGGRAPHRAG_MCP_DATABASE_URL": database_url,
        "OPENAI_API_KEY": DEFAULT_OPENAI_API_KEY,
    }

    result = list(lines)
    for key, default_value in required_defaults.items():
        if key not in values:
            result = ensure_line(result, key, default_value)

    if values.get("PGGRAPHRAG_MCP_PROXY_PORT", "").strip() != proxy_port:
        result = ensure_line(result, "PGGRAPHRAG_MCP_PROXY_PORT", proxy_port)

    if values.get("PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN", "").strip() != auth_token:
        result = ensure_line(result, "PGGRAPHRAG_MCP_SMALL_AUTH_TOKEN", auth_token)

    if values.get("AUTH_SMALL_BEARER_TOKEN", "").strip() != auth_token:
        result = ensure_line(result, "AUTH_SMALL_BEARER_TOKEN", auth_token)

    if values.get("PGGRAPHRAG_MCP_DB_PASSWORD", "").strip() != db_password:
        result = ensure_line(result, "PGGRAPHRAG_MCP_DB_PASSWORD", db_password)

    if values.get("PGGRAPHRAG_MCP_DATABASE_URL", "").strip() != database_url:
        result = ensure_line(result, "PGGRAPHRAG_MCP_DATABASE_URL", database_url)

    return result


def prompt_openai_api_key(
    *,
    existing_value: str | None,
    provided_value: str | None = None,
) -> str:
    if provided_value and provided_value.strip():
        return provided_value.strip()

    if existing_value and existing_value.strip():
        return existing_value.strip()

    if not sys.stdin.isatty():
        raise RuntimeError(
            "OPENAI_API_KEY is missing and no interactive terminal is available. "
            "Set OPENAI_API_KEY before running bootstrap."
        )

    api_key = getpass.getpass("Input OpenAI API Key: ").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required to bootstrap the local environment."
        )
    return api_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap_local_env.py",
        description=(
            "Create or update a local .env file for pggraphrag-mcp using "
            ".env.example as the base and interactive prompts for required secrets."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the local env file to create or update.",
    )
    parser.add_argument(
        "--env-example",
        default=".env.example",
        help="Path to the example env file to copy from when the env file is missing.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=None,
        help="Optional OpenAI API key to write without prompting.",
    )
    parser.add_argument(
        "--force-openai-prompt",
        action="store_true",
        help="Prompt for OPENAI_API_KEY even if the env file already contains a value.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    env_file = Path(args.env_file).resolve()
    env_example = Path(args.env_example).resolve()

    if not env_file.exists():
        if not env_example.exists():
            parser.error(f"Missing env example file: {env_example}")
        env_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(env_example, env_file)

    lines, values = parse_env_file(env_file)
    lines = ensure_required_values(lines, values)
    _, values = parse_env_file(env_file) if False else (lines, {**values})

    current_openai_value = values.get("OPENAI_API_KEY", "")
    if args.force_openai_prompt:
        current_openai_value = ""

    resolved_openai_key = prompt_openai_api_key(
        existing_value=current_openai_value,
        provided_value=args.openai_api_key,
    )

    lines = ensure_line(lines, "OPENAI_API_KEY", resolved_openai_key)

    final_text = "\n".join(lines).rstrip() + "\n"
    env_file.write_text(final_text, encoding="utf-8")

    print(f"Bootstrapped local env file: {env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

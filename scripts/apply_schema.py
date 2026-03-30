from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Iterable

import psycopg

DEFAULT_SQL_FILES = (
    "docker/postgres-age/initdb/00-init-extensions.sql",
    "docker/postgres-age/initdb/01-schema.sql",
    "docker/postgres-age/initdb/02-age-bootstrap.sql",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apply_schema.py",
        description=(
            "Apply the pggraphrag-mcp PostgreSQL extension, schema, and AGE bootstrap "
            "SQL files in a deterministic order."
        ),
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        required=True,
        help="PostgreSQL connection string.",
    )
    parser.add_argument(
        "--sql-file",
        dest="sql_files",
        action="append",
        default=None,
        help=(
            "Additional or replacement SQL file path. "
            "If omitted, the default repository-owned init SQL files are used."
        ),
    )
    parser.add_argument(
        "--project-root",
        dest="project_root",
        default=".",
        help="Repository root used to resolve relative SQL file paths.",
    )
    parser.add_argument(
        "--application-name",
        dest="application_name",
        default="pggraphrag-mcp-schema-apply",
        help="PostgreSQL application_name for this management operation.",
    )
    parser.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="Validate SQL files and print the execution plan without applying changes.",
    )
    parser.add_argument(
        "--stop-on-error",
        dest="stop_on_error",
        action="store_true",
        default=True,
        help="Stop immediately when a SQL file fails. Enabled by default.",
    )
    parser.add_argument(
        "--continue-on-error",
        dest="stop_on_error",
        action="store_false",
        help="Continue applying later files even if an earlier file fails.",
    )
    parser.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Print additional progress information.",
    )
    return parser


def resolve_sql_files(project_root: Path, provided: list[str] | None) -> list[Path]:
    raw_paths = provided if provided else list(DEFAULT_SQL_FILES)
    resolved: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = (project_root / path).resolve()
        resolved.append(path)
    return resolved


def ensure_sql_files_exist(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise FileNotFoundError(f"Missing SQL file(s):\n{joined}")


def read_sql_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"SQL file is empty: {path}")
    return content


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def apply_sql_file(
    conn: psycopg.Connection,
    *,
    sql_path: Path,
    sql_text: str,
    verbose: bool,
) -> None:
    if verbose:
        print(f"[apply] {sql_path}")
    with conn.cursor() as cur:
        cur.execute(sql_text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    sql_files = resolve_sql_files(project_root, args.sql_files)
    ensure_sql_files_exist(sql_files)

    sql_plan: list[tuple[Path, str]] = []
    for sql_file in sql_files:
        sql_text = read_sql_file(sql_file)
        sql_plan.append((sql_file, sql_text))

    print("Schema application plan:")
    for index, (sql_file, sql_text) in enumerate(sql_plan, start=1):
        digest = sha256_text(sql_text)[:12]
        print(f"{index}. {sql_file}  sha256:{digest}")

    if args.check_only:
        print("Check-only mode: no SQL was executed.")
        return 0

    failures: list[tuple[Path, str]] = []

    try:
        with psycopg.connect(
            args.database_url,
            autocommit=True,
            application_name=args.application_name,
        ) as conn:
            for sql_file, sql_text in sql_plan:
                try:
                    apply_sql_file(
                        conn,
                        sql_path=sql_file,
                        sql_text=sql_text,
                        verbose=args.verbose,
                    )
                except Exception as exc:
                    failures.append((sql_file, str(exc)))
                    print(f"[error] {sql_file}: {exc}", file=sys.stderr)
                    if args.stop_on_error:
                        break
    except Exception as exc:
        print(
            f"Failed to connect or initialize schema apply session: {exc}",
            file=sys.stderr,
        )
        return 1

    if failures:
        print("\nSchema apply completed with failures:", file=sys.stderr)
        for sql_file, message in failures:
            print(f"- {sql_file}: {message}", file=sys.stderr)
        return 1

    print("Schema apply completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

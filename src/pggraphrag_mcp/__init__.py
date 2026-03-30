from __future__ import annotations

import sys

from .cli import main as cli_main


def main() -> None:
    """Package entrypoint for console script execution."""
    raise SystemExit(cli_main(sys.argv[1:]))

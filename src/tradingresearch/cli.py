"""The `tr` command: a thin dispatcher over the command table in `commands/`."""

from __future__ import annotations

import argparse

from .commands import COMMANDS
from .config import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tr", description="tradingresearch: educational, not investment advice")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        command.register(sub)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    cfg = settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    args.func(args, cfg)

"""The `tr` entry point: `tr lab ...` goes to the lab runner without importing `cli`, everything else to `cli.main`.

A lab stub can leave any module `cli` imports broken (analyze.py, evals.py, ...); `tr lab` must still run then.
"""

from __future__ import annotations

import sys

from . import lab


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["lab"]:
        raise SystemExit(lab.main(argv[1:]))
    from .cli import main as real

    real(argv)

"""Observe for lab w5l3: what your experiment.compare prints as `tr exp compare` ($0, no network).

    python labs/w5/tools/observe_compare.py

Prints four compare blocks through commands/exp.py's own `show`, on the author's three context-ablation runs
(tools/runs.py rebuilds them from data/ablation.runs.json; the stored runs `tr exp compare` reads are not in the repo):

  1-2. full -> no-headlines and full -> no-edgar on every grader either run scored, in the order the runs first
       scored them: the chapter's two blocks (section 5), skipped lines first.
  3.   full -> no-edgar on the seven graders in the order experiments/context-ablation.toml names them.
  4.   full -> no-edgar on edgar_grounded and levels_grounded only, the two its drop leaves without a common item.

TR_LAB_DATA overrides labs/w5/data. Exits 0: it shows what your code does, the exercise's check decides. The offline
guard (tools/offline.py) is installed before your code is imported; a guarded call it tried is named in a `note:` line
at the end.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline  # noqa: E402

offline.install()  # before runs and your code are imported
import runs  # noqa: E402

SEVEN = ("parsed", "claims_valid", "all_claims_valid", "indicators_grounded", "levels_grounded", "edgar_grounded",
         "headlines_grounded")


def main() -> int:
    try:
        from tradingresearch.commands import exp
    except Exception as exc:  # a half-written file: show it, stop
        print(f"tradingresearch.commands.exp does not import: {type(exc).__name__}: {exc}")
        return 0
    stored = runs.stored()
    full = stored["full"]
    blocks = [("no-headlines", None, "every grader either run scored"),
              ("no-edgar", None, "every grader either run scored"),
              ("no-edgar", SEVEN, "the config's seven graders, in its order"),
              ("no-edgar", ("edgar_grounded", "levels_grounded"), "edgar_grounded and levels_grounded only")]
    for arm, graders, what in blocks:
        other = stored[arm]
        print(f"$ tr exp compare {full.record.run_id} {other.record.run_id}   # full -> {arm}, {what}")
        try:
            exp.show(full.record.run_id, other.record.run_id, full, other, graders or exp.scored(full, other))
        except Exception as exc:  # noqa: BLE001 - shown, the check decides
            print(f"compare raised {type(exc).__name__}: {exc}")
        print()
    if offline.HITS:
        print(f"note: your code tried {', '.join(dict.fromkeys(offline.HITS))}: blocked, the week-5 labs open no "
              f"connection and start no process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

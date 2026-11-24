"""$0 observe: regrade a recorded week-1 run with YOUR code. Run it from the tradingresearch repo root.

    uv run python labs/w1/tools/regrade.py observe                       # claim checks: claims_valid, reasons
    uv run python labs/w1/tools/regrade.py observe --grader inferences_grounded    # one line per analysis

The runs are the author's (week-1.md §2 and §6), extracted to labs/w1/data/: each row holds the parsed reply,
the SOURCES names and values of its prompt, and the scores recorded at the time. No model is called.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")
RUNS = ("observe", "prompt-v2-baseline", "prompt-v2-variant")


def load(run: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / f"{run}.jsonl").open()]


def claim_checks(rows: list[dict]) -> None:
    from tradingresearch.analyze import validate_claims

    reasons: Counter[str] = Counter()
    shares, whole, total, crashed = [], 0, 0, []
    for row in rows:
        try:
            kept, rejected = validate_claims(row["output_parsed"], row["values"], "an_regrade")
        except Exception as exc:  # a half-written check_one; show it instead of a traceback
            crashed.append(f"{row['item']} ({type(exc).__name__}: {exc})")
            continue
        total += len(kept) + len(rejected)
        reasons.update(r.reason for r in rejected)
        shares.append(len(kept) / (len(kept) + len(rejected)))
        whole += not rejected
    n = len(shares)
    recorded = {g: sum(r["scores"][g] for r in rows) / len(rows) for g in ("claims_valid", "all_claims_valid")}
    print(f"{rows[0]['run_id']}: {len(rows)} analyses, {total} claims graded with your check_one")
    if n:
        print(f"  yours:    claims_valid={sum(shares) / n:.3f}  all_claims_valid={whole / n:.3f} ({whole} of {n})")
    print(f"  recorded: claims_valid={recorded['claims_valid']:.3f}  all_claims_valid={recorded['all_claims_valid']:.3f}")
    print(f"  rejected {sum(reasons.values())}: " + (", ".join(f"{r}={c}" for r, c in reasons.most_common()) or "none"))
    for line in crashed:
        print(f"  CRASHED  {line}")


def one_grader(rows: list[dict], name: str) -> None:
    from tradingresearch import evals

    # A grader you are still writing is not in GRADERS yet (lab w1l3 registers it last): find its class by id.
    found = evals.GRADERS.get(name) or next(
        (obj for obj in vars(evals).values() if isinstance(obj, type) and getattr(obj, "id", None) == name), None)
    if found is None:
        raise SystemExit(f"no grader with id {name!r} in tradingresearch.evals")
    grader = found()
    if name not in evals.GRADERS:
        print(f"({name} is not in GRADERS yet: experiment configs cannot name it)")
    flagged = 0
    for row in rows:
        sample = SimpleNamespace(parse_status=row["parse_status"], output_parsed=row["output_parsed"])
        score = grader.grade(sample, {"values": row["values"], "names": row["names"]})
        flagged += score.value == 0
        print(f"{row['item']:<16} {score.value:g}  {score.explanation or ''}".rstrip())
    print(f"flagged {flagged} of {len(rows)}  ({name} on {rows[0]['run_id']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", choices=RUNS)
    parser.add_argument("--grader", help="a grader id from tradingresearch.evals.GRADERS")
    args = parser.parse_args()
    rows = load(args.run)
    one_grader(rows, args.grader) if args.grader else claim_checks(rows)


if __name__ == "__main__":
    main()

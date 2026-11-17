"""`tr usage`: cost per run, arm, day or call from the saved run files, then the OpenRouter key's spend (a free read)."""

from __future__ import annotations

from datetime import date

from .. import openrouter, trace, usage
from ..config import require

VIEWS = {"call": usage.by_call, "run": usage.by_run, "arm": usage.by_arm, "day": usage.by_day}


def show(rows: list[tuple[str, ...]], text_columns: int) -> None:
    """Aligned columns: the first `text_columns` left-aligned, the numbers right-aligned."""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        cells = [cell.ljust(w) if i < text_columns else cell.rjust(w) for i, (cell, w) in enumerate(zip(row, widths))]
        print("  ".join(cells).rstrip())


def money(row: usage.Usage) -> str:
    return f"${row.cost_usd:.6f}" + ("*" if row.prices_missing else "")


def cmd_usage(args, cfg) -> None:
    runs = list(trace.iter_runs(cfg.data_dir))
    records = {record.run_id: record for record, _ in runs}
    if args.run and args.run not in records:
        raise SystemExit(f"no saved run {args.run} under {cfg.data_dir / 'runs'}")
    every = [call for _, path in runs for call in trace.calls(path)]
    shown = [call for call in every if (not args.run or call.run_id == args.run)
             and (args.since is None or usage.day(call) >= args.since)]
    rows = VIEWS[args.by](shown)
    if not rows:
        print(f"no model calls under {cfg.data_dir / 'runs'}")
    else:
        everything = usage.total(rows)
        numbers = [(str(r.calls), str(r.tokens_in), str(r.tokens_out), money(r)) for r in [*rows, everything]]
        if args.by == "run":
            labels = [(r.key, trace.kind(records[r.key]), trace.arm(records[r.key]) or "-") for r in rows]
            show([("run", "kind", "arm", "calls", "tokens in", "tokens out", "cost"),
                  *[(*label, *n) for label, n in zip([*labels, ("total", "", "")], numbers)]], 3)
        else:
            show([(args.by, "calls", "tokens in", "tokens out", "cost", "mean latency"),
                  *[(r.key, *n, f"{r.mean_latency_ms:.0f} ms") for r, n in zip([*rows, everything], numbers)]], 1)
        if everything.prices_missing:
            print("* a call in this row has no recorded cost, so the cost is a lower bound")
    if not cfg.openrouter_key:
        print("OPENROUTER_API_KEY is not set: key usage and the reconcile line are skipped (trace tables only)")
        return
    key_usage = openrouter.key_usage(require(cfg.openrouter_key, "OPENROUTER_API_KEY"))
    traced = usage.total(usage.by_run(every)).cost_usd
    print(f"openrouter key usage ${key_usage:.6f}")
    print(f"trace total ${traced:.6f} vs key lifetime ${key_usage:.6f} (the key also paid for runs outside "
          f"{cfg.data_dir / 'runs'}, so the key is ≥ the trace total)")


def register(sub) -> None:
    p = sub.add_parser("usage", help="the OpenRouter key's total spend so far (log it before and after paid runs)",
                       description="cost per run, arm, day or call from the saved run files, then the OpenRouter "
                                   "key's lifetime spend and the two reconciled (free reads)")
    p.add_argument("--by", choices=sorted(VIEWS), default="run", help="group the calls by (default run)")
    p.add_argument("--run", metavar="RUN_ID", help="only this run's calls")
    p.add_argument("--since", type=date.fromisoformat, metavar="DATE",
                   help="only calls on or after this New York date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_usage)

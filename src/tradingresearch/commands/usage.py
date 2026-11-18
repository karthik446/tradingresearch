"""`tr usage`: cost per run, arm, day, call, step, model or tag from the saved run files joined with the cost ledger
(`TR_LEDGER`), then the OpenRouter key's spend (a free read). `--all-dirs` reads every `runs` directory under `data/`
and `data-dev/` and counts the ledger rows whose run file is gone (COST-SPIKE §2.2, §2.4). Anthropic has no key-spend
endpoint: under TR_PROVIDER=anthropic the trace tables are the record."""

from __future__ import annotations

from datetime import date

from .. import config, trace, usage
from ..config import require
from ..providers import openrouter

VIEWS = {"call": usage.by_call, "run": usage.by_run, "arm": usage.by_arm, "day": usage.by_day,
         "step": usage.by_step, "model": usage.by_model, "tag": usage.by_tag}
JOINED = ("step", "tag")  # views keyed by the ledger row of the run
COST_TABLE = ("step", "model")  # views that add items, cache tokens, $ per item, p50/p95 per item (G15-SPIKE §3)
LEDGER_KEYS = {  # the views a ledger-only run (no run file) joins with its totals; the others have no row for it
    "run": lambda row: row.run_id, "step": lambda row: row.step, "tag": usage.tag_key,
    "day": lambda row: usage.day(row).isoformat()}
ROOTS = (config.REPO / "data", config.REPO / "data-dev")  # --all-dirs: every `runs` directory at or below these


def show(rows: list[tuple[str, ...]], text_columns: int) -> None:
    """Aligned columns: the first `text_columns` left-aligned, the numbers right-aligned."""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        cells = [cell.ljust(w) if i < text_columns else cell.rjust(w) for i, (cell, w) in enumerate(zip(row, widths))]
        print("  ".join(cells).rstrip())


def money(row: usage.Usage, usd: float | None = None) -> str:
    return f"${row.cost_usd if usd is None else usd:.6f}" + ("*" if row.prices_missing else "")


def tokens(value: int | None) -> str:
    return "-" if value is None else str(value)


def cost_cells(row: usage.Usage, counted: bool) -> tuple[str, ...]:
    """The cost, and the no-cost count after it when `counted` (a table where a call has no recorded cost)."""
    return (money(row), str(row.calls_without_cost)) if counted else (money(row),)


def arm_label(row: usage.LedgerRow) -> str:
    """`<experiment>:<arm>` of a ledger-only run, as `trace.arm` shows it for a run file; `-` outside an experiment."""
    return f"{row.experiment}:{row.arm}" if row.experiment else "-"


def cmd_usage(args, cfg) -> None:
    ledger = usage.read_ledger(cfg.ledger)
    if args.all_dirs:
        runs, orphans = usage.all_runs(ROOTS, ledger)
        where = " and ".join(str(root / "runs") for root in ROOTS) + " (every runs directory below them)"
    else:
        runs, orphans = list(trace.iter_runs(cfg.data_dir)), []
        where = str(cfg.data_dir / "runs")
    records = {record.run_id: record for record, _ in runs}
    if args.run and args.run not in records and args.run not in {row.run_id for row in orphans}:
        raise SystemExit(f"no saved run {args.run} under {where}")
    by_run = {row.run_id: row for row in ledger}

    def wanted(run_id: str, on: date, step: str, tag: str | None) -> bool:
        return ((not args.run or run_id == args.run) and (args.since is None or on >= args.since)
                and (args.step is None or step == args.step) and (args.tag is None or tag == args.tag))

    every = [call for _, path in runs for call in trace.calls(path)]
    shown = [call for call in every if wanted(
        call.run_id, usage.day(call), by_run[call.run_id].step if call.run_id in by_run else call.step,
        by_run[call.run_id].cost_tag if call.run_id in by_run else None)]
    orphans = [row for row in orphans if wanted(row.run_id, usage.day(row), row.step, row.cost_tag)]
    rows = VIEWS[args.by](shown, by_run) if args.by in JOINED else VIEWS[args.by](shown)
    if args.by in LEDGER_KEYS:
        rows = usage.fold(rows, orphans, LEDGER_KEYS[args.by])
    if not rows:
        print(f"no model calls under {where}")
    else:
        everything = usage.total(shown)
        if args.by in LEDGER_KEYS:
            [everything] = usage.fold([everything], orphans, lambda row: "total")
        if args.by not in COST_TABLE:  # the views that predate step/model keep their total cost: the sum of the rows
            everything = everything.model_copy(update={"cost_usd": round(sum(r.cost_usd for r in rows), 6)})
        counted = everything.calls_without_cost > 0
        cost_head = ("cost", "no-cost") if counted else ("cost",)
        numbers = [(str(r.calls), str(r.tokens_in), str(r.tokens_out), *cost_cells(r, counted))
                   for r in [*rows, everything]]
        if args.by == "run":
            ledger_only = {row.run_id: row for row in orphans}  # kind `ledger`: the run file is gone, totals only
            labels = [(r.key, trace.kind(records[r.key]), trace.arm(records[r.key]) or "-") if r.key in records
                      else (r.key, "ledger", arm_label(ledger_only[r.key])) for r in rows]
            show([("run", "kind", "arm", "calls", "tokens in", "tokens out", *cost_head),
                  *[(*label, *n) for label, n in zip([*labels, ("total", "", "")], numbers)]], 3)
        elif args.by in COST_TABLE:
            show([(args.by, "calls", "items", "tokens in", "cache write", "cache read", "tokens out", *cost_head,
                   "$/item", "p50", "p95"),
                  *[(r.key, str(r.calls), str(r.items), str(r.tokens_in), tokens(r.cache_write), tokens(r.cache_read),
                     str(r.tokens_out), *cost_cells(r, counted), money(r, r.usd_per_item), f"{r.p50_ms} ms",
                     f"{r.p95_ms} ms")
                    for r in [*rows, everything]]], 1)
        else:
            show([(args.by, "calls", "tokens in", "tokens out", *cost_head, "mean latency"),
                  *[(r.key, *n, f"{r.mean_latency_ms:.0f} ms") for r, n in zip([*rows, everything], numbers)]], 1)
        if everything.prices_missing:
            print("* a call in this row has no recorded cost, so the cost is a lower bound")
    if args.by not in LEDGER_KEYS and orphans:
        print(f"{len(orphans)} ledger-only run(s) (run file not found) left out of --by {args.by}: a ledger row has "
              "no per-call detail; --by run, step, tag or day counts them")
    if cfg.provider == "anthropic":
        print("TR_PROVIDER=anthropic: Anthropic has no key-spend endpoint, so its calls are reconciled from the trace "
              "tables above (costs derived from the price table); the Console shows the billed amount")
    if not cfg.openrouter_key:
        print("OPENROUTER_API_KEY is not set: key usage and the reconcile line are skipped (trace tables only)")
        return
    key_usage = openrouter.key_usage(require(cfg.openrouter_key, "OPENROUTER_API_KEY"))
    traced = usage.total(every).cost_usd
    print(f"openrouter key usage ${key_usage:.6f}")
    print(f"trace total ${traced:.6f} vs key lifetime ${key_usage:.6f} (the key also paid for runs outside "
          f"{cfg.data_dir / 'runs'}, so the key is ≥ the trace total)")


def register(sub) -> None:
    p = sub.add_parser("usage", help="the OpenRouter key's total spend so far (log it before and after paid runs)",
                       description="cost per run, arm, day, call, step, model or tag from the saved run files and "
                                   "the cost ledger, then the OpenRouter key's lifetime spend and the two "
                                   "reconciled (free reads)")
    p.add_argument("--by", choices=sorted(VIEWS), default="run", help="group the calls by (default run)")
    p.add_argument("--run", metavar="RUN_ID", help="only this run's calls")
    p.add_argument("--since", type=date.fromisoformat, metavar="DATE",
                   help="only calls on or after this New York date (YYYY-MM-DD)")
    p.add_argument("--step", metavar="STEP", help="only runs of this step (the ledger's, e.g. analyze or worker)")
    p.add_argument("--tag", metavar="TAG", help="only runs saved under this TR_COST_TAG (e.g. worker:G99)")
    p.add_argument("--all-dirs", action="store_true",
                   help="every runs directory under data/ and data-dev/, plus the ledger rows whose run file is "
                        "gone, one row per run id")
    p.set_defaults(func=cmd_usage)

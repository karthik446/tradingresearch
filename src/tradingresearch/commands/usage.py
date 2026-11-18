"""`tr usage`: cost per run, arm, day, call, step, model or tag from the saved run files joined with the cost ledger
(`TR_LEDGER`), then the OpenRouter key's spend (a free read). `--all-dirs` reads every `runs` directory under `data/`
and `data-dev/` and counts the ledger rows whose run file is gone (COST-SPIKE §2.2, §2.4). Anthropic has no key-spend
endpoint: under TR_PROVIDER=anthropic the trace tables are the record.

`--account` (COST-3b, COST-SPIKE 2.5) also reads the account's credits, compares the key's move since the previous
reading with the calls traced since then, appends a `key_reading` row to the ledger, and exits 1 on a settled gap
over `--alert-usd` or a balance under `--min-credit-usd`."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime

from .. import config, slo_check, trace, usage
from ..analyze import append_ledger
from ..config import Settings, require
from ..providers import openrouter

SETTLE_S = 60.0  # a call's cost lands at the key a little after the call: two reads this far apart must agree
SLEEP: Callable[[float], None] = time.sleep  # the settled read's wait; tests replace it
NO_KEY = "OPENROUTER_API_KEY is not set: key usage and the reconcile line are skipped (trace tables only)"

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


def traced_since(every: list[trace.Call], orphans: list[usage.LedgerRow], since: datetime) -> float:
    """The traced cost of the calls started at or after `since`, plus the ledger-only runs created since."""
    calls = sum(call.cost_usd or 0.0 for call in every if call.started_at >= since)
    return round(calls + sum(row.spent_usd for row in orphans if row.created_at >= since), 6)


def account(cfg: Settings, every: list[trace.Call], orphans: list[usage.LedgerRow], *, alert_usd: float,
            min_credit_usd: float, clock: Callable[[], datetime] | None = None,
            sleep: Callable[[float], None] | None = None) -> int:
    """`--account`: the key's counters and the account's balance, the gap since the previous `key_reading` row, and
    that row appended. 1 when a settled gap is over `alert_usd` (two /key reads `SETTLE_S` apart agree, the first at
    least `SETTLE_S` after the last traced call when that time is known) or the balance is under `min_credit_usd`.
    Anthropic has no account endpoint, so the read is skipped and no row is written. The row's `at` is taken after
    the last /key read, so a call that lands during the waits is counted once, in the next window."""
    if cfg.provider == "anthropic":
        print("TR_PROVIDER=anthropic: Anthropic has no account endpoint, so --account is skipped (no key_reading row)")
        return 0
    if not cfg.openrouter_key:
        print(NO_KEY)
        return 0
    key = require(cfg.openrouter_key, "OPENROUTER_API_KEY")
    clock = clock or (lambda: datetime.now(UTC))
    sleep = sleep or SLEEP
    now = clock()
    if every:
        unsettled = SETTLE_S - (now - max(call.started_at for call in every)).total_seconds()
        if unsettled > 0:
            print(f"waiting {unsettled:.0f} s: the last traced call is under {SETTLE_S:.0f} s old")
            sleep(unsettled)
    reading = openrouter.key_reading(key)
    balance = openrouter.credits(key)
    previous = usage.read_key_readings(cfg.ledger)
    print(f"openrouter key usage ${reading.usage:.6f} (today ${reading.usage_daily:.6f}, this week "
          f"${reading.usage_weekly:.6f}); credits ${balance.total_credits:.2f} bought, ${balance.total_usage:.6f} "
          f"used, ${balance.left:.6f} left")
    code = 0
    if not previous:
        print(f"no previous key_reading in {cfg.ledger}: the gap is checked from the next --account run")
    else:
        last = previous[-1]
        traced = traced_since(every, orphans, last.at)
        delta = round(reading.usage - last.usage, 6)
        gap = round(delta - traced, 6)
        print(f"since {last.at.astimezone(UTC):%Y-%m-%d %H:%M:%S}Z: traced ${traced:.6f} vs key delta "
              f"${delta:.6f}, gap ${gap:.6f} (--alert-usd {alert_usd:.3f})")
        if abs(gap) > alert_usd:
            sleep(SETTLE_S)
            again = openrouter.key_reading(key)
            if again.usage == reading.usage:
                print(f"ALERT gap ${gap:.6f} over --alert-usd {alert_usd:.3f}: two /key reads {SETTLE_S:.0f} s apart "
                      "agree, so a call paid for by this key is not in the traces (or a trace cost is wrong); run "
                      "with --all-dirs if this was not, and compare the run files against the OpenRouter activity")
                code = 1
            else:
                print(f"unsettled: the key moved from ${reading.usage:.6f} to ${again.usage:.6f} between two reads "
                      f"{SETTLE_S:.0f} s apart, so the gap is not alerted; rerun --account once the calls have landed")
                reading = again
    if balance.left < min_credit_usd:
        print(f"ALERT credits ${balance.left:.6f} left under --min-credit-usd {min_credit_usd:.2f}: top up before the "
              "next tr daily")
        code = 1
    append_ledger(cfg.ledger, {"kind": usage.KEY_READING, "at": clock().isoformat(), "usage": reading.usage,
                               "usage_daily": reading.usage_daily, "usage_weekly": reading.usage_weekly,
                               "total_credits": balance.total_credits})
    print(f"key_reading appended to {cfg.ledger}")
    return code


def cmd_usage(args, cfg) -> None:
    ledger = usage.read_ledger(cfg.ledger)
    if args.all_dirs:
        runs, unfiltered = usage.all_runs(ROOTS, ledger)
        where = " and ".join(str(root / "runs") for root in ROOTS) + " (every runs directory below them)"
    else:
        runs, unfiltered = list(trace.iter_runs(cfg.data_dir)), []
        where = str(cfg.data_dir / "runs")
    records = {record.run_id: record for record, _ in runs}
    if args.run and args.run not in records and args.run not in {row.run_id for row in unfiltered}:
        raise SystemExit(f"no saved run {args.run} under {where}")
    by_run = {row.run_id: row for row in ledger}

    def wanted(run_id: str, on: date, step: str, tag: str | None) -> bool:
        return ((not args.run or run_id == args.run) and (args.since is None or on >= args.since)
                and (args.step is None or step == args.step) and (args.tag is None or tag == args.tag))

    every = [call for _, path in runs for call in trace.calls(path)]
    shown = [call for call in every if wanted(
        call.run_id, usage.day(call), by_run[call.run_id].step if call.run_id in by_run else call.step,
        by_run[call.run_id].cost_tag if call.run_id in by_run else None)]
    orphans = [row for row in unfiltered if wanted(row.run_id, usage.day(row), row.step, row.cost_tag)]
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
    if args.account:
        if account(cfg, every, unfiltered, alert_usd=args.alert_usd, min_credit_usd=args.min_credit_usd):
            raise SystemExit(1)
        return
    if not cfg.openrouter_key:
        print(NO_KEY)
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
    p.add_argument("--account", action="store_true",
                   help="also read the account's credits, compare the key's move since the previous key_reading "
                        "with the calls traced since, append a key_reading row to the ledger; exit 1 on a settled "
                        "gap over --alert-usd or a balance under --min-credit-usd (OpenRouter only)")
    p.add_argument("--alert-usd", type=float, default=0.025, metavar="USD",
                   help="--account: the gap (key delta minus traced) that exits 1 once settled (default 0.025)")
    p.add_argument("--min-credit-usd", type=float, default=slo_check.min_credit(), metavar="USD",
                   help=f"--account: exit 1 when fewer credits are left (default {slo_check.min_credit():.2f}, "
                        f"{slo_check.CREDIT_DAYS} x the daily cost budget)")
    p.set_defaults(func=cmd_usage)

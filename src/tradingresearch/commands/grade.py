"""`tr grade`: shadows and grades for closed champion and challenger theses (SPIKE §7.1, §7.4), no model call; with
`--judge`, also the P1 judge on graded theses that have no verdict (ADR-003), one paid call each. `--judge --batch`
submits those calls as one OpenRouter batch at the `:batch` price and `--judge --collect <id>` stores its answers
through the same run as sync (G15-SPIKE §1.3; docs/providers.md, "Batch judge")."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from gigai_core import CallBudget
from gigai_core.budget import BudgetExceeded
from gigai_core.providers import ModelRequest, Turn, request_sha256

from .. import evals, grade, journal, providers, reconcile_run, trace
from ..config import require
from ..providers import openrouter
from ..records import Thesis
from .common import alpaca_client
from .reconcile import completed_session

FINAL_FAILED = ("failed", "expired", "cancelled")  # a batch that ended with no results
COST_TOLERANCE_USD = 0.001  # collect's derived sum against the batch's own usage.cost


def cmd_grade(args, cfg) -> None:
    if (args.batch or args.collect) and not args.judge:
        raise SystemExit("--batch and --collect go with --judge")
    if args.collect and args.dry_run:
        raise SystemExit("--collect has no dry run: it polls the batch and stores what came back")
    # a batch's key and model check run first: an empty key exits 2 before grade.run reads bars or writes a grade
    key = batch_key(cfg) if args.collect or (args.batch and not args.dry_run) else ""
    day = completed_session(args.session, datetime.now(UTC))
    conn = journal.connect(cfg.db_path)
    if all(state == "PROPOSED" for _, state in journal.ungraded_theses(conn)):  # nothing filled: no bars to read
        report = grade.run(conn, None, day, dry_run=args.dry_run)
    else:
        with alpaca_client(cfg) as http:
            bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
            report = grade.run(conn, bars, day, dry_run=args.dry_run)
    print("\n".join(grade.render(report)))
    if not args.judge:
        return
    if args.collect:
        lines, code = collect_lines(conn, args.collect, cfg, key)
        print("\n".join(lines))
        if code:
            raise SystemExit(code)
    elif args.batch and not args.dry_run:
        print("\n".join(submit_lines(conn, args, cfg, key)))
    else:
        print("\n".join(judge_lines(conn, args, cfg)))


def judge_lines(conn, args, cfg) -> list[str]:
    """`--judge`: the key, prices and bars are read only when a thesis waits and this is not a dry run."""
    cap = args.judge_max_usd
    if args.dry_run or not grade.to_judge(conn):
        judged = grade.judge(conn, None, None, prices={}, data_dir=cfg.data_dir, max_usd=cap, dry_run=args.dry_run)
        return grade.render_judged(judged, dry_run=args.dry_run, max_usd=cap)
    providers.check_models(cfg, "judge", [evals.JUDGE_MODEL])
    provider = providers.make_provider(cfg, "judge")
    try:
        prices = providers.prices(cfg, "judge", [evals.JUDGE_MODEL])
        with alpaca_client(cfg) as http:
            bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
            judged = grade.judge(conn, bars, provider, prices=prices, data_dir=cfg.data_dir, max_usd=cap)
    finally:
        provider.close()
    return grade.render_judged(judged, dry_run=False, max_usd=cap)


# ---------- the batch judge (G15-SPIKE §1.3) ----------

def batch_key(cfg) -> str:
    """The OpenRouter key, or exit 2 naming the variable (never its value) before any request: a batch is
    OpenRouter's whatever `TR_PROVIDER` says, and the judge's vendor rule refuses Anthropic anyway."""
    try:
        key = require(cfg.openrouter_key, providers.KEYS["openrouter"])
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from None
    providers.check_models(cfg, "judge", [evals.JUDGE_MODEL])
    return key


def batch_price():
    """The judge's `:batch` row of OpenRouter's public price list (no key): the price a batch is billed at."""
    model = f"{evals.JUDGE_MODEL}:batch"
    return openrouter.prices([model])[model]


def head(t: Thesis) -> str:
    return f"{t.ticker:<6} {t.horizon:<5} {t.thesis_id} {t.arm:<10}"


def submit_lines(conn, args, cfg, key: str) -> list[str]:
    """`--judge --batch`: every thesis `tr grade --judge` would judge, as one batch under the same cap; the request
    is the one `run_eval` makes. `<data_dir>/batches/<id>.json` keeps the ids, each prompt's digest, the model and
    the submit time (never the key). Nothing reaches the journal before `--collect`. `key` is `batch_key`'s."""
    cap = args.judge_max_usd
    waiting = grade.to_judge(conn)
    if not waiting:
        return grade.render_judged([], dry_run=False, max_usd=cap)
    price = batch_price()
    budget = CallBudget(max_usd=cap, prices={evals.JUDGE_MODEL: price})  # the estimate at the price billed
    lines, requests = [], []
    with alpaca_client(cfg) as http:
        bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
        for t in waiting:
            try:
                item, settings, _ = evals.judge_item(conn, bars, t.thesis_id)
                request = ModelRequest(settings=settings, turns=(Turn(role="user", content=item.prompt),),
                                       metadata={"item_id": item.id, "repeat_index": 0})
                budget.reserve(request)
            except BudgetExceeded:
                lines.append(f"{head(t)}  not submitted: the ${cap:.2f} cap is spent; next run")
                continue
            except Exception as exc:
                lines.append(f"{head(t)}  not submitted: {type(exc).__name__}: {exc}")
                continue
            requests.append(request)
            lines.append(f"{head(t)}  submitted")
    if not requests:
        return [*lines, "judge batch: nothing submitted"]
    batch_id = openrouter.submit_batch(key, evals.JUDGE_MODEL, requests)
    record = {"batch_id": batch_id, "model": evals.JUDGE_MODEL, "endpoint": openrouter.BATCH_ENDPOINT,
              "submitted_at": datetime.now(UTC).isoformat(),
              "items": {r.metadata["item_id"]: request_sha256(r) for r in requests}}
    path = cfg.data_dir / "batches" / f"{batch_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return [*lines, f"judge batch {batch_id}: {len(requests)} submitted at the {price.model} price (worst case "
                    f"${budget.spent_usd:.6f}, cap ${cap:.2f}); nothing stored until "
                    f"`tr grade --judge --collect {batch_id}` (record {path})"]


def collect_lines(conn, batch_id: str, cfg, key: str) -> tuple[list[str], int]:
    """`--judge --collect <id>`: poll once. Not final: "still <status>", exit 0. Failed, expired or cancelled: exit
    1, nothing stored. Completed: each submitted thesis runs the sync `run_eval` on a `BatchReplay`, then the derived
    cost sum is printed next to the batch's `usage.cost`; exit 1 when they differ by more than $0.001. `key` is
    `batch_key`'s."""
    if not openrouter.CUSTOM_ID.fullmatch(batch_id):
        raise SystemExit(f"not a batch id: {batch_id!r}")
    path = cfg.data_dir / "batches" / f"{batch_id}.json"
    if not path.is_file():
        raise SystemExit(f"no batch record {path}: collect from the TR_DATA_DIR that submitted it")
    record = json.loads(path.read_text())
    batch = openrouter.get_batch(key, batch_id)
    status = batch.get("status")
    if status in FINAL_FAILED:
        return [f"judge batch {batch_id}: {status}: {(batch.get('error') or {}).get('message')}; nothing stored"], 1
    if status != "completed" or batch.get("results") is None:  # a completed batch's results can lag its status
        return [f"judge batch {batch_id}: still {status}" + (" (results not ready)" if status == "completed" else "")], 0
    price = batch_price()
    replay = providers.BatchReplay(batch["results"], price, record["items"])
    judged: list[grade.Judged] = []
    with alpaca_client(cfg) as http:
        bars = reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed)
        for thesis_id in record["items"]:
            t = journal.get(conn, Thesis, thesis_id)
            if journal.judge_verdict(conn, thesis_id) is not None:
                judged.append(grade.Judged(t, error="already judged (a sync run or an earlier collect)"))
                continue
            before = grade.run_files(cfg.data_dir)
            try:
                item, settings, judge = evals.judge_item(conn, bars, thesis_id)
                score = evals.judge_run(conn, item, settings, judge, replay, budget=CallBudget(),  # paid at submit
                                        data_dir=cfg.data_dir)
                one = grade.Judged(t, verdict=score.answer, reason=score.explanation)
            except Exception as exc:  # one thesis's failure (an error entry, no verdict) never stops the rest
                one = grade.Judged(t, error=f"{type(exc).__name__}: {exc}")
            cost = sum(trace.header(p).spent_usd for p in grade.run_files(cfg.data_dir) - before)
            judged.append(grade.Judged(one.thesis, one.verdict, one.reason, cost, one.error))
    lines = [grade.render_judged([j], dry_run=False, max_usd=0.0)[0] for j in judged]
    costs = [providers.entry_cost(entry, price) for entry in batch["results"]]
    derived = sum(c for c in costs if c is not None)
    unpriced = sum(c is None and not entry.get("error") for c, entry in zip(costs, batch["results"], strict=True))
    reported = (batch.get("usage") or {}).get("cost")
    done = sum(j.verdict is not None for j in judged)
    lines.append(f"judge batch {batch_id}: {done} judged, {len(judged) - done} not judged; derived cost "
                 f"${derived:.6f} (tokens x {price.model} price over {len(costs)} entries"
                 + (f", {unpriced} without usage" if unpriced else "") + ") vs batch usage.cost "
                 + (f"${reported:.6f}" if reported is not None else "missing"))
    if reported is None or abs(derived - reported) > COST_TOLERANCE_USD:
        lines.append(f"judge batch {batch_id}: the costs differ by more than ${COST_TOLERANCE_USD}; the run files "
                     "hold the derived costs")
        return lines, 1
    return lines, 0


def register(sub) -> None:
    p = sub.add_parser("grade", help="shadow baselines and grades for closed theses (a paid P1 judge with --judge)")
    p.add_argument("--session", help="a completed session (default: the latest, after 16:15 ET)")
    p.add_argument("--dry-run", action="store_true", help="print what would be created or graded; write nothing")
    p.add_argument("--judge", action="store_true",
                   help=f"also run the P1 judge ({evals.JUDGE_MODEL}, one paid call per graded thesis without a "
                        "verdict; off by default)")
    p.add_argument("--judge-max-usd", type=float, default=grade.JUDGE_MAX_USD,
                   help="dollar cap for the whole judge run (default: %(default)s)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--batch", action="store_true",
                      help="with --judge: submit the judge calls as one OpenRouter batch at the :batch price; "
                           "nothing is stored until --collect")
    mode.add_argument("--collect", metavar="BATCH_ID",
                      help="with --judge: poll a submitted batch once and store its verdicts when it is complete")
    p.set_defaults(func=cmd_grade)

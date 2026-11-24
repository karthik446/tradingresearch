"""The `tr` command. Week 1: sessions, bars, facts, snapshot, analyze, check, exp run."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from . import lab

try:  # a lab stub rewrites analyze.py and friends: `tr lab` must still run while they are broken
    from gigai_core import open_run
    from gigai_core.comparison import ComparisonRefused

    from . import alpaca, analyze as an, experiment, journal, openrouter, sessions
    from .config import require, settings
    from .edgar import Edgar, latest_frames
    from .records import Analysis
except Exception as err:  # noqa: BLE001  re-raised by main() for every command but `lab`
    _IMPORT_ERROR: Exception | None = err
else:
    _IMPORT_ERROR = None


def session_arg(text: str | None) -> date:
    day = date.fromisoformat(text) if text else sessions.last_completed(datetime.now(UTC))
    if not sessions.is_session(day):
        raise SystemExit(f"{day} is not an NYSE session")
    return day


def edgar_client(cfg) -> Edgar:
    return Edgar(require(cfg.sec_user_agent, "TR_SEC_USER_AGENT"), cfg.data_dir / "edgar")


def alpaca_client(cfg):
    return alpaca.client(require(cfg.alpaca_key_id, "APCA_API_KEY_ID"), require(cfg.alpaca_secret, "APCA_API_SECRET_KEY"))


def cmd_sessions(args, cfg) -> None:
    end = session_arg(args.session)
    for day in sessions.recent(args.count, end):
        o, c = sessions.open_close(day)
        print(day, o.strftime("%H:%MZ"), c.strftime("%H:%MZ"))


def cmd_bars(args, cfg) -> None:
    end = session_arg(args.session)
    start = sessions.recent(args.sessions, end)[0]
    conn = journal.connect(cfg.db_path)
    with alpaca_client(cfg) as http:
        frame = alpaca.daily_bars(http, args.tickers, start, end, feed=cfg.feed)
    for ticker in args.tickers:
        rows = frame[frame["ticker"] == ticker]
        alpaca.store_daily(conn, rows, feed=cfg.feed, adjustment="split")
        print(f"{ticker}: {len(rows)} daily bars {start}..{end} feed={cfg.feed}")
    print(frame.groupby("ticker").tail(2).to_string(index=False))


def cmd_facts(args, cfg) -> None:
    edgar = edgar_client(cfg)
    facts = edgar.company_facts(args.ticker)
    print(f"{args.ticker} cik={edgar.cik(args.ticker)} {facts['entityName']}")
    for row in latest_frames(facts, args.concept, args.kind, args.count, args.unit):
        print(f"{row['frame']:<10} {row['val']:>16,} {row['start'] if 'start' in row else '':>10} {row['end']} "
              f"fy={row['fy']} fp={row['fp']} {row['form']} filed={row['filed']}")


def context_for(args, cfg):
    day = session_arg(args.session)
    conn = journal.connect(cfg.db_path)
    with alpaca_client(cfg) as http:
        ctx = an.gather(conn, http, edgar_client(cfg), args.ticker, day, cfg.data_dir, cfg.feed)
    return conn, ctx


def cmd_snapshot(args, cfg) -> None:
    _, ctx = context_for(args, cfg)
    if args.prompt:
        print(an.render(ctx))
        print(f"\ncontext_tokens={an.context_tokens(an.system_prompt(an.DEFAULT_PROMPT), an.render(ctx))}")
        return
    print(json.dumps(ctx.snapshot.model_dump(mode="json"), indent=1))


def cmd_analyze(args, cfg) -> None:
    key = require(cfg.openrouter_key, "OPENROUTER_API_KEY")
    conn, ctx = context_for(args, cfg)
    provider = openrouter.OpenRouter(key)
    try:
        result = an.analyze(conn, ctx, provider, model=args.model, max_usd=args.max_usd,
                            prices=openrouter.prices([args.model]), data_dir=cfg.data_dir, prompt_version=args.prompt)
    finally:
        provider.close()
    a = result.analysis
    print(f"analysis {a.analysis_id}  {a.ticker} {a.session}  prompt={a.prompt_version}  model={a.model}  "
          f"route={a.provider_route}")
    print(f"context_tokens={a.context_tokens}  input_hash={a.input_hash[:19]}…  spent=${result.spent_usd:.4f}")
    print(f"run={result.run_path}")
    for c in a.claims:
        shown = c.text.replace("{value}", an.plain(c.value)) if c.value is not None else c.text
        refs = ",".join(c.source_ids or c.derived_from)
        print(f"  [{c.tag:<9}] {shown}  <- {refs}")
    print(f"valid {len(a.claims)}, rejected {len(result.rejected)}")
    for r in result.rejected:
        print(f"  REJECTED {r.claim}: {r.reason}: {r.detail}")


def source_table(prompt: str) -> dict[str, tuple[str, str, str]]:
    """source_id -> (name, value as shown, unit), read back from the SOURCES table in the stored prompt."""
    rows = {}
    for line in prompt.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 4 and cells[0].startswith("src_"):
            rows[cells[0]] = (cells[1], cells[2], cells[3])
    return rows


def cmd_check(args, cfg) -> None:
    """Every claim the model wrote, kept or rejected, beside the source values it cites."""
    conn = journal.connect(cfg.db_path)
    a = journal.get(conn, Analysis, args.analysis_id)
    run = open_run(cfg.data_dir / "runs" / f"{a.run_id}.jsonl")
    sample = next(s for s in run.samples if s.trace_id == a.sample_trace_id)
    item = run.items[sample.item_id]
    table = source_table(item.prompt)
    _, rejected = an.validate_claims(sample.output_parsed, item.expected["values"], "an_check")
    why = {r.claim: f"REJECTED {r.reason}: {r.detail}" for r in rejected}
    print(f"{a.analysis_id}  {a.ticker} {a.session}  prompt={a.prompt_version}  run={a.run_id}  "
          f"trace={a.sample_trace_id}")
    for raw in (sample.output_parsed or {}).get("claims", []):
        value = "" if raw.get("value") is None else f"  value={an.plain(raw['value'])} {raw.get('unit') or ''}"
        print(f"{raw.get('id')} [{raw.get('tag')}] {why.get(raw.get('id'), 'ok')}")
        print(f"    text: {raw.get('text')}{value}")
        for sid in raw.get("source_ids") or []:
            name, shown, unit = table.get(sid, ("NOT IN TABLE", "-", ""))
            print(f"    src:  {sid} {name} = {shown} {unit}".rstrip())
        if raw.get("derived_from"):
            print(f"    from: {', '.join(raw['derived_from'])} ({raw.get('steps')})")
    print(f"kept {len(a.claims)}, rejected {len(rejected)}")


def cmd_exp_run(args, cfg) -> None:
    config = experiment.load(Path(args.config))
    key = require(cfg.openrouter_key, "OPENROUTER_API_KEY")
    conn = journal.connect(cfg.db_path)
    with alpaca_client(cfg) as http:
        edgar = edgar_client(cfg)
        contexts = [an.gather(conn, http, edgar, t, s, cfg.data_dir, cfg.feed)
                    for s in config.sessions for t in config.tickers]
    print(f"experiment {config.name}: {len(contexts)} ticker-days x {len(config.arms)} arm(s), "
          f"graders {', '.join(config.graders)}, cap ${config.max_usd_per_arm:.2f}/arm")
    provider = openrouter.OpenRouter(key)
    try:
        results = experiment.run_arms(conn, config, contexts, provider,
                                      openrouter.prices(sorted({arm.model for arm in config.arms})), cfg.data_dir)
    finally:
        provider.close()
    for r in results:
        failed = sum(1 for s in r.run.samples if s.outcome != "succeeded")
        scores = "  ".join(f"{g}={m:.3f} (n={n})" for g, (m, n) in experiment.means(r.run).items())
        print(f"arm {r.arm.name:<10} prompt={r.arm.prompt} run={r.run.record.run_id} "
              f"spent=${r.run.record.spent_usd:.4f} failed={failed} analyses={r.analyses}")
        print(f"    {scores}")
    baseline = results[0]
    for r in results[1:]:
        try:
            comparison = experiment.compare(baseline.run, r.run, config.graders)
        except ComparisonRefused as exc:
            print(f"compare {baseline.arm.name} -> {r.arm.name} refused: {exc}")
            continue
        print(f"compare {baseline.arm.name} -> {r.arm.name}: {comparison.items} items, {comparison.clusters} clusters")
        for m in comparison.metrics:
            ci = f"[{m.ci.lower:+.3f}, {m.ci.upper:+.3f}] ({m.ci.level:.0%})" if m.ci else "none"
            mde = "-" if m.minimum_detectable is None else f"{m.minimum_detectable:.3f}"
            print(f"    {m.metric:<18} {m.mean_a:.3f} -> {m.mean_b:.3f}  diff {m.difference:+.3f}  CI {ci}  "
                  f"{m.test} p={m.p:.3g}  mde={mde}")


def cmd_usage(args, cfg) -> None:
    print(f"openrouter key usage ${openrouter.key_usage(require(cfg.openrouter_key, 'OPENROUTER_API_KEY')):.6f}")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["lab"]:  # local only: before the .env read and the data dir, and without the modules above
        raise SystemExit(lab.main(argv[1:]))
    if _IMPORT_ERROR is not None:
        raise _IMPORT_ERROR
    parser = argparse.ArgumentParser(prog="tr", description="tradingresearch: educational, not investment advice")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("lab", help=lab.HELP + " (`tr lab -h`)")

    p = sub.add_parser("sessions", help="NYSE sessions ending at a date")
    p.add_argument("--session")
    p.add_argument("--count", type=int, default=5)
    p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("bars", help="fetch and store daily bars")
    p.add_argument("tickers", nargs="+")
    p.add_argument("--session")
    p.add_argument("--sessions", type=int, default=300)
    p.set_defaults(func=cmd_bars)

    p = sub.add_parser("facts", help="framed EDGAR facts for one concept")
    p.add_argument("ticker")
    p.add_argument("--concept", default="RevenueFromContractWithCustomerExcludingAssessedTax")
    p.add_argument("--kind", choices=["year", "quarter", "instant"], default="quarter")
    p.add_argument("--unit", default="USD")
    p.add_argument("--count", type=int, default=4)
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("snapshot", help="indicators, levels and regime for one ticker-day")
    p.add_argument("ticker")
    p.add_argument("--session")
    p.add_argument("--prompt", action="store_true", help="print the analyze prompt instead")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("analyze", help="write a checked Analysis for one ticker-day (paid call)")
    p.add_argument("ticker")
    p.add_argument("--session")
    p.add_argument("--prompt", default=an.DEFAULT_PROMPT, help="prompt version: prompts/<version>.txt")
    p.add_argument("--model", default=an.DEFAULT_MODEL)
    p.add_argument("--max-usd", type=float, default=0.25)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("check", help="every claim of an analysis beside the source values it cites")
    p.add_argument("analysis_id")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("exp", help="experiments as config")
    exp = p.add_subparsers(dest="exp_command", required=True)
    p = exp.add_parser("run", help="run every arm of a config on the same ticker-days, then compare (paid calls)")
    p.add_argument("config", help="an experiments/*.toml file")
    p.set_defaults(func=cmd_exp_run)

    p = sub.add_parser("usage", help="the OpenRouter key's total spend so far (log it before and after paid runs)")
    p.set_defaults(func=cmd_usage)

    args = parser.parse_args(argv)
    cfg = settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    args.func(args, cfg)

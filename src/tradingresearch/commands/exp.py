"""`tr exp run`: every arm of an experiment config on the same ticker-days, then compare (paid calls)."""

from __future__ import annotations

from pathlib import Path

from gigai_core.comparison import ComparisonRefused

from .. import analyze as an, experiment, journal, openrouter
from ..config import require
from .common import alpaca_client, edgar_client


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


def register(sub) -> None:
    p = sub.add_parser("exp", help="experiments as config")
    exp = p.add_subparsers(dest="exp_command", required=True)
    p = exp.add_parser("run", help="run every arm of a config on the same ticker-days, then compare (paid calls)")
    p.add_argument("config", help="an experiments/*.toml file")
    p.set_defaults(func=cmd_exp_run)

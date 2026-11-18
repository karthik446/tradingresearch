"""`tr exp run`: every arm of an experiment config on the same ticker-days, then compare (paid calls);
`tr exp compare`: the same compare block for two stored runs ($0)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gigai_core import Run, open_run
from gigai_core.comparison import ComparisonRefused

from .. import analyze as an, experiment, journal, providers
from .common import alpaca_client, edgar_client


def cmd_exp_run(args, cfg) -> None:
    config = experiment.load(Path(args.config))
    models = sorted({arm.model for arm in config.arms})
    providers.check_models(cfg, "experiment", models)
    if cfg.provider != "openrouter" and (pinned := [arm.name for arm in config.arms if arm.provider]):
        raise SystemExit(f"{config.name}: arm {', '.join(pinned)} has an OpenRouter `provider` table, which "
                         f"TR_PROVIDER={cfg.provider} cannot carry (set TR_PROVIDER=openrouter)")
    provider = providers.make_provider(cfg, "experiment")
    conn = journal.connect(cfg.db_path)
    with alpaca_client(cfg) as http:
        edgar = edgar_client(cfg)
        contexts = [an.gather(conn, http, edgar, t, s, cfg.data_dir, cfg.feed)
                    for s in config.sessions for t in config.tickers]
    print(f"experiment {config.name}: {len(contexts)} ticker-days x {len(config.arms)} arm(s), "
          f"graders {', '.join(config.graders)}, cap ${config.max_usd_per_arm:.2f}/arm, provider {cfg.provider}")
    try:
        results = experiment.run_arms(conn, config, contexts, provider, providers.prices(cfg, "experiment", models),
                                      cfg.data_dir)
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
        show(baseline.arm.name, r.arm.name, baseline.run, r.run, config.graders)


def cmd_exp_compare(args, cfg) -> None:
    """Two stored runs compared as `tr exp run` compares its arms, read back from `data_dir/runs`; no call."""
    a, b = (stored(cfg.data_dir, run_id) for run_id in (args.run_a, args.run_b))
    graders = args.graders.split(",") if args.graders else scored(a, b)
    show(args.run_a, args.run_b, a, b, graders)


def stored(data_dir: Path, run_id: str) -> Run:
    """A run as `analyze.save` wrote it."""
    path = data_dir / "runs" / f"{run_id}.jsonl"
    if not path.exists():
        raise SystemExit(f"no stored run {run_id} ({path} not found)")
    return open_run(path)


def scored(a: Run, b: Run) -> list[str]:
    """Every grader either run scored, in the order each was first written (so `--graders` sets the order)."""
    return list(dict.fromkeys(score.grader_id for score in (*a.scores, *b.scores)))


def show(label_a: str, label_b: str, a: Run, b: Run, graders: Sequence[str]) -> None:
    """The compare block: B against A per grader, each skipped grader with its reason, or the refusal."""
    try:
        compared = experiment.compare(a, b, graders)
    except ComparisonRefused as exc:
        print(f"compare {label_a} -> {label_b} refused: {exc}")
        return
    comparison = compared.comparison
    print(f"compare {label_a} -> {label_b}: {comparison.items} items, {comparison.clusters} clusters")
    for why in compared.skipped:
        print(f"    skipped {why}")
    for m in comparison.metrics:
        ci = f"[{m.ci.lower:+.3f}, {m.ci.upper:+.3f}] ({m.ci.level:.0%})" if m.ci else "none"
        mde = "-" if m.minimum_detectable is None else f"{m.minimum_detectable:.3f}"
        print(f"    {m.metric:<18} {m.mean_a:.3f} -> {m.mean_b:.3f}  diff {m.difference:+.3f}  CI {ci}  "
              f"{m.test} p={m.p:.3g}  mde={mde}  n={m.items}")


def register(sub) -> None:
    p = sub.add_parser("exp", help="experiments as config")
    exp = p.add_subparsers(dest="exp_command", required=True)
    p = exp.add_parser("run", help="run every arm of a config on the same ticker-days, then compare (paid calls)")
    p.add_argument("config", help="an experiments/*.toml file")
    p.set_defaults(func=cmd_exp_run)
    p = exp.add_parser("compare", help="compare two stored runs as `exp run` compares its arms (no calls)")
    p.add_argument("run_a", help="the baseline run id")
    p.add_argument("run_b", help="the run compared against it")
    p.add_argument("--graders", help="comma-separated grader ids (default: every grader either run scored)")
    p.set_defaults(func=cmd_exp_compare)

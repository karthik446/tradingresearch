"""`tr exp run`: every arm of an experiment config on the same ticker-days, then compare (paid calls); a pipeline
arm's theses stay in memory, each later clean pipeline arm gets a drift line against the first clean one (and a
false-rejection count when it has guards), and each inject arm gets a paired verdict against it. `tr exp compare`:
the same compare block for two stored runs ($0)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from gigai_core import Run, open_run
from gigai_core.comparison import ComparisonRefused

from .. import analyze as an, experiment, guards, journal, providers
from .common import alpaca_client, edgar_client


def cmd_exp_run(args, cfg) -> None:
    config = experiment.load(Path(args.config))
    models = experiment.models(config)  # every arm's model, route step models and fallback: checked, then priced
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
    for arm in config.arms:  # the models each arm asks: a pipeline arm's per step (its `route`) and its fallback
        steps = (f"analyze {arm.analyze_model}  thesis {arm.thesis_model}  fallback {arm.route.fallback or 'none'}"
                 if arm.kind == "pipeline" else f"model {arm.model}")
        print(f"    arm {arm.name}: {steps}" + (f"  cache {arm.cache}" if arm.cache else ""))
    try:
        results = experiment.run_arms(conn, config, contexts, provider, providers.prices(cfg, "experiment", models),
                                      cfg.data_dir)
    finally:
        provider.close()
    records, _ = guards.read_audit(cfg.data_dir)
    for r in results:
        runs = (r.run, r.theses) if r.theses else (r.run,)
        failed = sum(1 for run in runs for s in run.samples if s.outcome != "succeeded")
        scores = "  ".join(f"{g}={m:.3f} (n={n})" for g, (m, n) in experiment.means(r.run).items())
        theses = f" theses={r.theses.record.run_id}" if r.theses else ""
        print(f"arm {r.arm.name:<10} prompt={r.arm.prompt} run={r.run.record.run_id}{theses} "
              f"spent=${sum(run.record.spent_usd for run in runs):.4f} failed={failed} analyses={r.analyses}")
        print(f"    {scores}")
        print(f"    audit {decisions(records, r)}")
    baseline = results[0]
    for r in results[1:]:
        if not r.arm.inject:  # an injected item has its own id, so it pairs with no analyze item
            show(baseline.arm.name, r.arm.name, baseline.run, r.run, config.graders)
    injected = [r for r in results if r.arm.inject]
    cleans = [r for r in results if r.arm.kind == "pipeline" and not r.arm.inject]
    if injected and not cleans:
        print(f"no clean pipeline arm: arm(s) {', '.join(r.arm.name for r in injected)} have nothing to pair against")
        return
    clean = cleans[0] if cleans else None
    for r in cleans[1:]:
        found = experiment.drift(clean, r)
        print(f"drift {clean.arm.name} -> {r.arm.name}: changed {found.attack_success:.3f}  CI {interval(found)}  "
              f"n={found.n}")
        if r.arm.guards:
            hit, n = false_rejections(records, r)
            print(f"    false rejection {hit}/{n} clean items had a row dropped or flagged")
    for r in injected:
        found = experiment.verdict(config, clean, r)
        if found is None:
            print(f"{experiment.RESISTED} not registered (week 7 learner part)")
            return
        print(f"verdict {clean.arm.name} -> {r.arm.name}: attack success {found.attack_success:.3f}  "
              f"CI {interval(found)}  n={found.n}")


def interval(found: experiment.Verdict) -> str:
    """A verdict's or drift's interval as `tr exp run` prints it, or why there is none."""
    if found.ci is None:
        return f"none ({found.clusters} clusters < {experiment.MIN_CLUSTERS})"
    return f"[{found.ci.lower:.3f}, {found.ci.upper:.3f}] ({found.ci.level:.0%}, cluster bootstrap)"


def false_rejections(records: list[guards.AuditRecord], r: experiment.ArmResult) -> tuple[int, int]:
    """A clean guards arm's ticker-days with at least one fetched row dropped or flagged in `audit.jsonl` (its own
    run ids, as `decisions` counts them), out of its items; counts only, never a row's text."""
    runs = {r.run.record.run_id} | ({r.theses.record.run_id} if r.theses else set())
    days = {(rec.ticker, rec.session) for rec in records if rec.run_id in runs and rec.arm == r.arm.name
            and rec.stage == "fetched" and rec.decision in ("drop", "flag")}
    return len(days), len(r.run.items)


def decisions(records: list[guards.AuditRecord], r: experiment.ArmResult) -> str:
    """An arm's guard decisions in `audit.jsonl`, by the arm's run ids (analyze and, for a pipeline arm, thesis)."""
    runs = {r.run.record.run_id} | ({r.theses.record.run_id} if r.theses else set())
    counts = Counter(rec.decision for rec in records if rec.run_id in runs and rec.arm == r.arm.name)
    return f"drop={counts['drop']} flag={counts['flag']} reject={counts['reject']}"


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

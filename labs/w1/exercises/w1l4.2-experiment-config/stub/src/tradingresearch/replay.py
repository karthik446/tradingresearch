"""Replay the author's recorded prompt-v2 run against your prompt and config (week 1, lab w1l4). No model is called.

    uv run python -m tradingresearch.replay prompt prompts/analyze-1.txt prompts/analyze-2.txt   # w1l4.1
    uv run python -m tradingresearch.replay experiment experiments/prompt-v2.toml               # w1l4.2

What a replay can and cannot show. The replies are the author's, recorded when analyze-1 and analyze-2 ran
(labs/w1/data/prompt-v2-*.jsonl). A recorded reply cannot react to a prompt you change: editing analyze-2.txt
changes which recorded failures your rules name, not what the model wrote. Only a paid run (`tr exp run`) shows
what your prompt does. The rules, the arms, the items and the graders are yours, so that part of the output moves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from gigai_core.graders.protocol import CannotGrade

from .analyze import PROMPTS_DIR
from .evals import InferencesGrounded
from .evals import graders as registry
from .experiment import load
from .taxonomy import code_classes

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TR_LAB_DATA") or REPO / "labs" / "w1" / "data")
RECORDED = {"analyze-1": DATA / "prompt-v2-baseline.jsonl", "analyze-2": DATA / "prompt-v2-variant.jsonl"}
AUTHOR_SHA = {  # sha256 of the author's prompt text (stripped) when the recorded replies were made
    "analyze-1": "27728ab29636a946944474c47a8e88061fe87eead9476942170ac7eab04e7a17",
    "analyze-2": "e38f8dbca0a5308d3d593d47ea6bdc44ce4dcd1ba54241a0cf2727291e9481cf",
}
CLASS_WORDS = {  # target class (the ids lab w1l2 fixes) -> options; a rule names the class if it has every word of one
    "window_name": [("window",), ("200-day",), ("20-day",)],
    "inference_wider": [("inference", "cite"), ("derived_from", "cite")],
    "opinion_cites": [("opinion", "derived_from"), ("opinion", "source_ids")],
    "label_in_value": [("placeholder",), ("label", "text")],
}
HONEST = ("recorded replies: they cannot react to a prompt you change; only a paid run (`tr exp run`) shows what "
          "your prompt does")


def load_rows(path: Path) -> list[dict]:
    """One recorded reply per line: item, run_id, parse_status, output_parsed, values, names, scores."""
    return [json.loads(line) for line in Path(path).open()]


def score(grader, row: dict) -> float | None:
    """One grader's score for one recorded reply, the way the runner grades it; None when it cannot grade."""
    sample = SimpleNamespace(parse_status=row["parse_status"], output_parsed=row["output_parsed"])
    try:
        return grader.grade(sample, {"values": row["values"], "names": row["names"]}).value
    except CannotGrade:
        return None


def failures(path: Path) -> dict[str, set[str]]:
    """Target class -> the items whose recorded reply shows it, found by code."""
    rows, found = load_rows(path), code_classes(path)
    opinion_cites = {r["item"] for r in rows for c in (r["output_parsed"] or {}).get("claims") or []
                     if c.get("tag") == "opinion" and (c.get("derived_from") or c.get("source_ids"))}
    return {"window_name": set(found["window_name"]),
            "inference_wider": {r["item"] for r in rows if score(InferencesGrounded(), r) == 0},
            "opinion_cites": opinion_cites,
            "label_in_value": set(found["label_in_value"])}


def rule_targets(base: str, variant: str) -> dict[str, list[str]]:
    """The rules a variant prompt adds to its base, under the target class each names.

    A rule is a line of variant, stripped, that is not blank and is no line of base (compared stripped). A rule names
    a class when, lowercased, it contains every word of one of the class's options in CLASS_WORDS. Every class of
    CLASS_WORDS is a key, with [] when no rule names it; a rule that names two classes is under both. Rules keep the
    variant's order.
    """
    old = {line.strip() for line in base.splitlines()}
    rules = [line.strip() for line in variant.splitlines() if line.strip() and line.strip() not in old]
    return {name: [rule for rule in rules if any(all(word in rule.lower() for word in words) for words in options)]
            for name, options in CLASS_WORDS.items()}


def replay(config: Path, recorded: dict[str, Path]) -> dict[str, dict[str, float]]:
    """Grade recorded replies the way your config's run would: arm name -> grader id -> mean score.

    An arm's replies are recorded[arm.prompt]; an arm whose prompt has no recording is left out. Only the config's
    items count (f"{ticker}:{session}" for each ticker and session). Each reply is graded by each of the config's
    graders with score(); a mean is over the replies the grader could grade (score is not None), and a grader that
    could grade none is left out.
    """
    # TODO(w1l4.2) load(config) is the runner's pre-flight; grade each arm's recorded replies with the config's graders.
    return {}


# ---------- the command ----------

def sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def show_prompt(base_path: Path, variant_path: Path) -> None:
    targets = rule_targets(base_path.read_text(), variant_path.read_text())
    if not targets:
        print("rule_targets returned nothing: write it first (TODO(w1l4.1))")
        return
    seen, n = failures(RECORDED["analyze-1"]), len(load_rows(RECORDED["analyze-1"]))
    named = [name for name in CLASS_WORDS if targets.get(name)]
    print(f"{variant_path} against {base_path}: rules for {len(named)} of {len(CLASS_WORDS)} target classes")
    for name in CLASS_WORDS:
        rules = targets.get(name, [])
        print(f"  {name:<16} in {len(seen[name]):>2} of {n} baseline replies   {f'{len(rules)} rule(s)' if rules else 'NO RULE'}")
        for rule in rules:
            print(f"      + {rule}")
    failing = {item for items in seen.values() for item in items}
    covered = [item for item in failing if all(item not in seen[name] for name in CLASS_WORDS if name not in named)]
    print(f"  {len(covered)} of {len(failing)} baseline replies with a target failure have a rule for each failure")
    after = failures(RECORDED["analyze-2"])
    print("  the author's analyze-2 replies, for reference: "
          + ", ".join(f"{name} in {len(after[name])}" for name in CLASS_WORDS))
    if sha(variant_path.read_text()) == AUTHOR_SHA["analyze-2"]:
        print("  (your variant is the author's analyze-2 word for word)")
    print(f"  {HONEST}")


def show_experiment(path: Path) -> None:
    cfg = load(path)
    items = len(cfg.tickers) * len(cfg.sessions)
    print(f"{path}: experiment {cfg.name}, {len(cfg.arms)} arm(s) x {items} ticker-days = {len(cfg.arms) * items} "
          f"calls, {len(cfg.tickers)} clusters")
    print(f"  worst case ${cfg.max_usd_per_arm * len(cfg.arms):.2f} ({len(cfg.arms)} x ${cfg.max_usd_per_arm:.2f} cap)")
    got = replay(path, RECORDED)
    if not got:
        print("replay returned nothing: write it first (TODO(w1l4.2))")
        return
    print(f"  {'arm':<10} {'prompt':<10} " + " ".join(f"{g:>19}" for g in cfg.graders) + "  recorded run")
    for arm in cfg.arms:
        if arm.name not in got:
            print(f"  {arm.name:<10} {arm.prompt:<10} no recording of {arm.prompt}")
            continue
        means = got[arm.name]
        cells = " ".join(f"{means[g]:>19.3f}" if g in means else f"{'-':>19}" for g in cfg.graders)
        print(f"  {arm.name:<10} {arm.prompt:<10} {cells}  {load_rows(RECORDED[arm.prompt])[0]['run_id']}")
    for arm in cfg.arms:
        prompt = PROMPTS_DIR / f"{arm.prompt}.txt"
        if arm.prompt in AUTHOR_SHA and prompt.exists() and sha(prompt.read_text()) != AUTHOR_SHA[arm.prompt]:
            print(f"  prompts/{arm.prompt}.txt is not the author's: the {arm.name} row grades the author's replies, "
                  "not replies to your prompt")
    print(f"  {HONEST}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    prompt = sub.add_parser("prompt", help="the rules your variant adds and the recorded failures they name")
    prompt.add_argument("base", nargs="?", type=Path, default=PROMPTS_DIR / "analyze-1.txt")
    prompt.add_argument("variant", nargs="?", type=Path, default=PROMPTS_DIR / "analyze-2.txt")
    experiment = sub.add_parser("experiment", help="your config's arms and graders over the recorded replies")
    experiment.add_argument("config", nargs="?", type=Path, default=Path("experiments/prompt-v2.toml"))
    args = parser.parse_args()
    if args.command == "prompt":
        show_prompt(args.base, args.variant)
    else:
        show_experiment(args.config)


if __name__ == "__main__":
    main()

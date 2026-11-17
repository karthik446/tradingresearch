"""The free CI gate (REPO-PLAN §7 G5): reconcile goldens and prompt immutability. No network, no model, no key.

`uv run python ci/gate.py` runs both checks; `--accept-reconcile` rewrites the goldens (only with a rules_version
bump); `--record-prompts` locks the hash of a new prompt that an experiment justifies. A prompt change cannot merge
without a recorded experiment (https://hamel.dev/blog/posts/evals/).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # the synthetic bars and their helpers live with the reconcile tests

import test_reconcile as fx  # noqa: E402

from tradingresearch import reconcile  # noqa: E402
from tradingresearch.costs import Costs  # noqa: E402
from tradingresearch.records import RULES_VERSION  # noqa: E402
from tradingresearch.sessions import xnys  # noqa: E402

GOLDEN = Path("tests/gate/golden/reconcile.json")
HASHES = Path("ci/prompt-hashes.json")
BASELINE = "baseline"  # the first prompt of a kind, allowed only for `*-1` files
SHOWN_DIFFS = 5

# One row per bars.json case: (golden name, fixture case, subject kwargs, settle kwargs), the kwargs of its test.
CASES: list[tuple[str, str, dict, dict]] = [
    ("market_open", "market_open", {"kind": "market_open"}, {}),
    ("entry_stop", "entry_stop", {}, {}),
    ("entry_stop_gap", "entry_stop_gap", {}, {}),
    ("entry_limit", "entry_limit", {"kind": "limit", "entry": 100.0}, {}),
    ("entry_limit_touch", "entry_limit_touch", {"kind": "limit", "entry": 100.0}, {}),
    ("entry_limit_gap", "entry_limit_gap", {"kind": "limit", "entry": 100.0}, {}),
    ("exit_stop", "exit_stop", {}, {}),
    ("exit_stop_gap", "exit_stop_gap", {}, {}),
    ("exit_target", "exit_target", {}, {}),
    ("exit_target_touch", "exit_target_touch", {}, {}),
    ("exit_target_gap", "exit_target_gap", {}, {}),
    ("entry_stop_touch", "entry_stop_touch", {}, {}),
    ("exit_stop_touch", "exit_stop_touch", {}, {}),
    ("time_exit_short", "time_exit_short", {"hold": 3}, {}),
    ("time_exit_swing_holiday", "time_exit_swing_holiday", {"horizon": "swing", "hold": 5, "day": date(2026, 11, 19)},
     {}),
    ("time_exit_day", "time_exit_day", {"horizon": "day"}, {}),
    ("time_exit_day_early_close", "time_exit_day_early_close", {"horizon": "day", "day": date(2026, 11, 27)}, {}),
    ("invalidation_day", "invalidation_day", {"horizon": "day"}, {}),
    ("invalidation_short", "invalidation_short", {}, {}),
    ("invalidation_stop_first", "invalidation_stop_first", {}, {}),
    ("invalidation_time_exit_first", "invalidation_time_exit_first", {"hold": 2}, {}),
    ("minute_invalidation_stop_first", "minute_invalidation_stop_first", {"horizon": "day"}, {}),
    ("minute_invalidation_time_exit_first", "minute_invalidation_time_exit_first", {"horizon": "day"}, {}),
    ("entry_day_invalidation", "entry_day_invalidation", {}, {}),
    ("same_bar_daily", "same_bar_daily", {}, {}),
    ("same_bar_daily_stop_first", "same_bar_daily_stop_first", {}, {}),
    ("same_bar_minute", "same_bar_minute", {"horizon": "day"}, {}),
    ("same_bar_entry_stop", "same_bar_entry_stop", {"horizon": "day"}, {}),
    ("same_bar_entry_target", "same_bar_entry_target", {"horizon": "day"}, {}),
    ("same_bar_missing_minutes", "same_bar_daily", {}, {"drop": (fx.D2,)}),
    ("pre_entry_stop", "pre_entry_stop", {}, {}),
    ("pre_entry_gap_limit_at_stop", "pre_entry_gap_limit_at_stop", {"kind": "limit", "entry": 100.0}, {}),
    ("pre_entry_gap_limit_below_stop", "pre_entry_gap_limit_below_stop", {"kind": "limit", "entry": 100.0}, {}),
    ("pre_entry_gap_stop_entry", "pre_entry_gap_stop_entry", {}, {}),
    ("day_pre_entry_stop", "day_pre_entry_stop", {"horizon": "day"}, {}),
    ("day_pre_entry_invalidated", "day_pre_entry_invalidated", {"horizon": "day"}, {}),
    ("pre_entry_invalidated", "pre_entry_invalidated", {}, {}),
    ("window_missed", "window_missed", {"horizon": "swing"}, {}),
    ("window_missed_before_end", "window_missed", {"horizon": "swing"}, {"until": fx.D1}),
    ("window_end_after_close", "window_end_after_close", {"end": fx.ny(fx.D2, "09:00")}, {}),
    ("entry_minutes_missing", "entry_stop", {}, {"drop": (fx.D1,)}),
    ("corporate_action_proposed", "corporate_action_proposed", {}, {}),
    ("corporate_action_open", "corporate_action_open", {}, {}),
    ("no_look_ahead", "no_look_ahead", {"start": fx.ny(fx.D1, "10:00")}, {}),
    ("no_look_ahead_daily", "no_look_ahead_daily", {"day": fx.D2}, {}),
]


# -- reconcile goldens ----------------------------------------------------------------------------------------------


def reconcile_outputs(costs: Costs = Costs()) -> dict[str, dict]:
    """Every case, long and short, settled from its PROPOSED event; the thesis id is pinned so event ids are stable."""
    outputs = {}
    for name, case, subject_kwargs, settle_kwargs in CASES:
        for d, side in ((1, "long"), (-1, "short")):
            th = fx.subject(d, **subject_kwargs).model_copy(update={"thesis_id": f"th_gate_{name}_{side}"})
            daily, minutes = fx.bars(case, d, **settle_kwargs)
            events = (fx.event(th.thesis_id, "PROPOSED"),)
            result = reconcile.settle(th, events, daily, minutes, xnys(), RULES_VERSION, costs)
            outputs[f"{name}/{side}"] = result.model_dump(mode="json")
    return outputs


def _text(value: object) -> str:
    """Canonical JSON for goldens: sorted keys, floats as Python's shortest round-trip repr."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _load(golden: Path) -> dict | None:
    return json.loads(golden.read_text()) if golden.exists() else None


def _changed(old: dict, new: dict) -> list[str]:
    """Golden case names whose output moved or vanished; a case only in `new` is added coverage, not a change."""
    return [name for name in old if new.get(name) != old[name]]


def _diff(name: str, old: dict | None, new: dict | None) -> str:
    before = _text(old).splitlines(keepends=True) if old is not None else []
    after = _text(new).splitlines(keepends=True) if new is not None else []
    return "".join(difflib.unified_diff(before, after, f"golden {name}", f"now {name}"))


def check_reconcile(golden: Path, outputs: dict[str, dict] | None = None) -> list[str]:
    """Problems when the engine's output differs from the committed goldens, with a diff per moved case."""
    stored = _load(golden)
    if stored is None:
        return [f"{golden}: missing; run `uv run python ci/gate.py --accept-reconcile`"]
    outputs = reconcile_outputs() if outputs is None else outputs
    names = sorted(set(stored["cases"]) | set(outputs))
    moved = [name for name in names if stored["cases"].get(name) != outputs.get(name)]
    if not moved:
        return []
    head = (f"reconcile output differs from {golden} in {len(moved)} case(s) (goldens: {stored['rules_version']}, "
            f"code: {RULES_VERSION}); a rule or cost change needs a RULES_VERSION bump in records.py, then "
            "`uv run python ci/gate.py --accept-reconcile`")
    diffs = [_diff(name, stored["cases"].get(name), outputs.get(name)) for name in moved[:SHOWN_DIFFS]]
    rest = moved[SHOWN_DIFFS:]
    more = [f"... and {len(rest)} more: {', '.join(rest)}"] if rest else []
    return [head, *diffs, *more]


def accept_reconcile(golden: Path, outputs: dict[str, dict] | None = None) -> list[str]:
    """Rewrite the goldens; refused when a recorded case moved under the same rules_version as the goldens."""
    outputs = reconcile_outputs() if outputs is None else outputs
    stored = _load(golden)
    if stored is not None:
        changed = _changed(stored["cases"], outputs)
        if changed and stored["rules_version"] == RULES_VERSION:
            return [f"refused: {len(changed)} golden case(s) moved ({', '.join(changed[:SHOWN_DIFFS])}) but "
                    f"RULES_VERSION is still {RULES_VERSION}; bump it in src/tradingresearch/records.py first"]
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text(_text({"rules_version": RULES_VERSION, "cases": outputs}))
    print(f"wrote {golden.name}: {len(outputs)} cases at {RULES_VERSION}")
    return []


# -- prompt immutability --------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _prompts(root: Path) -> dict[str, Path]:
    return {p.stem: p for p in sorted((root / "prompts").iterdir()) if p.is_file() and not p.name.startswith(".")}


def _arms(root: Path) -> dict[str, list[str]]:
    """Prompt stem -> the experiment configs (file stems) with an arm naming it."""
    named: dict[str, list[str]] = {}
    for config in sorted((root / "experiments").glob("*.toml")):
        for arm in tomllib.loads(config.read_text()).get("arms", []):
            if "prompt" in arm:
                named.setdefault(arm["prompt"], []).append(config.stem)
    return named


def _justified(stem: str, experiment: str, arms: dict[str, list[str]]) -> bool:
    """`baseline` only for a `*-1` prompt; otherwise an experiments/<experiment>.toml arm must name the prompt."""
    return stem.endswith("-1") if experiment == BASELINE else experiment in arms.get(stem, [])


def check_prompts(root: Path) -> list[str]:
    """Problems: a recorded prompt changed or vanished, an entry without a valid experiment, an unrecorded prompt."""
    hashes = json.loads((root / HASHES).read_text())
    prompts, arms, problems = _prompts(root), _arms(root), []
    for stem, entry in sorted(hashes.items()):
        path = prompts.get(stem)
        if path is None:
            problems.append(f"prompts/{stem}: recorded in {HASHES} but the file is gone; recorded prompts stay")
        elif _sha256(path) != entry["sha256"]:
            problems.append(f"{path.relative_to(root)}: bytes changed after it was recorded; prompts are immutable, "
                            "write the change as a new prompt file with an experiment arm for it")
        if not _justified(stem, entry.get("experiment", ""), arms):
            problems.append(f"{HASHES} {stem}: experiment {entry.get('experiment')!r} does not justify it (an "
                            f"experiments/<name>.toml arm must name {stem}; {BASELINE!r} only for *-1 prompts)")
    for stem in sorted(set(prompts) - set(hashes)):
        why = (f"named by experiments {arms[stem]}; run `uv run python ci/gate.py --record-prompts` and commit "
               f"{HASHES}") if stem in arms else "no experiments/*.toml arm names it and it has no recorded experiment"
        problems.append(f"{prompts[stem].relative_to(root)}: not recorded in {HASHES} ({why})")
    return problems


def record_prompts(root: Path) -> list[str]:
    """Lock the hash of each unrecorded prompt an experiment arm names (or a `*-1` baseline); never re-record one."""
    hashes = json.loads((root / HASHES).read_text())
    prompts, arms, problems = _prompts(root), _arms(root), []
    for stem in sorted(set(prompts) - set(hashes)):
        experiment = arms[stem][0] if stem in arms else BASELINE if stem.endswith("-1") else None
        if experiment is None:
            problems.append(f"{prompts[stem].relative_to(root)}: not recorded; add an experiments/*.toml arm naming it")
        else:
            hashes[stem] = {"experiment": experiment, "sha256": _sha256(prompts[stem])}
            print(f"recorded {prompts[stem].relative_to(root)} -> experiment {experiment!r} {hashes[stem]['sha256']}")
    (root / HASHES).write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    return problems


# -- command --------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    """Exit 0 when every check passes; print each problem otherwise."""
    p = argparse.ArgumentParser(prog="ci/gate.py", description=__doc__.splitlines()[0])
    p.add_argument("--accept-reconcile", action="store_true", help="rewrite the reconcile goldens (needs a rules bump)")
    p.add_argument("--record-prompts", action="store_true", help="lock the hashes of new, justified prompts")
    args = p.parse_args(argv)
    if args.accept_reconcile:
        problems = accept_reconcile(root / GOLDEN)
    elif args.record_prompts:
        problems = record_prompts(root)
    else:
        problems = check_reconcile(root / GOLDEN) + check_prompts(root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems and not (args.accept_reconcile or args.record_prompts):
        print(f"gate: ok ({len(CASES) * 2} reconcile cases at {RULES_VERSION}, {len(_prompts(root))} prompts)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

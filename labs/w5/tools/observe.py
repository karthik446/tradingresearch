"""Observe for the week-5 labs: what your section graders and your ablation config do ($0, no network).

    python labs/w5/tools/observe.py grader    # w5l1: the four section scores on five replies, in three arms
    python labs/w5/tools/observe.py ablation  # w5l2: experiments/context-ablation.toml loaded, then replayed at $0

`grader` scores five replies about the FAKEA context (tools/fakea.py) per section: the recorded analyze-3 reply, a
reply with a claim citing two sections, a reply whose claims fail for three reasons, a parsed reply with no claims
list, and a reply that did not parse. Each section's grader is the registered `<section>_grounded` when evals.GRADERS
has it, built by evals.graders as an arm builds it, and else a subclass of SectionGrounded that sets `section`. The
recorded reply is then scored in the full, no-headlines and no-edgar arms, once the registered graders exist.

`ablation` loads experiments/context-ablation.toml with experiment.load and prints its arms, graders, cluster and
pre-registration lines, then runs its arms through the real OpenRouter adapter whose transport answers every request
with the recorded reply (at most fakea.STOP_AFTER requests; a temp journal; the context size pinned at 1600 tokens, as
the checks do) and prints the requests sent and each grader's mean and count per arm.

TR_LAB_DATA overrides labs/w5/data. Exits 0 in every mode: it shows what your code does, the exercise's check decides.
The offline guard (tools/offline.py) is installed before your code is imported; a guarded call it tried is named in a
`note:` line at the end.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline  # noqa: E402

offline.install()  # before fakea and your code are imported
import fakea  # noqa: E402

LABELS = ("Primary metric:", "Guard metric:", "Rule:")


def module(name: str) -> object | str:
    try:
        return importlib.import_module(f"tradingresearch.{name}")
    except Exception as exc:  # a learner's half-written file: show it, keep going
        return f"{type(exc).__name__}: {exc}"


def cut(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def section_grader(evals, section: str, drop: tuple[str, ...] = ()):
    name = f"{section}_grounded"
    if name in evals.GRADERS:
        return evals.graders([name], drop)[0]
    return type(f"Lab{section.title()}", (evals.SectionGrounded,), {"section": section})()


def score(g, parsed, parse_status: str = "ok") -> str:
    try:
        got = g.grade(fakea.sample_of(parsed, parse_status), fakea.expected())
    except Exception as exc:  # noqa: BLE001 - CannotGrade and a half-written grader alike are shown
        return f"{type(exc).__name__}: {cut(exc, 58)}".rstrip(": ")
    return f"{got.value:.3f}  {cut(got.explanation, 56)}"


def grader_mode() -> None:
    evals, masking = module("evals"), module("masking")
    if isinstance(evals, str):
        print(f"does not import: {evals}")
        return
    headline = fakea.rows("headlines")[0].name
    regime = fakea.row("regime_spy")
    replies = [
        ("the recorded analyze-3 reply", fakea.recorded(), "ok"),
        ("m1 cites close and a level; m2 sma_20 (wrong) and a level",
         {"claims": [fakea.fact("m1", "close", "level_hvn_1"), fakea.fact("m2", "sma_20", "level_hvn_2", value=1.0)]},
         "ok"),
        ("three indicator claims failing three ways, one kept",
         {"claims": [fakea.fact("i1", "sma_20", value=1.0), fakea.fact("i2", "close", text="The close is 5 {value}."),
                     dict(id="i3", tag="fact", text="The regime is {value}.", value=None, unit=None,
                          source_ids=[regime.source_id], derived_from=[], steps=None),
                     fakea.fact("i4", "close"), fakea.fact("h1", headline)]}, "ok"),
        ("a parsed reply with no claims list", {"verdict": "none"}, "ok"),
        ("a reply that did not parse", None, "not_json"),
    ]
    registered = sorted(n for n in evals.GRADERS if n.endswith("_grounded") and n != "inferences_grounded")
    print(f"registered section graders: {registered or 'none yet'}")
    for label, parsed, status in replies:
        print(f"\n{label} ({status}):")
        for section in masking.SECTIONS:
            print(f"  {section:11} {score(section_grader(evals, section), parsed, status)}")
    if len(registered) < len(masking.SECTIONS):
        return
    print("\nthe recorded reply in each arm (evals.graders hands the arm's drop to every grader):")
    for drop in [(), ("headlines",), ("edgar",)]:
        print(f"  drop {list(drop)}")
        for section in masking.SECTIONS:
            print(f"    {section:11} {score(section_grader(evals, section, drop), fakea.recorded())}")


def header(path: Path) -> list[str]:
    """The comment lines above the config's first key that start a pre-registration item."""
    lines = []
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            break
        item = line.lstrip("#").strip().removeprefix("- ")
        if item.startswith(LABELS):
            lines.append(item)
    return lines


def ablation_mode() -> None:
    ex = module("experiment")
    if isinstance(ex, str):
        print(f"does not import: {ex}")
        return
    try:
        config = ex.load(fakea.CONFIG)
    except SystemExit as exc:
        print(f"experiment.load refused {fakea.CONFIG}: {exc}")
        return
    print(f"{fakea.CONFIG}: {len(config.arms)} arms, {len(config.tickers)} tickers, cluster {config.cluster!r}")
    for arm in config.arms:
        print(f"  {arm.name:16} {arm.model:28} {arm.prompt:10} {arm.mode:6} drop {list(arm.drop)}")
    print(f"graders: {list(config.graders)}")
    print("pre-registration lines above the first key:")
    for line in header(fakea.CONFIG) or ["(none)"]:
        print(f"  {cut(line, 110)}")
    sent: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            results = fakea.ablation(config, Path(tmp), sent)
        except Exception as exc:  # noqa: BLE001 - shown
            print(f"\nthe $0 replay raised {type(exc).__name__}: {cut(exc, 100)} after {len(sent)} requests")
            return
    print(f"\nthe $0 replay: {len(sent)} requests, each answered with the recorded reply; per arm, mean (n) of each "
          f"grader that scored (a section no claim cites has none):")
    for result in results:
        means = ex.means(result.run)
        shown = ", ".join(f"{g} {m:.3f} ({n})" for g, (m, n) in means.items())
        print(f"  {result.arm.name:16} {cut(shown, 170)}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    modes = {"grader": grader_mode, "ablation": ablation_mode}
    if mode not in modes:
        print(f"usage: python labs/w5/tools/observe.py {'|'.join(modes)}")
        return 2
    modes[mode]()
    if offline.HITS:
        print(f"note: your code tried {', '.join(dict.fromkeys(offline.HITS))}: blocked, the week-5 labs open no "
              f"connection and start no process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""w3l2.1 rubric in, thesis out: the judge's prompt carries p1_thesis_quality.md, and OUTPUT is the thesis text.

p1_judge runs on the closed FAKEA trade from tests/test_week3.py, through the real OpenRouter adapter whose transport
answers with the recorded reply ($0, no network). The prompt it sends is compared with the recorded request
(labs/w3/data/judge_request.json, run_54953ec7ce484649): a replayed reply is evidence only for the request that
produced it.
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

SECTIONS = ("Question", "Inputs", "Met", "Not met", "Unknown", "Hindsight", "Verdict format")


@pytest.fixture(scope="module")
def prompt(tmp_path_factory) -> str:
    got, sent, _ = fakea.judge(tmp_path_factory.mktemp("w3l2_1"))
    assert sent, (
        f"p1_judge sent no request: it stopped with {fakea.shown(got)}. Part A's p1_judge stops with "
        f"NotImplementedError after its call, so anything else before it is in the code you changed."
    )
    return fakea.prompt_of(sent[0])


def test_the_prompt_carries_the_rubric(prompt):
    mine, recorded = fakea.rubric_part(prompt), fakea.rubric_part(fakea.recorded_prompt())
    missing = [s for s in SECTIONS if f"## {s}" not in prompt]
    a, b = mine.splitlines(), recorded.splitlines()
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    why = ("Without p1_thesis_quality.md the judge never sees when a mechanism is met, not met or unknown, nor the "
           "Verdict format p1_verdict reads." if missing or "{rubric}" in prompt else
           "The rubric is there but the prompt file around it is not: the frame tells the judge which block is the "
           "thesis and which the evidence.")
    assert mine == recorded, (
        f"The judge's instructions are {len(mine)} chars, the recorded request's {len(recorded)}; "
        f"{'the {rubric} line is still in the prompt, ' if '{rubric}' in prompt else ''}"
        f"rubric sections missing: {missing or 'none'}; first differing line {first + 1}: "
        f"{(a[first] if first < len(a) else '(end)')[:70]!r}. {why}"
    )


def test_output_holds_the_thesis_one_labelled_line_each(prompt):
    mine, recorded = fakea.block(prompt, "OUTPUT"), fakea.block(fakea.recorded_prompt(), "OUTPUT")
    assert mine == recorded, (
        f"[BEGIN OUTPUT] holds {mine!r}; the recorded request held {recorded!r}. OUTPUT is the text being graded: "
        f"the thesis's prediction, reason and invalidation_text, labelled as the prompt file names them, so the judge "
        f"can list the mechanisms the reason names."
    )


def test_output_follows_the_thesis_it_judges(tmp_path):
    got, sent, _ = fakea.judge(tmp_path, reworded=True)
    assert sent, f"p1_judge sent no request for a reworded thesis on the same trade: it stopped with {fakea.shown(got)}."
    mine = fakea.block(fakea.prompt_of(sent[0]), "OUTPUT")
    labels = [line.split(": ", 1)[0] for line in fakea.block(fakea.recorded_prompt(), "OUTPUT")]
    want = [f"{name}: {fakea.REWORDED[name]}" for name in labels]
    assert mine == want, (
        f"For the same trade with its thesis reworded, [BEGIN OUTPUT] holds {mine!r}; that thesis says {want!r}. "
        f"OUTPUT comes from the thesis being judged: a fixed text passes the recorded trade and grades the wrong "
        f"thesis on every other."
    )


def test_the_instructions_follow_the_rubric_file(tmp_path, monkeypatch):
    from tradingresearch import evals

    rubrics, added = tmp_path / "rubrics", "A line this check added to the end of the rubric file."
    frame = "A line this check added to the start of the prompt file."
    shutil.copytree(evals.RUBRICS, rubrics)
    (rubrics / "p1_thesis_quality.md").write_text((evals.RUBRICS / "p1_thesis_quality.md").read_text() + added + "\n")
    (rubrics / "p1_judge_prompt.txt").write_text(frame + "\n" + (evals.RUBRICS / "p1_judge_prompt.txt").read_text())
    monkeypatch.setattr(evals, "RUBRICS", rubrics)
    got, sent, _ = fakea.judge(tmp_path)
    mine = fakea.rubric_part(fakea.prompt_of(sent[0])) if sent else ""
    missing = [line for line in (frame, added) if line not in mine]
    assert not missing, (
        f"The judge's instructions ({len(mine)} chars; p1_judge ended with {fakea.shown(got)}) do not hold the added "
        f"line(s) {missing!r}. RUBRICS points at a copy of evals/rubrics whose p1_judge_prompt.txt starts with "
        f"{frame!r} and whose p1_thesis_quality.md ends with {added!r}. Both files are read from RUBRICS on every "
        f"call, so an edit to either changes what the judge is told; a copy of the recorded request's text, or a "
        f"path of its own, grades every later trade by the files as they were on 2026-11-17."
    )


def test_a_long_reason_reaches_the_judge_whole(tmp_path, monkeypatch):
    reason = " ".join(["The 20-day high at 100.5 gave way and closes held over it; volume rose on each close."] * 15)
    monkeypatch.setitem(fakea.REWORDED, "reason", reason)
    got, sent, _ = fakea.judge(tmp_path, reworded=True)
    mine = fakea.block(fakea.prompt_of(sent[0]), "OUTPUT") if sent else []
    held = next((line for line in mine if line.startswith("reason: ")), "")
    assert held == f"reason: {reason}", (
        f"[BEGIN OUTPUT]'s reason line is {len(held)} chars (p1_judge ended with {fakea.shown(got)}); the thesis's "
        f"reason is {len(reason)} chars, so the line should be {len('reason: ' + reason)}. The judge lists the "
        f"mechanisms the whole reason names: a cut reason hides the ones at its end, and the verdict grades a "
        f"thesis nobody wrote."
    )

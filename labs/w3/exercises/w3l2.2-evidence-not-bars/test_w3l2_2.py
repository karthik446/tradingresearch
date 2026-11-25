"""w3l2.2 evidence, not bars: INPUT is the cited claims and the code-written summary, never the bar rows.

The rubric's Hindsight section: the judge sees what code measured after the trade (label.summary) and the claims the
thesis cited, not the bars. Bars would let it read the whole price path and grade with hindsight; the summary says only
what the reason needs. Same replay as w3l2.1: the closed FAKEA trade, compared with labs/w3/data/judge_request.json.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

RAW_BAR_VALUES = ("100.2", "101.6", "106.5", "107.5", "107.2")  # tests/test_week3.py: opens, highs, a post-exit close


@pytest.fixture(scope="module")
def prompt(tmp_path_factory) -> str:
    got, sent, _ = fakea.judge(tmp_path_factory.mktemp("w3l2_2"))
    assert sent, (
        f"p1_judge sent no request: it stopped with {fakea.shown(got)}. Part A's p1_judge stops with "
        f"NotImplementedError after its call, so anything else before it is in the code you changed."
    )
    return fakea.prompt_of(sent[0])


def test_the_prompt_holds_no_bar_rows(prompt):
    values = [v for v in RAW_BAR_VALUES if v in prompt]
    columns = re.findall(r"['\"](?:o|h|l|vw)['\"]\s*:|\bo\s+h\s+l\s+c\b", prompt)
    assert not values and not columns, (
        f"The prompt holds bar values {values} and bar columns {columns}: opens, highs or a close after the exit, "
        f"which no claim and no summary line contains. The judge must not see the price path (rubric: Hindsight); "
        f"label.summary already says what the closes did against the levels the reason names."
    )


def test_input_is_the_cited_claims_then_the_summary(prompt):
    mine, recorded = fakea.block(prompt, "INPUT"), fakea.block(fakea.recorded_prompt(), "INPUT")
    first = next((i for i, (a, b) in enumerate(zip(mine, recorded)) if a != b), min(len(mine), len(recorded)))
    yours = mine[first] if first < len(mine) else "(end of block)"
    theirs = recorded[first] if first < len(recorded) else "(end of block)"
    assert mine == recorded, (
        f"[BEGIN INPUT] has {len(mine)} lines, the recorded request's {len(recorded)}; they differ at line {first + 1}: "
        f"yours {yours[:90]!r}, recorded {theirs[:90]!r}. INPUT is the cited claims under their heading, a blank line, "
        f"then the post-trade summary under its heading, as label.cited and label.summary write them."
    )


def test_input_follows_the_thesis_it_judges(tmp_path):
    got, sent, t = fakea.judge(tmp_path, reworded=True)
    assert sent, f"p1_judge sent no request for a reworded thesis on the same trade: it stopped with {fakea.shown(got)}."
    mine, recorded = fakea.block(fakea.prompt_of(sent[0]), "INPUT"), fakea.block(fakea.recorded_prompt(), "INPUT")
    claims = mine[1:mine.index("")] if "" in mine else mine[1:]
    want = [line for line in recorded[1:recorded.index("")] if line.split(" | ")[0] in t.evidence]
    assert claims == want, (
        f"The same trade, its thesis citing only {list(t.evidence)} of its analysis's two claims: INPUT's claim lines "
        f"are {claims!r}, the cited one is {want!r}. The judge checks the reason against what the thesis cited, so "
        f"the claims shown are this thesis's evidence: not every claim of the analysis, not the recorded trade's lines."
    )

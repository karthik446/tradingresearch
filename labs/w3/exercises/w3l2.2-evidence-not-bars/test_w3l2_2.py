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

# tests/test_week3.py: opens, highs, lows and a post-exit close, none of which a claim or a summary line holds
RAW_BAR_VALUES = ("100.2", "101.6", "106.5", "107.5", "107.2", "101.0", "105.0")


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
        f"The prompt holds bar values {values} and bar columns {columns}: opens, highs, lows or a close after the exit, "
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


def test_the_summary_follows_the_thesis_it_judges(tmp_path):
    from tradingresearch import label

    got, sent, t = fakea.judge(tmp_path, reworded=True)
    assert sent, f"p1_judge sent no request for a reworded thesis on the same trade: it stopped with {fakea.shown(got)}."
    mine = fakea.block(fakea.prompt_of(sent[0]), "INPUT")
    (tmp_path / "fresh").mkdir()
    conn, fresh, bars = fakea.closed_trade(tmp_path / "fresh", reworded=True)
    want = label.summary(conn, bars, *label.labelable(conn, fresh.thesis_id)).splitlines()
    lines = mine[mine.index("") + 2:] if "" in mine else []
    assert lines == want, (
        f"The same trade, its thesis citing only {list(t.evidence)}: INPUT's summary lines are {lines!r}; "
        f"label.summary for that thesis writes {want!r}. The summary measures the closes against the levels this "
        f"thesis's cited claims name, so it is written for the thesis being judged, not copied from the recorded trade."
    )


def test_input_shows_every_cited_claim(tmp_path, monkeypatch):
    import test_week3

    made_analysis, made_thesis = test_week3.analysis, test_week3.thesis

    def analysis(*args, **kwargs):  # the FAKEA analysis with a third claim, an inference from the other two
        a = made_analysis(*args, **kwargs)
        third = a.claims[0].model_copy(update={
            "claim_id": "cl_fakea_both", "tag": "inference", "text": "The two levels meet at {value} USD.",
            "source_ids": (), "derived_from": ("cl_fakea_high", "cl_fakea_top"), "steps": "high_20 = congestion_high"})
        return a.model_copy(update={"claims": (*a.claims, third)})

    def thesis(*args, **kwargs):  # its thesis citing all three
        t = made_thesis(*args, **kwargs)
        return t.model_copy(update={"evidence": (*t.evidence, "cl_fakea_both")})

    monkeypatch.setattr(test_week3, "analysis", analysis)
    monkeypatch.setattr(test_week3, "thesis", thesis)
    got, sent, t = fakea.judge(tmp_path)
    mine = fakea.block(fakea.prompt_of(sent[0]), "INPUT") if sent else []
    claims = mine[1:mine.index("")] if "" in mine else []
    third = "cl_fakea_both | inference | The two levels meet at 100.5 USD. (steps: high_20 = congestion_high)"
    assert [line.split(" | ")[0] for line in claims] == list(t.evidence) and claims[-1:] == [third], (
        f"INPUT's claim lines are {claims!r} (p1_judge ended with {fakea.shown(got)}); the thesis cites "
        f"{list(t.evidence)}, the last shown as {third!r}. The FAKEA analysis here has a third claim, an inference, "
        f"and the thesis cites all three: every cited claim is shown as label.cited writes it, steps included, or "
        f"the judge checks the reason against part of its evidence."
    )

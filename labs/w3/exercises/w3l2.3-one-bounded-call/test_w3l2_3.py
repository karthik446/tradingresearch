"""w3l2.3 one bounded call: ADR-003's reply bound and a money cap checked before sending.

Same replay as w3l2.1: the closed FAKEA trade through the real adapter, whose transport answers with the recorded reply.
At the end the whole request must equal the recorded one (labs/w3/data/judge_request.json): only then is the replayed
reply evidence for what your code sends. Keeping the run in a run file is part B (lab w3l3).
"""

import sys
from pathlib import Path

import pytest
from gigai_core.budget import BudgetExceeded

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

WORST_CASE = 0.042964  # one call's worst case: the recorded prompt plus 4000 output tokens at the recorded price


@pytest.fixture(scope="module")
def judged(tmp_path_factory) -> tuple:
    data_dir = tmp_path_factory.mktemp("w3l2_3")
    got, sent, _ = fakea.judge(data_dir)
    why = (f"A money cap needs the model's price to estimate a call; with no price for {fakea.MODEL} the budget refuses "
           f"every call." if isinstance(got, BudgetExceeded) else
           "Part A's p1_judge stops with NotImplementedError after its call through the provider it is given, so "
           "anything else before it is in the code you changed.")
    assert sent, (
        f"p1_judge sent no request under max_usd={fakea.MAX_USD} (test_week3's cap, above one call's worst case of "
        f"about $0.043): it stopped with {fakea.shown(got)}. {why}"
    )
    return got, sent, data_dir


def test_the_reply_is_bounded_by_judge_max_tokens(judged):
    _, sent, _ = judged
    recorded = fakea.load("judge_request")["body"]["max_tokens"]
    assert sent[0].get("max_tokens") == recorded, (
        f"The request asks for at most {sent[0].get('max_tokens')} output tokens; the recorded request asked for "
        f"{recorded} (JUDGE_MAX_TOKENS, ADR-003: about 500 per trade expected, 4000 bounds a runaway reply). 1024 is "
        f"CallSettings' default, and a reply cut short there can end before its verdict (w3l1.3's cut_off reply)."
    )


def test_a_cap_below_the_worst_case_refuses_before_sending(tmp_path):
    got, sent, _ = fakea.judge(tmp_path, max_usd=0.001)
    assert not sent and isinstance(got, BudgetExceeded), (
        f"With max_usd=0.001, below one call's worst case (about $0.043 at 4000 output tokens), p1_judge sent "
        f"{len(sent)} request(s) and ended with {fakea.shown(got)}. The cap is checked before the call, from the "
        f"price table: BudgetExceeded, nothing sent, nothing spent."
    )


@pytest.mark.parametrize("cap, sends", [(0.0435, True), (0.0425, False)])
def test_the_cap_is_the_callers_to_the_last_tenth_of_a_cent(cap, sends, tmp_path):
    got, sent, _ = fakea.judge(tmp_path, max_usd=cap)
    assert bool(sent) == sends, (
        f"With max_usd={cap}, just {'above' if sends else 'below'} one call's worst case (${WORST_CASE}), p1_judge "
        f"sent {len(sent)} request(s) and ended with {fakea.shown(got)}; it should "
        f"{'send its one call' if sends else 'refuse before sending'}. The cap is the money the caller allows, as "
        f"given: tr grade passes what is left of its own budget, so a margin, a rounding or extra slack on top moves "
        f"the line the caller drew."
    )


def test_one_request_and_it_is_the_recorded_one(judged):
    _, sent, _ = judged
    recorded = fakea.load("judge_request")["body"]
    differs = sorted(k for k in recorded.keys() | sent[0].keys() if recorded.get(k) != sent[0].get(k))
    assert len(sent) == 1 and sent[0] == recorded, (
        f"p1_judge sent {len(sent)} request(s); the first differs from the recorded request in {differs}. One call "
        f"per trade, and the body must be the recorded one for the recorded reply to mean anything about your code."
    )

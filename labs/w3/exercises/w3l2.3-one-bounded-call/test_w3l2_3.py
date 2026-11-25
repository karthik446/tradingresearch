"""w3l2.3 one bounded call: ADR-003's reply bound and a money cap checked before sending.

Same replay as w3l2.1: the closed FAKEA trade through the real adapter, whose transport answers with the recorded reply.
At the end the whole request must equal the recorded one (labs/w3/data/judge_request.json): only then is the replayed
reply evidence for what your code sends. Keeping the run in a run file is part B (lab w3l3).
"""

import json
import sys
from pathlib import Path

import pytest
from gigai_core.budget import BudgetExceeded

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

# The budget's estimate of one call's worst case, which its cap is checked against: the recorded prompt counted at about
# 4 characters a token (1482 tokens) plus 4000 output tokens, at the recorded prices. The recorded call's prompt was
# really 1558 tokens, so the true worst case is $0.043116; the budget can only estimate before sending.
WORST_CASE = 0.042964


def refused(data_dir: Path) -> list[str]:
    """What the provider refused before sending, from the trace run_eval writes under data_dir/traces."""
    traces = sorted((data_dir / "traces").glob("*.jsonl"))
    lines = [json.loads(x) for p in traces for x in p.read_text().splitlines() if x]
    return sorted({f"{e.get('code')} ({e.get('message')})" for o in lines if isinstance(e := o.get("error"), dict)})


@pytest.fixture(scope="module")
def judged(tmp_path_factory) -> tuple:
    data_dir = tmp_path_factory.mktemp("w3l2_3")
    got, sent, _ = fakea.judge(data_dir)
    errors = [] if sent else refused(data_dir)
    why = (f"A money cap needs the model's price to estimate a call; with no price for {fakea.MODEL} the budget refuses "
           f"every call." if isinstance(got, BudgetExceeded) else
           f"The adapter refused the request before sending it: {errors}. A settings field the adapter does not send "
           f"stops the call; the exercise asks only for the model, JUDGE_MAX_TOKENS and the budget." if errors else
           "Part A's p1_judge stops with NotImplementedError after its call through the provider it is given, so "
           "anything else before it is in the code you changed.")
    assert sent, (
        f"p1_judge sent no request under max_usd={fakea.MAX_USD} (test_week3's cap, above the budget's estimate of "
        f"one call's worst case, about $0.043): it stopped with {fakea.shown(got)}. {why}"
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
        f"With max_usd=0.001, below one call's worst case as the budget estimates it (about $0.043 at 4000 output "
        f"tokens), p1_judge sent {len(sent)} request(s) and ended with {fakea.shown(got)}. The cap is checked before "
        f"the call, from the price table: BudgetExceeded, nothing sent, nothing spent."
    )


@pytest.mark.parametrize("cap, sends", [(0.0435, True), (0.0425, False), (0.04297, True), (0.04296, False)])
def test_the_cap_is_the_callers_to_a_thousandth_of_a_cent(cap, sends, tmp_path):
    got, sent, _ = fakea.judge(tmp_path, max_usd=cap)
    assert bool(sent) == sends, (
        f"With max_usd={cap}, just {'above' if sends else 'below'} one call's worst case as the budget estimates it "
        f"(${WORST_CASE}), p1_judge sent {len(sent)} request(s) and ended with {fakea.shown(got)}; it should "
        f"{'send its one call' if sends else 'refuse before sending'}. The cap is the money the caller allows, as "
        f"given: tr grade passes what is left of its own budget, so a margin, a rounding or extra slack on top moves "
        f"the line the caller drew."
    )


def test_one_request_and_it_is_the_recorded_one(judged):
    _, sent, _ = judged
    recorded = fakea.load("judge_request")["body"]
    differs = sorted(k for k in recorded.keys() | sent[0].keys() if recorded.get(k) != sent[0].get(k))
    what = (f"the first differs from the recorded request in {differs}" if differs else
            "the first is the recorded request, and every other one is a second paid call for the same trade")
    assert len(sent) == 1 and not differs, (
        f"p1_judge sent {len(sent)} request(s); {what}. One call per trade, and the body must be the recorded one "
        f"for the recorded reply to mean anything about your code."
    )

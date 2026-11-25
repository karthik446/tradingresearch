"""w3l4.2 one cap per run: grade.judge judges every waiting thesis once, under one dollar cap for the whole run.

Each check builds a journal of three closed, graded FAKEA theses (a champion, a challenger, then a second champion;
tools/fakea.py `journal_of`) and runs grade.judge through the real adapter. Request i gets reply i (`answer`): the
recorded pass, a reply with no verdict, or an HTTP 400. One check makes the bars fail once, the way a data feed can.
The budget's estimate of one call's worst case is about $0.043 (4000 output tokens); the recorded reply cost
$0.005163, as its run file says.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

PAID = 0.005163  # one recorded reply, as its run file's spent_usd has it
ARMS = ("champion", "challenger", "champion")


def run(data_dir: Path, replies: tuple[str, ...], max_usd: float, *, flaky_bars: bool = False
        ) -> tuple[list, list, list]:
    from tradingresearch import grade

    conn, theses, bars = fakea.journal_of(data_dir, ARMS)
    if flaky_bars:  # the first read of daily bars fails; every later one works
        daily, calls = bars.daily, []

        def once_down(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError("the bars feed timed out (injected)")
            return daily(*args, **kwargs)

        bars.daily = once_down
    sent: list[dict] = []
    try:
        out = grade.judge(conn, bars, fakea.replaying(sent, replies), prices=fakea.prices(), data_dir=data_dir,
                          max_usd=max_usd)
    except Exception as exc:
        raise AssertionError(f"grade.judge raised {fakea.shown(exc)} after {len(sent)} request(s) (replies "
                             f"{list(replies)}): one thesis's failure stopped the run, and the theses after it were "
                             f"never tried.") from None
    return out, sent, theses


def outcome(j) -> str:
    said = f"P1 {j.verdict}" if j.verdict is not None else f"not judged ({fakea.masked(str(j.error))[:70]})"
    return f"{said}, cost ${j.cost_usd:.6f}"


def test_one_cap_covers_the_whole_run(tmp_path):
    out, sent, theses = run(tmp_path, ("recorded",), max_usd=0.045)
    assert len(out) == 3 and [j.thesis.thesis_id for j in out] == [t.thesis_id for t in theses], (
        f"grade.judge returned {len(out)} outcome(s) for 3 waiting theses: every thesis to_judge lists gets one, "
        f"judged or not, in its order, so `tr grade --judge` can say what happened to each."
    )
    assert sent, (
        f"grade.judge sent no request for 3 waiting theses under a $0.045 cap: {[outcome(j) for j in out]}. The "
        f"first call fits the cap (the budget's worst-case estimate is about $0.043), so the first thesis gets judged."
    )
    assert len(sent) == 1, (
        f"Under a $0.045 cap for the run, grade.judge sent {len(sent)} requests: {[outcome(j) for j in out]}. After "
        f"the first call spent ${PAID}, $0.039837 is left, which cannot cover the budget's estimate of another call's "
        f"worst case (about $0.043): the cap is for the whole run, not for each call."
    )
    first, second, third = out
    assert first.verdict == "pass" and abs(first.cost_usd - PAID) < 1e-6, (
        f"The first thesis: {outcome(first)}; expected P1 pass, cost ${PAID}"
    )
    assert second.verdict is None and "does not fit" in str(second.error), (
        f"The second thesis: {outcome(second)}; the budget refused its call (BudgetExceeded: its worst-case estimate "
        f"does not fit what is left), and its outcome should say so."
    )
    assert third.verdict is None and "next run" in str(third.error) and third.cost_usd == 0, (
        f"The third thesis: {outcome(third)}. Once the cap cannot cover a call, every later thesis waits for the next "
        f"run without trying (the capped branch of the loop)."
    )


def test_one_failure_does_not_stop_the_run_and_every_call_is_counted(tmp_path):
    from tradingresearch import evals

    out, sent, _ = run(tmp_path, ("no_verdict", "failed", "recorded"), max_usd=0.25)
    reply = fakea.answer("no_verdict").json()["choices"][0]["message"]["content"]
    with pytest.raises(evals.CannotGrade) as said:
        evals.p1_verdict(reply)
    assert len(sent) == 3 and len(out) == 3, f"grade.judge sent {len(sent)} requests for 3 theses, expected 3"
    first, second, third = out
    assert first.verdict is None and str(said.value) in str(first.error), (
        f"The first reply held no verdict; its thesis shows {outcome(first)}. It should keep why: "
        f"{str(said.value)[:60]!r}..."
    )
    assert second.verdict is None and "http_400" in str(second.error), (
        f"The second call failed (HTTP 400); its thesis shows {outcome(second)}. It should keep why (http_400)."
    )
    assert third.verdict == "pass", f"The third reply passed; its thesis shows {outcome(third)}"
    costs = [round(j.cost_usd, 6) for j in out]
    assert costs == [PAID, 0.0, PAID], (
        f"The three costs are {costs}; the run files say {[PAID, 0.0, PAID]}: the reply with no verdict was paid "
        f"like the pass, the rejected request cost nothing. Each thesis's cost is what the run files its call added "
        f"say they spent, so the cap counts every paid reply."
    )


def test_a_paid_reply_with_no_verdict_counts_against_the_cap(tmp_path):
    out, sent, _ = run(tmp_path, ("no_verdict", "recorded"), max_usd=0.048)
    assert len(sent) == 1, (
        f"Under a $0.048 cap, grade.judge sent {len(sent)} requests: {[outcome(j) for j in out]}. The first reply held "
        f"no verdict but was paid (${PAID}), so $0.042837 is left, which cannot cover the budget's estimate of another "
        f"call's worst case (about $0.043): what the run spent counts every paid reply, judged or not."
    )


def test_the_cap_counts_what_the_whole_run_spent(tmp_path):
    out, sent, _ = run(tmp_path, ("recorded",), max_usd=0.05)
    assert len(sent) == 2, (
        f"Under a $0.05 cap, grade.judge sent {len(sent)} requests: {[outcome(j) for j in out]}. After two calls "
        f"the run spent ${2 * PAID:.6f}, so $0.039674 is left, which cannot cover another call's worst case (about "
        f"$0.043). What is left is the cap minus everything this run spent so far, not minus the last call alone."
    )


def test_any_other_failure_stays_on_its_thesis(tmp_path):
    out, sent, _ = run(tmp_path, ("recorded",), max_usd=0.25, flaky_bars=True)
    first, second, third = out
    assert first.verdict is None and "the bars feed timed out (injected)" in str(first.error), (
        f"The bars failed (RuntimeError) while the first thesis was being judged; its thesis shows {outcome(first)}. "
        f"It should keep why."
    )
    assert (second.verdict, third.verdict, len(sent)) == ("pass", "pass", 2), (
        f"After the first thesis's bars failed, grade.judge sent {len(sent)} request(s): "
        f"{[outcome(j) for j in out]}. Any failure other than the cap stays on its thesis and the run goes on."
    )


def test_a_refused_call_costs_nothing(tmp_path):
    out, _, _ = run(tmp_path, ("recorded",), max_usd=0.045)
    second = out[1]
    assert second.cost_usd == 0, (
        f"The second thesis: {outcome(second)}. The budget refused its call, so it sent nothing and added no run "
        f"file: its cost is $0. A thesis's cost is what the run files its own call added say, not the newest file's."
    )

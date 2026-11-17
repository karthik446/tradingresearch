"""`tr report` (SPIKE §7.5, §7.6, §7.2 2x2): hand-computed Wilson, cluster bootstrap and MDE numbers, the empty state,
teacher exclusion, and one synthetic thesis graded end to end through the real reconcile and grade. No model call."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from gigai_core.score import ScoreRecord

from factories import analysis, snapshot, thesis
from test_grade import D0, D1, D2, D3, NOW, Bars, ny, seed, settle
from tradingresearch import grade, journal, report
from tradingresearch.cli import main
from tradingresearch.records import RULES_VERSION, EntryRule, Event, NoTrade

Z = 1.959963984540054  # two-sided 95%
Z_POWER = 0.8416212335729143  # power 0.8


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def trades(per_session: list[list[tuple[float, float | None]]]) -> tuple[report.Trade, ...]:
    """Trades from [(r_net, shadow_r_net), ...] per entry session, sessions on consecutive days."""
    start = date(2026, 12, 1)
    return tuple(report.Trade(f"th_{i}_{j}", start + timedelta(days=i), r, s, 1.0, -0.5)
                 for i, items in enumerate(per_session) for j, (r, s) in enumerate(items))


def test_win_rate_is_the_hand_computed_wilson_interval():
    cards = report.stats_lines(trades([[(1.0, 0.0)], [(-1.0, 0.0)], [(2.0, 0.0)], [(0.0, 0.0)]]))
    centre = (0.5 + Z**2 / 8) / (1 + Z**2 / 4)  # 2 wins of 4: (p + z²/2n) / (1 + z²/n)
    half = Z * math.sqrt(0.25 / 4 + Z**2 / 64) / (1 + Z**2 / 4)
    assert cards[0] == f"  win rate 2/4 = 50.0%, 95% CI [{centre - half:.1%}, {centre + half:.1%}] (Wilson)"
    assert cards[0] == "  win rate 2/4 = 50.0%, 95% CI [15.0%, 85.0%] (Wilson)"


def test_the_mde_line_uses_the_measured_sigma():
    rows = trades([[(1.0, None)], [(-1.0, None)], [(2.0, None)], [(0.0, None)]])
    sd = math.sqrt(5 / 3)  # stdev of 1, -1, 2, 0 around 0.5
    mde = (Z + Z_POWER) * sd / 2
    assert report.detectable(rows) == (f"  with n = 4, only effects >= {mde:.2f} R are detectable "
                                       f"(sigma {sd:.2f} R from these trades, alpha 0.05, power 0.8)")
    assert f"{mde:.2f}" == "1.81"
    assert "not computable" in report.detectable(rows[:1])


def test_equal_session_means_give_an_exact_bootstrap_interval():
    rows = trades([[(2.0, 1.5), (-1.0, -1.5)]] * 10)  # every session averages +0.5, real - shadow is +0.5 each
    boot = report.mean_r(rows)
    assert (boot.difference, boot.ci.lower, boot.ci.upper, boot.clusters) == pytest.approx((0.5, 0.5, 0.5, 10))
    paired = report.real_vs_shadow(rows)
    assert (paired.difference, paired.ci.lower, paired.ci.upper) == pytest.approx((0.5, 0.5, 0.5))


def test_the_bootstrap_interval_stays_within_the_session_means_and_is_seeded():
    means = [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, -2.0, 0.25, 0.75, 3.0]
    rows = trades([[(m, 0.0)] for m in means])
    boot = report.mean_r(rows)
    assert min(means) <= boot.ci.lower < boot.difference < boot.ci.upper <= max(means)
    assert boot.difference == pytest.approx(sum(means) / len(means))
    assert report.mean_r(rows) == boot  # seed 0: a rerun prints the same interval


def test_under_ten_sessions_the_interval_is_insufficient():
    rows = trades([[(1.0, 0.0), (0.5, 0.0)]] * 9)
    assert report.mean_r(rows) is None and report.real_vs_shadow(rows) is None
    lines = report.stats_lines(rows)
    assert lines[1] == "  mean r_net +0.75 R, 95% CI insufficient (9 sessions < 10)"
    assert lines[2] == "  real - shadow +0.75 R over 18 pairs, 95% CI insufficient (9 sessions < 10)"
    assert lines[3] == "  median MFE +1.00 R, median MAE -0.50 R"


def test_the_two_by_two_counts_outcome_against_process_and_leaves_unknowns_out():
    rows = tuple(report.Trade(f"th_{i}", date(2026, 12, 1), r, 0.0, 1.0, -0.5, p1) for i, (r, p1) in enumerate(
        [(1.0, "met"), (2.0, "met"), (0.5, "not_met"), (-1.0, "met"), (-1.0, "not_met"), (0.0, "not_met"),
         (1.0, "unknown"), (1.0, None)]))
    assert report.two_by_two(rows) == {"Earned": 2, "Lucky": 1, "Unlucky": 1, "Deserved": 2}
    w = report.wilson_interval(3, 6)
    assert report.process_lines(rows) == [
        f"  P1 met 3/6 = 50.0%, 95% CI [{w.ci.lower:.1%}, {w.ci.upper:.1%}] (Wilson); 1 unknown excluded",
        "               P1 met       P1 not met",
        "  r_net > 0    Earned 2     Lucky 1",
        "  r_net <= 0   Unlucky 1    Deserved 2"]
    assert report.process_lines(rows[-1:]) == ["  P1: no judged trades"]


def test_an_empty_journal_prints_counts_and_no_closed_trades_yet(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    main(["report", "--horizon", "swing"])
    assert capsys.readouterr().out.splitlines()[1:] == [
        "champion swing: 0 theses: 0 closed (0 graded), 0 expired, 0 cancelled, 0 open, 0 proposed",
        "  fill rate n/a (0 of 0) (filled / (filled + expired)); abstention n/a (0 of 0) "
        "(no-trades / main-analysis decisions for swing, both arms)",
        "  no closed trades yet",
        "cost per tr daily run: no run recorded"]
    with pytest.raises(SystemExit):
        main(["report", "--arm", "teacher"])  # the teacher arm has no scorecard


def expired(conn, ticker: str):
    """A champion short thesis whose stop entry at 110 is never reached on D1: EXPIRED."""
    a = analysis(ticker=ticker, session=D0, snapshot=snapshot(ticker=ticker, session=D0, values={"close": 100.0}))
    journal.add_analysis(conn, a, sources=[])
    late = thesis(a.analysis_id, ticker=ticker, rules_version=RULES_VERSION, stop=98.0, target=115.0,
                  invalidation_price=98.0, hold_sessions=2, terms_class=a.terms_class,
                  entry=EntryRule(kind="stop", price=110.0, window_start=ny(D1, "09:30"), window_end=ny(D1, "16:00")))
    journal.add(conn, late, Event(event_id=f"ev_{ticker}", subject_id=late.thesis_id, state="PROPOSED", at=NOW,
                                  recorded_at=NOW, price=None, reason="written", bars_source_id=None,
                                  rules_version=RULES_VERSION))
    return late


def test_a_thesis_graded_through_reconcile_and_grade_lands_on_its_horizon_card(conn):
    winner = seed(conn, "FAKEA")  # long stop 101, stop 98, target 106 (test_grade): fills D1, target on D2
    expired(conn, "FAKEB")
    seed(conn, "FAKEC", arm="teacher")
    journal.add(conn, NoTrade(analysis_id=winner.analysis_id, horizon="day", reason="no setup", created_at=NOW))
    bars = Bars()
    for day in (D1, D2, D3):
        settle(conn, bars, day)
    grade.run(conn, bars, D3, now=NOW)
    assert conn.execute("SELECT thesis_id FROM grade").fetchall() == [(winner.thesis_id,)]  # never the teacher's
    [short, day] = report.cards(conn, ["champion"], ["short", "day"])
    assert (short.states, short.filled, short.no_trades, short.answered) == ({"CLOSED": 1, "EXPIRED": 1}, 1, 0, 2)
    assert (day.states, day.no_trades, day.answered, day.trades) == ({}, 1, 1, ())
    g = report.graded(conn, winner.thesis_id)
    [t] = short.trades
    assert (t.session, t.r_net, t.mfe_r, t.mae_r) == (D1, g.outcome.r_net, g.outcome.mfe_r, g.outcome.mae_r)
    assert g.outcome.r_gross == pytest.approx(5 / 3)  # (106 - 101) / (101 - 98)
    assert t.shadow_r_net == journal.shadow_outcome(conn, g.shadow_id).r_net and t.p1 is None
    lines = report.render([short, day], report.run_costs(conn))
    assert lines[1:5] == [
        "champion short: 2 theses: 1 closed (1 graded), 1 expired, 0 cancelled, 0 open, 0 proposed",
        "  fill rate 1/2 = 50.0% (filled / (filled + expired)); abstention 0/2 = 0.0% "
        "(no-trades / main-analysis decisions for short, both arms)",
        "  win rate 1/1 = 100.0%, 95% CI [20.7%, 100.0%] (Wilson)",  # 1 / (1 + z²)
        f"  mean r_net {g.outcome.r_net:+.2f} R, 95% CI insufficient (1 sessions < 10)"]
    assert "  with n = 1, the detectable effect is not computable (sigma needs at least 2 closed trades)" in lines
    assert "  P1: no judged trades" in lines
    assert lines[-4:-1] == ["champion day: 0 theses: 0 closed (0 graded), 0 expired, 0 cancelled, 0 open, 0 proposed",
                            "  fill rate n/a (0 of 0) (filled / (filled + expired)); abstention 1/1 = 100.0% "
                            "(no-trades / main-analysis decisions for day, both arms)",
                            "  no closed trades yet"]
    assert report.arms_shown(conn) == ["champion"]


def test_a_process_score_on_the_grade_is_the_p1_result(conn):
    seed(conn, "FAKED")
    bars = Bars()
    for day in (D1, D2, D3):
        settle(conn, bars, day)
    grade.run(conn, bars, D3, now=NOW)
    [(body,)] = conn.execute("SELECT body FROM grade").fetchall()
    g = report.Grade.model_validate_json(body)
    for score_id, value, explanation, want in [("sc_met", 1.0, "held", "met"), ("sc_not", 0.0, "broke", "not_met"),
                                               ("sc_unk", 0.0, "unknown: sector rotation", "unknown")]:
        score = ScoreRecord(score_id=score_id, trace_id="tr_0", grader_id="p1_thesis_quality", grader_version="1",
                            kind="model", value=value, explanation=explanation, recorded_at=datetime.now(UTC))
        journal._insert_score(conn, g.thesis_id, score)
        assert report.p1_result(conn, g.model_copy(update={"process_score_id": score_id})) == want
    assert report.p1_result(conn, g) is None


def test_the_latest_stored_judge_verdict_is_the_p1_result_ahead_of_the_process_score(conn):
    seed(conn, "FAKEJ")
    bars = Bars()
    for day in (D1, D2, D3):
        settle(conn, bars, day)
    grade.run(conn, bars, D3, now=NOW)
    [(body,)] = conn.execute("SELECT body FROM grade").fetchall()
    g = report.Grade.model_validate_json(body)
    score = ScoreRecord(score_id="sc_met", trace_id="tr_0", grader_id="p1_thesis_quality", grader_version="1",
                        kind="model", value=1.0, explanation="held", recorded_at=datetime.now(UTC))
    journal._insert_score(conn, g.thesis_id, score)
    scored = g.model_copy(update={"process_score_id": "sc_met"})
    for verdict, reason, want in [("fail", "the stop broke first", "not_met"), ("pass", "held", "met"),
                                  ("fail", "unknown: sector rotation", "unknown")]:
        journal.add_judge_verdict(conn, g.thesis_id, verdict, reason)
        assert report.p1_result(conn, scored) == want  # the latest row wins over the earlier rows and the score
    assert report.p1_result(conn, g) == "unknown"


def test_run_costs_group_by_daily_run_and_split_out_the_teacher_part(conn):
    for daily_id, reason, cost in [("dy_1", "accepted 1", 0.10), ("dy_1", "teacher m: accepted 1", 0.02),
                                   ("dy_2", "already done", 0.0)]:
        journal.add_daily_run(conn, {"daily_id": daily_id, "session": "2026-11-17", "step": "thesis", "ticker": "AAPL",
                                     "status": "ok", "reason": reason, "ids": [], "cost_usd": cost})
    costs = report.run_costs(conn)
    assert costs == {"dy_1": pytest.approx((0.12, 0.02)), "dy_2": (0.0, 0.0)}
    assert report.cost_line(costs) == ("cost per tr daily run: 2 runs, total $0.120000, mean $0.060000, "
                                       "max $0.120000; teacher steps $0.020000 of the total")

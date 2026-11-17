"""Champion/challenger adoption (SPIKE §8.2-8.3): the decision rule on hand-computed vectors, the rule-change store's
refusals (Prereg shape, late Prereg, second pending change, decide once), the per-session pairs read from the
journal, and `tr learn --status` / `--decide`. No model call."""

import math
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from factories import analysis, thesis
from test_playbook import add_thesis
from tradingresearch import adopt, journal
from tradingresearch.cli import main
from tradingresearch.records import RuleChange

DAYS = [date(2026, 12, 1) + timedelta(days=i) for i in range(30)]  # distinct dates: the clusters
REGISTERED = datetime(2026, 12, 7, 21, 0, tzinfo=UTC)  # 16:00 New York on Monday 2026-12-07, after that open


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def change(change_id: str = "rc_1", registered_at: datetime = REGISTERED, **prereg) -> RuleChange:
    p = journal.rule_prereg("short", "a tighter stop raises session r_net", registered_at)
    return RuleChange(change_id=change_id, description="stop at 1.0 ATR", diff_ref="tight_stop",
                      prereg=p.model_copy(update=prereg), decided="pending")


def decide(champ, chall, champ_p1, chall_p1, n=None, **kw) -> adopt.Decision:
    n = n or len(champ)
    return adopt.decide(champ, chall, champ_p1, chall_p1, DAYS[:n], **kw)


# --- the decision rule, hand-computed -------------------------------------------------------------------------------

def test_a_constant_positive_delta_with_equal_p1_is_adopted():
    # every session: challenger 0.5 - champion 0.0 = 0.5, so every resampled mean is 0.5 and the CI is [0.5, 0.5];
    # P1 1.0 vs 1.0 on every session: guard CI [0, 0] >= -0.10
    d = decide([0.0] * 20, [0.5] * 20, [1.0] * 20, [1.0] * 20)
    assert (d.status, d.n_pairs) == ("adopted", 20)
    assert (d.delta_ci.difference, d.delta_ci.ci.lower, d.delta_ci.ci.upper) == (0.5, 0.5, 0.5)
    assert (d.p1_guard_ci.ci.lower, d.p1_guard_ci.ci.upper) == (0.0, 0.0)


def test_a_p1_drop_beyond_the_margin_rejects_a_winning_change():
    # P1 0.75 - 1.0 = -0.25 every session: guard lower bound -0.25 < -0.10
    d = decide([0.0] * 20, [0.5] * 20, [1.0] * 20, [0.75] * 20)
    assert d.status == "rejected"
    assert d.p1_guard_ci.ci.lower == -0.25
    assert d.reason == "P1 guard lower bound -0.250 is below -0.10"


def test_a_lower_bound_of_exactly_zero_is_not_a_pass():
    d = decide([0.3] * 20, [0.3] * 20, [1.0] * 20, [1.0] * 20)  # delta 0.0 every session: CI [0, 0]
    assert d.status == "rejected"
    assert d.reason == "delta lower bound +0.000 R is not > 0"


def test_a_mixed_positive_delta_is_bounded_by_its_smallest_and_largest_session():
    # deltas alternate 0.25 and 0.75: mean (10 * 0.25 + 10 * 0.75) / 20 = 0.5; a resample mean of values in
    # [0.25, 0.75] stays in [0.25, 0.75], so the lower bound is >= 0.25 > 0
    d = decide([0.0] * 20, [0.25, 0.75] * 10, [1.0] * 20, [1.0] * 20)
    assert d.status == "adopted"
    assert d.delta_ci.difference == pytest.approx(0.5)
    assert 0.25 <= d.delta_ci.ci.lower < d.delta_ci.ci.upper <= 0.75


def test_fewer_pairs_are_pending_before_day_60_and_insufficient_after():
    args = ([0.0] * 12, [0.5] * 12, [1.0] * 12, [1.0] * 12)
    pending, late = decide(*args), decide(*args, day60_reached=True)
    assert (pending.status, pending.n_pairs, pending.reason) == ("pending", 12, "12 of 20 paired sessions so far")
    assert pending.delta_ci.ci.lower == 0.5  # 12 sessions >= 10: the interval is shown, the rule is not applied
    assert (late.status, late.reason) == ("insufficient", "day 60 reached with 12 of 20 paired sessions")


def test_only_the_first_20_sessions_by_date_decide():
    # sessions 21-25 (the latest dates) lose 5 R each, and the input order is reversed: they must not count
    champ, chall = [0.0] * 25, [0.5] * 20 + [-5.0] * 5
    d = adopt.decide(champ[::-1], chall[::-1], [1.0] * 25, [1.0] * 25, DAYS[:25][::-1])
    assert (d.status, d.n_pairs, d.delta_ci.difference) == ("adopted", 20, 0.5)


def test_the_guard_uses_sessions_with_p1_on_both_arms_and_needs_ten():
    sparse = [1.0] * 5 + [None] * 15  # 5 sessions with P1 on both arms < 10
    d = decide([0.0] * 20, [0.5] * 20, sparse, sparse)
    assert (d.status, d.p1_guard_ci) == ("rejected", None)
    assert d.reason == "P1 guard not computable (5 sessions with P1 on both arms < 10)"
    some = [1.0] * 12 + [None] * 8
    assert decide([0.0] * 20, [0.5] * 20, [1.0] * 20, some).p1_guard_ci.clusters == 12


def test_vectors_must_line_up_one_pair_per_session():
    with pytest.raises(ValueError, match="one value per session"):
        adopt.decide([0.0] * 3, [0.0] * 2, [None] * 3, [None] * 3, DAYS[:3])
    with pytest.raises(ValueError, match="repeats"):
        adopt.decide([0.0] * 2, [0.0] * 2, [None] * 2, [None] * 2, [DAYS[0], DAYS[0]])


def test_the_mde_line_is_the_hand_computed_spike_value():
    # 2.80159 / sqrt(20) = 0.6265 at sigma 1.0; * sqrt(2) = 0.8860
    assert 2.80159 / math.sqrt(20) == pytest.approx(0.6265, abs=1e-4)
    empty = adopt.SessionPairs((), (), (), (), (), waiting=None)
    assert adopt.mde_lines(empty) == ["  detectable delta at n = 20: 2.80159/sqrt(n) * sigma = 0.63 R at sigma 1.00, "
                                      "0.89 R at sigma 1.41 (sigma assumed, SPIKE §8.3)"]


def test_activation_is_the_first_session_opening_after_registration():
    assert adopt.activation(REGISTERED) == date(2026, 12, 8)  # registered after the 12-07 open
    assert adopt.activation(datetime(2026, 12, 7, 14, 0, tzinfo=UTC)) == date(2026, 12, 7)  # 09:00 NY, before it
    assert adopt.activation(datetime(2026, 12, 5, 12, 0, tzinfo=UTC)) == date(2026, 12, 7)  # a Saturday


# --- the rule-change store ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("field", "value", "match"), [
    ("primary_metric", "session_r_net_delta", "primary_metric"), ("primary_metric", "win_rate:short", "primary_metric"),
    ("pass_rule", "delta_ci_lower >= 0", "pass_rule"), ("guard_metric", None, "guard_metric"),
    ("margin", 0.2, "margin"), ("n_planned", 30, "n_planned"),
])
def test_a_prereg_that_breaks_spike_8_2_is_refused(conn, field, value, match):
    with pytest.raises(ValueError, match=match):
        journal.add_rule_change(conn, change(**{field: value}))
    assert journal.rule_changes(conn) == []


def test_a_change_is_stored_pending_and_listed(conn):
    journal.add_rule_change(conn, change())
    assert journal.rule_changes(conn) == [change()]
    assert journal.rule_changes(conn, "pending") == [change()] and journal.rule_changes(conn, "adopted") == []
    with pytest.raises(ValueError, match="stored pending"):
        journal.add_rule_change(conn, change("rc_2").model_copy(update={"decided": "adopted"}))


def test_a_second_pending_change_is_refused(conn):
    journal.add_rule_change(conn, change())
    with pytest.raises(ValueError, match="one challenger at a time: rc_1 is still pending"):
        journal.add_rule_change(conn, change("rc_2"))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):  # the index holds even past the Python check
        conn.execute("INSERT INTO rule_change (change_id, horizon, registered_at, decided, body, record_sha256, "
                     "created_at) VALUES ('rc_3', 'short', 'x', 'pending', '{}', 'x', 'x')")


def test_a_prereg_registered_after_the_first_challenger_thesis_is_refused(conn):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    journal.add(conn, thesis(a.analysis_id, arm="challenger"))  # stored now
    late = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(ValueError, match="not before the first challenger thesis"):
        journal.add_rule_change(conn, change(registered_at=late))
    journal.add_rule_change(conn, change(registered_at=datetime(2026, 1, 2, tzinfo=UTC)))  # registered before it
    assert [c.change_id for c in journal.rule_changes(conn)] == ["rc_1"]


def test_a_decision_is_made_once_and_the_prereg_never_changes(conn):
    journal.add_rule_change(conn, change())
    journal.decide_rule_change(conn, "rc_1", "rejected")
    assert journal.rule_changes(conn)[0].decided == "rejected"
    assert journal.rule_change_decided_at(conn, "rc_1") is not None
    with pytest.raises(ValueError, match="already rejected: a decision is final"):
        journal.decide_rule_change(conn, "rc_1", "adopted")
    with pytest.raises(ValueError, match="a decision is one of"):
        journal.decide_rule_change(conn, "rc_1", "pending")
    with pytest.raises(KeyError):
        journal.decide_rule_change(conn, "rc_9", "adopted")


@pytest.mark.parametrize("sql", [
    "UPDATE rule_change SET body = '{}'", "UPDATE rule_change SET registered_at = 'x'",
    "UPDATE rule_change SET decided = 'pending', decided_at = NULL", "DELETE FROM rule_change",
])
def test_the_store_triggers_refuse_edits_past_the_python_checks(conn, sql):
    journal.add_rule_change(conn, change())
    conn.execute("UPDATE rule_change SET decided = 'adopted', decided_at = 'now'")  # the one allowed move
    with pytest.raises(sqlite3.IntegrityError, match="rule_change"):
        conn.execute(sql)


def test_a_pending_change_cannot_edit_its_prereg_either(conn):
    journal.add_rule_change(conn, change())
    with pytest.raises(sqlite3.IntegrityError, match="only a pending decision changes, once"):
        conn.execute("UPDATE rule_change SET decided = 'adopted', decided_at = 'now', horizon = 'day'")


def test_a_new_change_is_registered_after_the_last_decision(conn):
    journal.add_rule_change(conn, change(registered_at=datetime(2026, 1, 2, tzinfo=UTC)))
    journal.decide_rule_change(conn, "rc_1", "insufficient")
    with pytest.raises(ValueError, match="not after the last decision"):
        journal.add_rule_change(conn, change("rc_2", registered_at=datetime(2026, 1, 3, tzinfo=UTC)))
    journal.add_rule_change(conn, change("rc_2", registered_at=datetime.now(UTC) + timedelta(days=1)))
    assert [(c.change_id, c.decided) for c in journal.rule_changes(conn)] == [
        ("rc_1", "insufficient"), ("rc_2", "pending")]


# --- pairs from the journal and the command -------------------------------------------------------------------------

def seed_pairs(conn) -> None:
    """Registered 2026-12-07 after the open, so pairs start 2026-12-08. Per session on the short horizon:
    12-07 before activation; 12-08 champion +1.0 (P1 pass), challenger +1.5 (P1 fail) and an expired challenger;
    12-09 challenger -0.5 only; 12-10 a swing champion trade only (no short trade: 0 vs 0); 12-11 a challenger still
    open, which stops the pairs; 12-14 graded, but after the waiting session."""
    journal.add_rule_change(conn, change())
    add_thesis(conn, date(2026, 12, 7), r_net=9.0)
    add_thesis(conn, date(2026, 12, 8), r_net=1.0, p1="pass")
    add_thesis(conn, date(2026, 12, 8), arm="challenger", r_net=1.5, p1="fail")
    add_thesis(conn, date(2026, 12, 8), arm="challenger", final="EXPIRED")
    add_thesis(conn, date(2026, 12, 9), arm="challenger", r_net=-0.5)
    add_thesis(conn, date(2026, 12, 10), horizon="swing", r_net=3.0)
    add_thesis(conn, date(2026, 12, 14), r_net=2.0)
    add_thesis(conn, date(2026, 12, 11), arm="challenger", final="OPEN")


def test_session_vectors_sum_r_per_arm_with_zero_for_no_trade(conn):
    seed_pairs(conn)
    pairs = adopt.sessions_r(conn, "rc_1")
    assert pairs == adopt.SessionPairs(
        sessions=(date(2026, 12, 8), date(2026, 12, 9), date(2026, 12, 10)), champion_r=(1.0, 0.0, 0.0),
        challenger_r=(1.5, -0.5, 0.0), champion_p1=(1.0, None, None), challenger_p1=(0.0, None, None),
        waiting=date(2026, 12, 11))
    assert adopt.decide_pairs(pairs, day60=False).status == "pending"


def cli_journal(tmp_path, monkeypatch) -> sqlite3.Connection:
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    return journal.connect(tmp_path / "journal.db")


def test_status_lists_the_change_its_pairs_the_rule_and_the_mde(tmp_path, monkeypatch, capsys):
    seed_pairs(cli_journal(tmp_path, monkeypatch))
    main(["learn", "--status"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "rule changes (SPIKE §8.2-8.3): 1 registered"
    assert out[1] == f"rule: {adopt.RULE}"
    assert out[2] == ("rc_1 [pending] short: stop at 1.0 ATR (diff tight_stop; registered 2026-12-07 21:00 UTC, "
                      "active from 2026-12-08)")
    assert out[3] == ("  paired sessions so far: 3 of 20; waiting on session 2026-12-11 (a thesis is not graded, "
                      "expired or cancelled yet)")
    assert out[4:6] == ["  delta session r_net (challenger - champion) insufficient (3 sessions < 10)",
                        "  P1 met-rate guard (challenger - champion) insufficient (1 sessions < 10)"]
    assert out[6] == "  the rule today: pending (3 of 20 paired sessions so far)"
    # deltas (0.5, -0.5, 0.0): sample SD 0.5; 2.80159 * 0.5 / sqrt(20) = 0.313
    assert out[8] == "  measured sigma 0.50 R over 3 pairs: detectable delta at n = 20 is 0.31 R"


def test_decide_with_too_few_pairs_writes_nothing(tmp_path, monkeypatch, capsys):
    conn = cli_journal(tmp_path, monkeypatch)
    seed_pairs(conn)
    main(["learn", "--decide", "rc_1"])
    assert capsys.readouterr().out.splitlines()[-1] == "rc_1: pending, 3 of 20 paired sessions so far; nothing written"
    assert journal.rule_changes(conn)[0].decided == "pending"
    with pytest.raises(SystemExit, match="no row with change_id = 'rc_9'"):
        main(["learn", "--decide", "rc_9"])


def test_an_empty_journal_has_no_changes_but_states_the_rule(tmp_path, monkeypatch, capsys):
    cli_journal(tmp_path, monkeypatch)
    main(["learn", "--status"])
    assert capsys.readouterr().out.splitlines() == [
        "rule changes (SPIKE §8.2-8.3): none registered yet; a change is pre-registered before its first challenger "
        "thesis", f"rule: {adopt.RULE}", adopt.mde_lines(adopt.SessionPairs((), (), (), (), (), None))[0]]

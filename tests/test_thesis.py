"""`tr thesis` checks and writes, on the recorded real AAPL reply plus hand-mutated copies; `tr open`. No fake model."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from gigai_core.graders.protocol import CannotGrade

from tradingresearch import journal, thesis as th
from tradingresearch.cli import main
from tradingresearch.commands.thesis import analysis_for, horizons_to_ask
from tradingresearch.records import RULES_VERSION, Analysis

FIXTURES = Path(__file__).parent / "fixtures" / "thesis"
ANALYSIS = Analysis.model_validate_json((FIXTURES / "AAPL_2026-11-16.analysis.json").read_text())
REPLY = json.loads((FIXTURES / "AAPL_2026-11-16.reply.json").read_text())
WRITTEN_AT = datetime(2026, 11, 17, 3, 46, tzinfo=UTC)  # when the real reply was written
NEXT_OPEN = datetime(2026, 11, 17, 14, 30, tzinfo=UTC)
OPINION = "cl_ba1ecc8934034a7d"
ALL = ("day", "short", "swing")


def written(arm="champion", at=WRITTEN_AT) -> th.Written:
    return th.Written(arm, at, "trace_test", "openrouter:test", "restricted", "sha256:" + "3" * 64)


def swing(**changes) -> dict:
    """The real reply's accepted swing thesis with some fields changed."""
    return {**REPLY["theses"][0], **changes}


def check(theses, no_trade=(), asked=("swing",), analysis=ANALYSIS, **kw) -> th.Checked:
    return th.validate({"theses": list(theses), "no_trade": list(no_trade)}, analysis, asked, written(**kw))


def reasons(checked: th.Checked) -> list[tuple[str, str]]:
    return [(r.horizon, r.reason) for r in checked.rejected]


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    journal.add_analysis(c, ANALYSIS, sources=[])
    yield c
    c.close()


def test_the_real_reply_gives_one_swing_thesis_and_two_no_trades():
    checked = th.validate(REPLY, ANALYSIS, ALL, written())
    assert checked.rejected == []
    assert [n.horizon for n in checked.no_trades] == ["day", "short"]
    [t] = checked.theses
    assert (t.horizon, t.direction, t.setup_type, t.entry.kind, t.entry.price) == (
        "swing", "long", "pullback_to_level", "limit", 343.41)
    assert (t.entry.window_start, t.entry.window_end) == (NEXT_OPEN, datetime(2026, 11, 18, 21, 0, tzinfo=UTC))
    assert (t.rules_version, t.regime, t.arm, t.created_at) == (RULES_VERSION, "bull-high", "champion", WRITTEN_AT)


@pytest.mark.parametrize(("changes", "reason"), [
    ({"evidence": []}, "no_evidence"),
    ({"evidence": ["cl_made_up"]}, "unknown_evidence"),
    ({"evidence": [OPINION]}, "opinion_only_evidence"),
    ({"hold_sessions": 3}, "hold_sessions"),
    ({"stop": 345.0}, "stop_side"),
    ({"direction": "short"}, "stop_side"),
    ({"target": 340.0}, "target_side"),
    ({"stop": 342.0}, "stop_floor"),  # 1.41 from entry; floor is 0.25 x 8.05 = 2.01
    ({"invalidation_price": 344.0}, "invalidation"),  # beyond the entry
    ({"invalidation_price": 330.0}, "invalidation"),  # beyond the stop
    ({"entry_kind": "market_open"}, "not_a_thesis"),  # market_open with a price (Thesis rule 1)
    ({"setup_type": "momentum"}, "not_a_thesis"),
    ({"stop": None}, "not_a_thesis"),
    ({"prediction": "x" * 301}, "not_a_thesis"),  # S1 bound (GUARDS-SPIKE §2.3)
    ({"evidence": [REPLY["theses"][0]["evidence"][0]] * 2}, "not_a_thesis"),  # S3: each claim once
])
def test_each_broken_rule_is_rejected_with_its_reason(changes, reason):
    checked = check([swing(**changes)])
    assert checked.theses == [] and reasons(checked) == [("swing", reason)]


def test_a_market_open_entry_is_checked_against_the_close():
    short = swing(direction="short", entry_kind="market_open", entry_price=None, stop=360.0, target=343.41,
                  invalidation_price=358.0)
    assert len(check([short]).theses) == 1
    assert reasons(check([{**short, "stop": 354.0}])) == [("swing", "stop_floor")]  # 1.22 from the 352.78 close


def test_a_thesis_written_after_the_window_opened_is_rejected():
    assert reasons(check([swing()], at=NEXT_OPEN)) == [("swing", "window_passed")]


def test_validator_6_teacher_theses_need_a_teacher_analysis_and_may_be_written_late():
    assert reasons(check([swing()], arm="teacher")) == [("swing", "arm_mismatch")]
    teacher = ANALYSIS.model_copy(update={"arm": "teacher"})
    assert reasons(check([swing()], analysis=teacher)) == [("swing", "arm_mismatch")]
    late = check([swing()], analysis=teacher, arm="teacher", at=datetime(2026, 11, 30, tzinfo=UTC))
    assert len(late.theses) == 1  # the teacher bound is the analysis session's close, not the clock


def test_horizons_must_be_asked_answered_once_and_all_answered():
    checked = check([swing(), swing()], [{"horizon": "day", "reason": "x"}], asked=("short", "swing"))
    assert reasons(checked) == [("swing", "duplicate_horizon"), ("day", "horizon_not_asked"),
                                ("short", "horizon_missing")]
    assert len(checked.theses) == 1
    assert reasons(th.validate({"claims": []}, ANALYSIS, ALL, written())) == [("-", "not_json_theses")]


def test_windows_follow_the_xnys_calendar():
    assert th.windows(date(2026, 11, 16), "day") == (NEXT_OPEN, datetime(2026, 11, 17, 16, 30, tzinfo=UTC))
    assert th.windows(date(2026, 11, 13), "short")[0] == datetime(2026, 11, 16, 14, 30, tzinfo=UTC)  # weekend
    # Thanksgiving: the next session is the 13:00 ET half day, the swing window ends at Monday's close
    assert th.windows(date(2026, 11, 25), "short")[1] == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    assert th.windows(date(2026, 11, 25), "swing")[1] == datetime(2026, 11, 30, 21, 0, tzinfo=UTC)


def test_the_prompt_lists_claim_ids_the_stop_floor_and_the_windows():
    prompt = th.render(ANALYSIS, ("swing",))
    assert f"{OPINION} | opinion |" in prompt
    assert "STOP FLOOR at the close: 2.01 USD" in prompt
    assert "swing: entry window 2026-11-17 09:30 to 2026-11-18 16:00 ET, hold_sessions 5-20" in prompt
    assert "day: entry window" not in prompt and "Write the claims" not in prompt


def test_store_writes_the_proposed_event_and_no_trades_and_the_trigger_rejects_a_second_live(conn):
    stored = th.store(conn, th.validate(REPLY, ANALYSIS, ALL, written()))
    [t] = stored.theses
    [(state, body)] = conn.execute("SELECT state, body FROM event WHERE subject_id = ?", (t.thesis_id,)).fetchall()
    assert state == "PROPOSED" and json.loads(body)["rules_version"] == RULES_VERSION
    assert {h for (h,) in conn.execute("SELECT horizon FROM no_trade")} == {"day", "short"}
    again = th.store(conn, check([swing()]))
    assert again.theses == [] and reasons(again) == [("swing", "one_live")]
    assert journal.live_horizons(conn, "AAPL", "champion") == {"swing"}
    assert journal.live_horizons(conn, "AAPL", "challenger") == set()


def test_live_horizons_are_skipped_before_the_call_and_a_started_window_refuses(conn, capsys):
    th.store(conn, check([swing()]))
    assert horizons_to_ask(conn, ANALYSIS, "champion", WRITTEN_AT) == ("day", "short")
    assert "skip AAPL swing champion" in capsys.readouterr().out
    assert horizons_to_ask(conn, ANALYSIS, "challenger", WRITTEN_AT) == ALL
    with pytest.raises(SystemExit, match="already started"):
        horizons_to_ask(conn, ANALYSIS, "champion", NEXT_OPEN)


def test_the_analysis_is_found_and_validator_6_refuses_before_any_call(conn):
    args = SimpleNamespace(ticker="AAPL", session="2026-11-16", analysis=None, arm="champion")
    assert analysis_for(conn, args) == ANALYSIS
    with pytest.raises(SystemExit, match="no teacher analysis"):
        analysis_for(conn, SimpleNamespace(**{**vars(args), "arm": "teacher"}))
    with pytest.raises(SystemExit, match="needs a teacher analysis"):
        analysis_for(conn, SimpleNamespace(**{**vars(args), "arm": "teacher", "analysis": ANALYSIS.analysis_id}))


def test_the_grader_scores_the_share_of_theses_that_pass():
    sample = SimpleNamespace(parse_status="ok", output_parsed=REPLY, recorded_at=WRITTEN_AT, trace_id="trace_test")
    expected = th.item_for(ANALYSIS, ALL, "champion").expected
    assert th.ThesesValid().grade(sample, expected).value == 1.0
    sample.output_parsed = {**REPLY, "theses": [swing(hold_sessions=3)]}
    score = th.ThesesValid().grade(sample, expected)
    assert score.value == 0.0 and score.explanation.startswith("swing hold_sessions")
    with pytest.raises(CannotGrade):
        th.ThesesValid().grade(SimpleNamespace(parse_status="invalid_json"), expected)


def test_tr_open_lists_proposed_theses_per_arm(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "verify.env"))
    c = journal.connect(tmp_path / "journal.db")
    journal.add_analysis(c, ANALYSIS, sources=[])
    [t] = th.store(c, check([swing()])).theses
    main(["open"])
    assert capsys.readouterr().out == (
        "thesis_id ticker horizon direction state entry stop target created\n"
        f"{t.thesis_id} AAPL swing long PROPOSED limit@343.41 338.7 360.83 2026-11-16 22:46\n1 open\n")
    main(["open", "--arm", "teacher"])
    assert capsys.readouterr().out.endswith("0 open\n")

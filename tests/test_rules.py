"""The challenger arm in `tr daily` (G11b, SPIKE §8.2-8.3): the rule registry, the refusal of an unknown diff_ref
before any spend, one challenger answer per analysis with idempotent reruns, failures as rows that adopt.py leaves
out, and a synthetic challenger thesis settled, graded and shown on the challenger card only.

The AAPL steps replay the recorded real reply of 2026-11-16 (test_daily) for both arms; the synthetic steps store
test_grade's geometry so the real reconcile and grade settle it over test_grade's bars. No network, no model.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from factories import analysis, snapshot, thesis
from test_daily import ANALYSIS, NOW, REPLY, SESSION, TEACHER_ANALYSIS, Recorded, ranked
from test_grade import D0, D1, D2, D3, NOW as GRADE_NOW, Bars, ny, settle
from tradingresearch import adopt, analyze as an, daily, grade, journal, reconcile_run, report, rules, thesis as th, \
    usage
from tradingresearch.cli import main
from tradingresearch.commands.learn import pair_lines
from tradingresearch.commands.thesis import horizons_to_ask
from tradingresearch.records import RULES_VERSION, Analysis, EntryRule, NoTrade, RuleChange
from tradingresearch.screen import CODE_VERSION, ScreenResult

REGISTERED = datetime(2026, 11, 16, 14, 0, tzinfo=UTC)  # 09:00 New York, before the 2026-11-16 open
CHALLENGER_RUN = Path(__file__).parent / "fixtures" / "usage" / "runs" / "run_c40caab0968e44a3.jsonl"  # a real run
PROMPT_HASHES = Path(__file__).parents[1] / "ci" / "prompt-hashes.json"


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def runs_dir(tmp_path):
    path = tmp_path / "runs"
    path.mkdir()
    return path


def change(diff_ref: str = "example-same-prompt", registered_at: datetime = REGISTERED,
           horizon: str = "swing") -> RuleChange:
    return RuleChange(change_id="rc_1", description="an example change", diff_ref=diff_ref,
                      prereg=journal.rule_prereg(horizon, "the rule raises session r_net", registered_at),
                      decided="pending")


class Challenged(Recorded):
    """test_daily's recorded steps plus the challenger's: the same recorded reply, written as the challenger under
    the rule's filter, or a recorded failure."""

    def __init__(self, *args, error: BaseException | None = None, run_file: Path | None = None, **kw) -> None:
        super().__init__(*args, **kw)
        self.error, self.run_file = error, run_file  # Recorded.fail is the analyze step's
        self.challenged: list[str] = []

    def challenger_thesis(self, a: Analysis, asked: tuple[str, ...], rule: rules.Rule) -> th.Result:
        self.challenged.append(a.analysis_id)
        if self.run_file is not None:  # the saved run file is what the cost is read from
            shutil.copy(self.run_file, self.runs_dir / self.run_file.name)
        if self.error is not None:
            raise self.error
        written = th.Written("challenger", NOW, "trace_test", "openrouter:test", "restricted", "sha256:" + "4" * 64)
        checked = th.validate(REPLY, a, asked, written)
        post = rules.post(rule, a)
        return th.Result(th.store(self.conn, checked if post is None else post(checked)), 0.0, "", "")

    def challenger(self) -> daily.ChallengerSteps:
        return daily.ChallengerSteps(lambda a, now: horizons_to_ask(self.conn, a, "challenger", now),
                                     self.challenger_thesis)


def run(conn, steps: Challenged, runs_dir: Path, challenger: bool = True, **kw) -> daily.Daily:
    options = {"top": 10, "max_usd": 1.0, "now": NOW} | kw
    return daily.run(conn, steps.steps(), SESSION, runs_dir=runs_dir,
                     challenger=steps.challenger() if challenger else None, **options)


def challenger_rows(conn, session: date = SESSION) -> list[dict]:
    return [r for r in journal.daily_runs(conn, session) if r["reason"].startswith("challenger ")]


def arm_theses(conn, arm: str) -> list[tuple[str, str]]:
    return conn.execute("SELECT analysis_id, horizon FROM thesis WHERE arm = ? ORDER BY rowid", (arm,)).fetchall()


# ---------- the registry ----------

def test_the_registry_ships_one_example_filter_and_one_example_prompt_variant():
    examples = {ref: rule for ref, rule in rules.CHALLENGER_RULES.items() if ref.startswith("example-")}
    kinds = sorted(type(rule).__name__ for rule in examples.values())
    assert kinds == ["Filter", "PromptVariant"]
    for ref, rule in examples.items():
        assert rules.resolve(ref) is rule and rule.description.startswith("example")
    variant = rules.resolve("example-same-prompt")
    assert (an.PROMPTS_DIR / f"{variant.prompt}.txt").is_file()
    assert variant.prompt in json.loads(PROMPT_HASHES.read_text())  # locked by ci/gate.py like every prompt
    assert rules.prompt_of(variant) == variant.prompt
    assert rules.prompt_of(rules.resolve("example-breakout-volume")) == th.DEFAULT_PROMPT


def test_the_proposed_entries_are_filters_on_the_champion_prompt():
    """A real entry (week 4: rule-change-1) is a reviewed Filter, not an example, and keeps the champion prompt."""
    proposed = {ref: rule for ref, rule in rules.CHALLENGER_RULES.items() if not ref.startswith("example-")}
    assert "short-sma50-trend" in proposed
    for ref, rule in proposed.items():
        assert rules.resolve(ref) is rule and isinstance(rule, rules.Filter)
        assert rule.description.strip() and not rule.description.startswith("example")
        assert rules.prompt_of(rule) == th.DEFAULT_PROMPT


def test_the_example_filter_drops_a_breakout_without_volume_before_the_store():
    weak = analysis(snapshot=snapshot(values={"close": 230.0, "atr_14": 4.0, "rel_volume": 1.2}))
    strong = analysis(snapshot=snapshot(values={"close": 230.0, "atr_14": 4.0, "rel_volume": 2.0}))
    breakout = thesis(weak.analysis_id, horizon="short", setup_type="breakout_20d")
    pullback = thesis(weak.analysis_id, horizon="swing", setup_type="pullback_to_level")
    flt = rules.resolve("example-breakout-volume")
    out = rules.post(flt, weak)(th.Checked([breakout, pullback], [], []))
    assert out.theses == [pullback]
    assert [(r.horizon, r.reason) for r in out.rejected] == [("short", "rule_filter")]
    assert "rel_volume >= 1.5, got 1.2" in out.rejected[0].detail
    assert rules.post(flt, strong)(th.Checked([breakout], [], [])).theses == [breakout]
    assert rules.post(rules.resolve("example-same-prompt"), weak) is None  # a prompt variant has no filter


def test_an_unknown_diff_ref_is_refused_at_registration_before_anything_is_stored(conn):
    with pytest.raises(ValueError, match="unknown diff_ref 'tight_stop': not in rules.CHALLENGER_RULES"):
        rules.register(conn, change("tight_stop"))
    assert journal.rule_changes(conn) == []
    rules.register(conn, change())
    assert [c.diff_ref for c in journal.rule_changes(conn)] == ["example-same-prompt"]


def test_an_unknown_diff_ref_stored_around_register_is_refused_at_activation_with_no_call(conn, runs_dir, capsys):
    journal.add_rule_change(conn, change("tight_stop"))  # journal.add_rule_change itself does not check the ref
    steps = Challenged(conn, runs_dir, ranked("AAPL"))
    report_ = run(conn, steps, runs_dir)
    assert (steps.thesised, steps.challenged, report_.screen_failed) == (["AAPL"], [], False)
    [row] = challenger_rows(conn)
    assert row["status"] == "failed" and "refused: unknown diff_ref 'tight_stop'" in row["reason"]
    assert rules.unanswered(conn, SESSION, "rc_1") == [ANALYSIS.analysis_id]


def test_tr_thesis_challenger_refuses_without_a_pending_change_or_with_an_unknown_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))  # no key: a refusal must come before the call
    c = journal.connect(tmp_path / "journal.db")
    journal.add_analysis(c, ANALYSIS, [])
    argv = ["thesis", "AAPL", "--session", SESSION.isoformat(), "--arm", "challenger"]
    with pytest.raises(SystemExit, match="a challenger thesis answers a pending rule change"):
        main(argv)
    journal.add_rule_change(c, change("tight_stop"))
    c.close()
    with pytest.raises(SystemExit, match="rc_1: unknown diff_ref 'tight_stop'"):
        main(argv)


# ---------- the challenger in `tr daily` ----------

def test_with_no_pending_change_the_run_and_its_dry_run_print_exactly_what_they_did_before(tmp_path, capsys):
    outputs = []
    for challenger in (False, True):
        for dry_run in (True, False):
            c = journal.connect(":memory:")
            runs = tmp_path / f"runs_{challenger}_{dry_run}"
            runs.mkdir()
            if challenger:  # registered after the session opened: not pending for it
                journal.add_rule_change(c, change(registered_at=datetime(2026, 11, 16, 15, 0, tzinfo=UTC)))
            run(c, Challenged(c, runs, ranked("AAPL")), runs, challenger=challenger, dry_run=dry_run)
            outputs.append(re.sub(r"(an|th)_[0-9a-f]{16}", r"\1", capsys.readouterr().out))
            assert challenger_rows(c) == []
            c.close()
    assert outputs[:2] == outputs[2:]
    assert "challenger" not in "".join(outputs)
    assert outputs[0].splitlines()[-1] == ("daily 2026-11-16 (dry run): would analyze 1, thesis 1, estimated $0.05 "
                                           "(≈$0.02 per analyze, $0.03 per thesis); nothing written to daily_run")


def test_the_challenger_answers_each_analysis_once_and_a_rerun_adds_nothing(conn, runs_dir, capsys):
    rules.register(conn, change())
    steps = Challenged(conn, runs_dir, ranked("AAPL"), run_file=CHALLENGER_RUN)
    report_ = run(conn, steps, runs_dir)
    assert steps.challenged == [ANALYSIS.analysis_id]
    assert arm_theses(conn, "challenger") == [(ANALYSIS.analysis_id, "swing")]  # the champion's own analysis
    assert arm_theses(conn, "champion") == [(ANALYSIS.analysis_id, "swing")]
    [row] = challenger_rows(conn)
    assert journal.live_horizons(conn, "AAPL", "challenger") == journal.live_horizons(conn, "AAPL", "champion") \
        == {"swing"}  # one live thesis per arm: the arms never block each other
    cost = usage.run_cost(CHALLENGER_RUN).cost_usd
    assert (row["status"], row["step"], row["cost_usd"]) == ("ok", "thesis", cost)
    assert row["reason"] == f"challenger rc_1 ({ANALYSIS.analysis_id}): accepted 1, no_trade 2, rejected 0"
    assert report_.spent_usd == pytest.approx(0.017304 + cost)  # inside the run's total, under --max-usd
    out = capsys.readouterr().out.splitlines()
    assert out[-2].startswith("daily 2026-11-16: 2 ok, 0 failed, 0 skipped, 0 stopped; 2 model steps")
    assert out[-1] == (f"challenger rc_1 (example-same-prompt) 2026-11-16: 1 answered, 0 failed, 0 skipped, "
                       f"0 stopped; spent ${cost:.4f}, inside the total above")
    run(conn, steps, runs_dir)
    assert steps.challenged == [ANALYSIS.analysis_id] and len(arm_theses(conn, "challenger")) == 1
    assert [r["status"] for r in challenger_rows(conn)] == ["ok", "skipped"]
    assert challenger_rows(conn)[1]["reason"].endswith(": already done")
    assert capsys.readouterr().out.splitlines()[-2] == "daily 2026-11-16: already done, no model call"
    assert rules.unanswered(conn, SESSION, "rc_1") == []


def test_a_failed_challenger_is_a_row_never_the_exit_code_and_a_rerun_retries_it(conn, runs_dir, capsys):
    rules.register(conn, change())
    for fail in (SystemExit("model call failed: parse_error (run run_y)"), sqlite3.OperationalError("disk I/O")):
        steps = Challenged(conn, runs_dir, ranked("AAPL"), error=fail)
        report_ = run(conn, steps, runs_dir)
        assert report_.screen_failed is False and challenger_rows(conn)[-1]["status"] == "failed"
    reasons = [r["reason"] for r in challenger_rows(conn)]
    assert reasons == [f"challenger rc_1 ({ANALYSIS.analysis_id}): model call failed: parse_error (run run_y)",
                       f"challenger rc_1 ({ANALYSIS.analysis_id}): disk I/O"]
    assert rules.unanswered(conn, SESSION, "rc_1") == [ANALYSIS.analysis_id]
    assert "1 failed" in capsys.readouterr().out.splitlines()[-1]
    run(conn, Challenged(conn, runs_dir, ranked("AAPL")), runs_dir)
    assert challenger_rows(conn)[-1]["status"] == "ok" and rules.unanswered(conn, SESSION, "rc_1") == []


def test_no_challenger_and_the_gates_leave_a_skipped_row_per_decided_analysis(conn, runs_dir):
    rules.register(conn, change())
    steps = Challenged(conn, runs_dir, ranked("AAPL"))
    run(conn, steps, runs_dir, challenger=False)
    [row] = challenger_rows(conn)
    assert (row["status"], row["reason"].split(": ", 1)[1]) == ("skipped", "--no-challenger")
    run(conn, steps, runs_dir, no_model=True)
    assert challenger_rows(conn)[-1]["reason"].endswith(": --no-model") and steps.challenged == []
    assert rules.unanswered(conn, SESSION, "rc_1") == [ANALYSIS.analysis_id]


def test_a_dry_run_plans_the_challenger_and_counts_it_in_the_estimate(conn, runs_dir, capsys):
    rules.register(conn, change())
    steps = Challenged(conn, runs_dir, ranked("AAPL"))
    run(conn, steps, runs_dir, dry_run=True)
    out = capsys.readouterr().out.splitlines()
    assert out[-2] == ("daily 2026-11-16 (dry run): would analyze 1, thesis 1, estimated $0.08 (≈$0.02 per analyze, "
                       "$0.03 per thesis); nothing written to daily_run")
    assert out[-1] == ("challenger rc_1 (example-same-prompt) 2026-11-16 (dry run): would thesis 1, estimated $0.03, "
                       "inside the estimate above")
    assert journal.daily_runs(conn, SESSION) == [] and steps.challenged == []


def test_teacher_analyses_and_theses_are_never_read(conn, runs_dir):
    rules.register(conn, change())
    journal.add_analysis(conn, TEACHER_ANALYSIS, [])
    taught = thesis(TEACHER_ANALYSIS.analysis_id, arm="teacher", terms_class=TEACHER_ANALYSIS.terms_class)
    journal.add(conn, taught)
    journal.add_daily_run(conn, {"daily_id": "dy_t", "session": SESSION.isoformat(), "step": "thesis",
                                 "ticker": "AAPL", "status": "ok", "reason": "teacher x/y: accepted 1", "ids": [],
                                 "cost_usd": 0.0})
    assert rules.champion_ran(conn, SESSION) is False  # a teacher row is not the champion's evening
    steps = Challenged(conn, runs_dir, ranked("AAPL"), error=SystemExit("model call failed: x"))
    run(conn, steps, runs_dir)
    assert steps.challenged == [ANALYSIS.analysis_id]  # never the teacher's analysis
    assert rules.answered(conn, "rc_1", TEACHER_ANALYSIS.analysis_id) is False
    assert rules.unanswered(conn, SESSION, "rc_1") == [ANALYSIS.analysis_id]


# ---------- synthetic end to end: settled, graded, on the challenger card; adopt leaves out failures ----------

def at(day: date, ticker: str) -> list[ScreenResult]:
    return [ScreenResult(session=day, ticker=ticker, points=2, triggers={}, filtered_out=None, rank=1,
                         code_version=CODE_VERSION)]


class Synthetic:
    """One synthetic name a session: both arms write test_grade's long stop-101 entry for D1 (the challenger's target
    104, the champion's 106), or a no-trade / an answer with nothing kept; reconcile and grade wait for D1."""

    def __init__(self, conn, ticker: str, day: date, *, decide: str = "thesis", challenger_fail: bool = False):
        values = {"close": 100.0, "atr_14": 2.0, "sma_20": 99.0, "rel_volume": 2.0}
        self.conn, self.decide, self.challenger_fail = conn, decide, challenger_fail
        self.a = analysis(ticker=ticker, session=day, snapshot=snapshot(ticker=ticker, session=day, values=values))

    def one(self, arm: str, target: float) -> th.Checked:
        t = thesis(self.a.analysis_id, ticker=self.a.ticker, arm=arm, rules_version=RULES_VERSION, stop=98.0,
                   target=target, invalidation_price=98.0, hold_sessions=2, terms_class=self.a.terms_class,
                   entry=EntryRule(kind="stop", price=101.0, window_start=ny(D1, "09:30"), window_end=ny(D1, "16:00")))
        return th.Checked([t], [], [])

    def analyze(self, ticker: str, day: date) -> an.Result:
        journal.add_analysis(self.conn, self.a, [])
        return an.Result(self.a, [], 0.0, "", "")

    def champion(self, a: Analysis, asked: tuple[str, ...]) -> th.Result:
        if self.decide == "thesis":
            return th.Result(th.store(self.conn, self.one("champion", 106.0)), 0.0, "", "")
        no_trade = NoTrade(analysis_id=a.analysis_id, horizon="short", reason="no setup", created_at=NOW)
        return th.Result(th.store(self.conn, th.Checked([], [no_trade], [])), 0.0, "", "")

    def challenger(self, a: Analysis, asked: tuple[str, ...], rule: rules.Rule) -> th.Result:
        if self.challenger_fail:
            raise SystemExit("model call failed: timeout (run run_z)")
        checked = self.one("challenger", 104.0) if self.decide == "thesis" else th.Checked([], [], [])
        return th.Result(th.store(self.conn, rules.post(rule, a)(checked)), 0.0, "", "")

    def run(self, day: date, now: datetime, runs_dir: Path) -> daily.Daily:
        steps = daily.Steps(lambda d: at(day, self.a.ticker), self.analyze,
                            lambda a, n: horizons_to_ask(self.conn, a, "champion", n), self.champion,
                            lambda d, dry: reconcile_run.run(self.conn, None, d, dry_run=dry, now=now),
                            lambda d, dry: grade.run(self.conn, None, d, dry_run=dry, now=now))
        challenger = daily.ChallengerSteps(lambda a, n: horizons_to_ask(self.conn, a, "challenger", n), self.challenger)
        return daily.run(self.conn, steps, day, top=10, max_usd=1.0, runs_dir=runs_dir, now=now, challenger=challenger)


def test_a_challenger_thesis_settles_grades_and_lands_on_the_challenger_card_never_the_champions(conn, runs_dir):
    rules.register(conn, change("example-breakout-volume", horizon="short"))
    Synthetic(conn, "FAKEA", D0).run(D0, NOW, runs_dir)
    [(champion_id,)] = conn.execute("SELECT thesis_id FROM thesis WHERE arm = 'champion'").fetchall()
    [(challenger_id,)] = conn.execute("SELECT thesis_id FROM thesis WHERE arm = 'challenger'").fetchall()
    bars = Bars()
    for day in (D1, D2, D3):
        settle(conn, bars, day)
    grade.run(conn, bars, D3, now=GRADE_NOW)
    assert report.arms_shown(conn, since=None) == ["champion", "challenger"]
    [champion, challenger] = report.cards(conn, ["champion", "challenger"], ["short"], since=None)
    assert [t.thesis_id for t in champion.trades] == [champion_id]
    assert [t.thesis_id for t in challenger.trades] == [challenger_id]
    assert challenger.trades[0].r_net == report.graded(conn, challenger_id).outcome.r_net
    assert report.graded(conn, challenger_id).outcome.r_gross == pytest.approx(1.0)  # (104 - 101) / (101 - 98)
    lines = report.render([champion, challenger], report.run_costs(conn, since=None), since=None)
    assert "challenger short: 1 theses: 1 closed (1 graded), 0 expired, 0 cancelled, 0 open, 0 proposed" in lines
    assert "champion short: 1 theses: 1 closed (1 graded), 0 expired, 0 cancelled, 0 open, 0 proposed" in lines


def test_adopt_waits_on_then_leaves_out_a_session_whose_challenger_failed_and_goes_on_past_it(conn, runs_dir):
    rules.register(conn, change("example-breakout-volume", horizon="short"))
    Synthetic(conn, "FAKEA", D0, challenger_fail=True).run(D0, NOW, runs_dir)
    assert challenger_rows(conn, D0)[0]["status"] == "failed"
    before_d1_opens = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)
    after_d1_opens = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
    pairs = adopt.sessions_r(conn, "rc_1", now=before_d1_opens)  # still answerable: the pairs stop there
    assert (pairs.sessions, pairs.waiting, pairs.excluded) == ((), D0, ())
    Synthetic(conn, "FAKEB", D1, decide="no_trade").run(D1, datetime(2026, 11, 18, 3, 0, tzinfo=UTC), runs_dir)
    assert [r["status"] for r in challenger_rows(conn, D1)] == ["ok"]
    pairs = adopt.sessions_r(conn, "rc_1", now=datetime(2026, 11, 18, 15, 0, tzinfo=UTC))
    assert pairs == adopt.SessionPairs((D1,), (0.0,), (0.0,), (None,), (None,), waiting=None, excluded=(D0,))
    assert adopt.sessions_r(conn, "rc_1", now=after_d1_opens).excluded == (D0,)
    line = pair_lines(pairs, adopt.decide_pairs(pairs, False))[0]
    assert line == "  paired sessions so far: 1 of 20; left out 1, the challenger never answered: 2026-11-16"

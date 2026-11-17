"""The teacher bake-off (SPIKE §9.4, TRAINING-SPIKE §7.1): the date-seeded draw, the experiment cluster key, the
Prereg template and `tr bakeoff`. Everything is offline at $0: seeded journal rows, and the recorded real DeepSeek V4
Pro call of 2026-11-16 replayed at the HTTP transport for the run-file columns; no fake model."""

import dataclasses
from datetime import date
from pathlib import Path

import pytest
from gigai_core import Dataset
from gigai_core.records import Prereg

from factories import T0, analysis, claim, snapshot, thesis
from test_teacher import PRICE, REPLY, TEACHER, context, replaying
from tradingresearch import analyze as an, bakeoff, experiment, grade, journal, screen, teacher
from tradingresearch.cli import main
from tradingresearch.hashing import new_id
from tradingresearch.records import NoTrade, TeacherOutcome

ROOT = Path(__file__).parent.parent
TEN = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO", "CAT"]  # prompt-v2's tickers
DAY = date(2026, 11, 16)
DRAWN = ["HD", "KO", "MSFT", "UNH"]  # draw(DAY, TEN); cross-checked with `shasum -a 256` in the shell
BAKEOFF_DAY = bakeoff.FIRST_SESSION  # 2026-11-17, bake-off session 1; DAY is before it, so the report ignores DAY
BAKEOFF_DRAWN = ["KO", "NVDA", "UNH", "XOM"]  # draw(BAKEOFF_DAY, TEN)
# Dataset.of("prompt-v2", ...) over the relabelled fixture contexts, captured at bc8859b before `cluster` existed.
PROMPT_V2_SHA = "35ed95885c94ad30d6d5af5acd5a34167b424fa139bcc21eacac62b6ff6bb4c4"


# ---------- draw ----------

def test_the_draw_is_fixed_by_the_session_date_not_by_shortlist_order():
    assert teacher.draw(DAY, TEN) == DRAWN
    assert teacher.draw(date(2026, 11, 17), TEN) == ["KO", "NVDA", "UNH", "XOM"]
    assert teacher.draw(date(2026, 11, 18), TEN) == ["AMZN", "MSFT", "NVDA", "XOM"]
    assert teacher.draw(DAY, [*reversed(TEN), "HD", "KO"]) == DRAWN  # order and repeats do not move it


def test_the_draw_names_four_distinct_shortlisted_names_or_the_whole_short_list():
    for offset in range(30):
        names = teacher.draw(date.fromordinal(DAY.toordinal() + offset), TEN)
        assert len(set(names)) == len(names) == teacher.BAKEOFF_NAMES and set(names) <= set(TEN)
    assert teacher.draw(DAY, ["MSFT", "AAPL", "MSFT"]) == ["AAPL", "MSFT"]
    assert teacher.draw(DAY, []) == []


# ---------- cluster ----------

def contexts() -> list[an.Context]:
    """The recorded context relabelled to prompt-v2's 20 ticker-days: what `items` builds, not market data."""
    base = context()
    return [dataclasses.replace(base, ticker=t, session=s) for s in (date(2026, 11, 12), date(2026, 11, 13)) for t in TEN]


def test_the_default_ticker_cluster_keeps_prompt_v2_byte_identical():
    config = experiment.load(ROOT / "experiments" / "prompt-v2.toml")
    assert config.cluster == "ticker"
    built = experiment.items(config, contexts())
    assert [i.model_dump_json() for i in built] == [an.item_for(c).model_dump_json() for c in contexts()]
    assert Dataset.of(config.name, built).ref.sha256 == PROMPT_V2_SHA
    assert sorted({i.cluster_id for i in built}) == sorted(TEN)


def test_a_session_cluster_keys_each_item_on_its_session_date():
    config = dataclasses.replace(experiment.load(ROOT / "experiments" / "prompt-v2.toml"), cluster="session")
    built = experiment.items(config, contexts())
    assert {i.cluster_id for i in built} == {"2026-11-12", "2026-11-13"}
    assert [(i.id, i.prompt) for i in built] == [(i.id, i.prompt) for i in map(an.item_for, contexts())]


def prompt_v2_with(tmp_path, line: str) -> Path:
    path = tmp_path / "exp.toml"
    path.write_text(line + "\n" + (ROOT / "experiments" / "prompt-v2.toml").read_text())
    return path


def test_fewer_than_ten_clusters_are_refused_at_load_naming_the_count(tmp_path):
    with pytest.raises(SystemExit, match="cluster = 'session' gives 2 clusters; compare needs at least 10"):
        experiment.load(prompt_v2_with(tmp_path, 'cluster = "session"'))
    with pytest.raises(SystemExit, match="cluster must be one of ticker, session, not 'day'"):
        experiment.load(prompt_v2_with(tmp_path, 'cluster = "day"'))
    assert experiment.load(prompt_v2_with(tmp_path, 'cluster = "ticker"')).cluster == "ticker"


# ---------- prereg ----------

def test_the_prereg_example_loads_into_a_gigai_core_prereg():
    found = bakeoff.prereg(ROOT / "experiments" / "bakeoff-prereg.example.toml")
    assert isinstance(found, Prereg)
    assert (found.primary_metric, found.guard_metric, found.margin, found.n_planned) == ("p2_p4_pass", "parse_ok",
                                                                                          0.10, 40)
    assert found.registered_at.tzinfo is not None and found.hypothesis and found.pass_rule


def test_the_committed_prereg_loads_and_names_the_first_session_plan_uses():
    path = ROOT / "experiments" / "bakeoff-prereg.toml"
    assert isinstance(bakeoff.prereg(path), Prereg)
    assert f"on or after {bakeoff.FIRST_SESSION.isoformat()}" in path.read_text()


def test_plan_ignores_teacher_analyses_before_the_first_bakeoff_session():
    conn = journal.connect(":memory:")
    screened(conn, DAY, TEN)
    stored(conn, TEACHER.model, "KO", DAY)
    assert bakeoff.plan(conn) == bakeoff.Plan((), (), ())  # 2026-11-16 was a test run, not session 1
    screened(conn, BAKEOFF_DAY, TEN)
    stored(conn, TEACHER.model, "KO", BAKEOFF_DAY)
    found = bakeoff.plan(conn)
    assert found.sessions == (BAKEOFF_DAY,) and found.items == tuple((BAKEOFF_DAY, t) for t in BAKEOFF_DRAWN)


# ---------- report ----------

def screened(conn, day: date, tickers: list[str]) -> None:
    journal.add_screen_results(conn, [dict(session=day.isoformat(), ticker=t, points=2, triggers={}, filtered_out=None,
                                           rank=n, code_version=screen.CODE_VERSION) for n, t in enumerate(tickers, 1)])


def stored(conn, model: str, ticker: str, day: date = BAKEOFF_DAY):
    found = analysis(ticker=ticker, session=day, arm="teacher", model=model, terms_class="trainable")
    journal.add_analysis(conn, found, [])
    return found


def settled(conn, thesis_id: str, checks: dict[str, bool]) -> None:
    journal.add(conn, TeacherOutcome(teacher_outcome_id=new_id("to"), thesis_id=thesis_id, final_state="CANCELLED",
                                     outcome=None, code_checks=checks, outcome_score_id=None, rules_version="1",
                                     settled_at=T0))


def seeded() -> tuple:
    """Bake-off session 1: DeepSeek parses NVDA (a thesis, cancelled) and UNH (a no-trade), stops after KO's analysis
    and has no XOM; an off-draw AAPL analysis is ignored. Qwen and gpt-oss have nothing yet."""
    conn = journal.connect(":memory:")
    screened(conn, BAKEOFF_DAY, TEN)
    ds = TEACHER.model
    nvda = stored(conn, ds, "NVDA")
    written = thesis(nvda.analysis_id, ticker="NVDA", arm="teacher", terms_class="trainable")
    journal.add(conn, written)
    unh = stored(conn, ds, "UNH")
    journal.add(conn, NoTrade(analysis_id=unh.analysis_id, horizon="short", reason="no setup", created_at=T0))
    stored(conn, ds, "KO")
    stored(conn, ds, "AAPL")
    return conn, written


def test_the_report_counts_parse_ok_over_the_drawn_items_and_shows_states_and_verdicts(tmp_path):
    conn, written = seeded()
    settled(conn, written.thesis_id, {})
    plan, rows = bakeoff.report(conn, tmp_path)
    assert plan.sessions == (BAKEOFF_DAY,) and [t for _, t in plan.items] == BAKEOFF_DRAWN
    ds, qwen, oss = rows
    assert (ds.items, ds.parse_ok, ds.states, ds.cost) == (4, 2, {"CANCELLED": 1}, None)
    assert ds.facts_total is None  # the seeded analyses have no run file
    assert ds.verdict == "incomplete: 4/40 items" and ds.p2_p4 == 0.0  # NVDA's thesis cites cl_0, not a claim
    assert (oss.parse_ok, oss.verdict) == (0, "not eligible: parse_ok 0/4")
    text = bakeoff.render(plan, rows)
    assert f"{'incomplete: 4/40 items':<36}0.0%" in text and "no automatic pick" in text
    assert text.endswith("margin (experiments/bakeoff-prereg.toml)")  # the committed prereg, not the example
    assert (ROOT / "experiments" / "bakeoff-prereg.toml").exists()
    assert "deepseek/deepseek-v4-pro" in text and "2/4" in text and "CANCELLED=1" in text


def cited(ticker: str):
    """A teacher analysis whose one fact quotes its snapshot's close, so a thesis citing that fact passes P2."""
    snap = snapshot(ticker=ticker, session=BAKEOFF_DAY)
    close = next(row for row in an.snapshot_rows(snap)[1] if row.name == "close")
    analysis_id = new_id("an")
    fact = claim(analysis_id, source_ids=(close.source_id,), value=close.value)
    return analysis(analysis_id=analysis_id, ticker=ticker, session=BAKEOFF_DAY, arm="teacher", model=TEACHER.model,
                    terms_class="trainable", snapshot=snap, claims=(fact,))


def test_p2_p4_counts_an_item_only_when_every_thesis_it_wrote_passes_on_its_stored_analysis(tmp_path):
    conn = journal.connect(":memory:")
    screened(conn, BAKEOFF_DAY, TEN)
    nvda = cited("NVDA")
    journal.add_analysis(conn, nvda, [])
    good = thesis(nvda.analysis_id, ticker="NVDA", arm="teacher", terms_class="trainable",
                  evidence=(nvda.claims[0].claim_id,))
    journal.add(conn, good)
    assert grade.code_checks(good, nvda) == dict.fromkeys(grade.P2_P4, True)
    assert bakeoff.report(conn, tmp_path)[1][0].p2_p4 == 1 / 4  # unsettled NVDA passes; KO, UNH, XOM have nothing
    journal.add(conn, thesis(nvda.analysis_id, ticker="NVDA", horizon="swing", arm="teacher", terms_class="trainable"))
    assert bakeoff.report(conn, tmp_path)[1][0].p2_p4 == 0.0  # the swing thesis cites cl_0, not a claim: P2 fails


def test_the_fact_share_and_cost_come_from_the_recorded_teacher_run(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: 1894)
    conn = journal.connect(":memory:")
    screened(conn, BAKEOFF_DAY, ["AAPL", "MSFT", "NVDA"])  # a short shortlist: all three are drawn
    session_1 = dataclasses.replace(context(), session=BAKEOFF_DAY)  # the 2026-11-16 reply, relabelled into session 1
    result = an.analyze(conn, session_1, replaying(REPLY, []), model=TEACHER.model, max_usd=0.10,
                        prices={TEACHER.model: PRICE}, data_dir=tmp_path, arm="teacher",
                        terms_class=TEACHER.terms_class)
    assert sum(c.tag == "fact" for c in result.analysis.claims) == 4  # G6's live run: 4 kept, the rest number_in_text
    ds = bakeoff.report(conn, tmp_path)[1][0]
    assert (ds.items, ds.parse_ok) == (3, 0)  # no thesis step stored yet
    assert (ds.facts_valid, ds.facts_total) == (4, 8)  # the reply wrote 8 fact claims; 4 passed the validators
    assert ds.cost is not None and ds.cost.calls == 1 and ds.cost.cost_usd > 0


def test_tr_bakeoff_draw_prints_the_stored_sessions_names_and_refuses_an_unscreened_one(tmp_path, monkeypatch,
                                                                                        capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    screened(journal.connect(tmp_path / "journal.db"), DAY, TEN)
    main(["bakeoff", "draw", "--session", DAY.isoformat()])
    assert capsys.readouterr().out.startswith(f"bake-off draw {DAY}: {' '.join(DRAWN)}  (4 of a shortlist of 10")
    with pytest.raises(SystemExit, match="no stored screen for 2026-11-13"):
        main(["bakeoff", "draw", "--session", "2026-11-13"])
    main(["bakeoff", "report"])
    assert "bake-off sessions none yet (0 of 10), 0 drawn items" in capsys.readouterr().out

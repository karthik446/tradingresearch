"""`tr label` (SPIKE §7.3, ADR-003): blind `show`, `add` refusals and relabels, the judge-verdict store, and kappa on
a hand-computed 2x2. Synthetic theses graded through the real reconcile and grade; no model call."""

import re
from datetime import date

import pytest
from gigai_core.agreement import agreement
from gigai_core.records import LabelRecord

from factories import T0, analysis, claim, thesis
from test_grade import D1, D2, D3, NOW, Bars, seed, settle
from tradingresearch import grade, journal, label
from tradingresearch.cli import main


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def graded(conn, *tickers: str, teacher: str | None = None):
    """Champion theses on `tickers` (and one teacher thesis) settled D1-D3 and graded: each fills D1, exits D2."""
    theses = [seed(conn, ticker) for ticker in tickers]
    if teacher:
        theses.append(seed(conn, teacher, arm="teacher"))
    bars = Bars()
    for day in (D1, D2, D3):
        settle(conn, bars, day)
    grade.run(conn, bars, D3, now=NOW)
    return theses


def rows(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


class Window(Bars):
    """Bars that remember the daily window asked for."""

    def daily(self, ticker: str, start: date, end: date):
        self.window = (start, end)
        return super().daily(ticker, start, end)


# ---------- list / show ----------

def test_list_has_graded_champions_without_a_label_and_never_a_teacher(conn):
    assert label.render_list(conn) == [
        "nothing to label: no graded champion or challenger thesis without a label (0 labelled)"]
    a, b, _ = graded(conn, "FAKEA", "FAKEB", teacher="FAKET")
    assert label.render_list(conn) == [
        f"FAKEA  short champion   {a.thesis_id}", f"FAKEB  short champion   {b.thesis_id}",
        "2 to label, 0 labelled: `tr label show <thesis_id>`, then `tr label add <thesis_id> met|not_met|unknown`"]
    label.add(conn, a.thesis_id, "met")
    assert label.render_list(conn)[0] == f"FAKEB  short champion   {b.thesis_id}"
    assert label.render_list(conn)[-1].startswith("1 to label, 1 labelled")


def test_show_is_blind_to_a_stored_verdict_and_records_nothing(conn):
    [t] = graded(conn, "FAKEA")
    journal.add_judge_verdict(conn, t.thesis_id, "pass", "JUDGE-REASON-the stop was respected", score_id="sc_j")
    label.add(conn, t.thesis_id, "not_met", note="OPERATOR-NOTE")
    before = (rows(conn, "label"), rows(conn, "judge_verdict"), rows(conn, "event"))
    bars = Window()
    out = "\n".join(label.show(conn, bars, t.thesis_id))
    assert "JUDGE-REASON" not in out and "sc_j" not in out and not re.search(r"\bpass\b", out)
    assert "OPERATOR-NOTE" not in out and "not met" not in out  # nor the earlier label
    assert f"prediction: {t.prediction}" in out and f"reason: {t.reason}" in out
    assert "cl_0 | missing from analysis" in out  # seed() cites cl_0, which its analysis does not hold
    assert "exit: target at 106 on 2026-11-18, filled at 101 on 2026-11-17" in out  # grade.py's summary
    assert bars.window == (date(2026, 10, 20), D2)  # 20 sessions before the fill day (no NYSE holiday between)
    assert (rows(conn, "label"), rows(conn, "judge_verdict"), rows(conn, "event")) == before


def test_cited_claims_show_their_values_tags_and_steps():
    a = analysis(analysis_id="an_c", claims=(claim("an_c", claim_id="cl_close", value=101.5),
                                             claim("an_c", claim_id="cl_inf", tag="inference", value=None, unit=None,
                                                   source_ids=(), derived_from=("cl_close",),
                                                   text="Close is above sma_20.", steps="101.5 > 99")))
    assert label.cited(a, ("cl_close", "cl_inf", "cl_gone")) == [
        "cl_close | fact | Close was 101.5 USD.", "cl_inf | inference | Close is above sma_20. (steps: 101.5 > 99)",
        "cl_gone | missing from analysis an_c"]


# ---------- add ----------

def test_add_stores_a_blind_label_record(conn):
    [t] = graded(conn, "FAKEA")
    record = label.add(conn, t.thesis_id, "not_met", note="the reason never showed up", now=NOW)
    [(body,)] = conn.execute("SELECT body FROM label").fetchall()
    assert LabelRecord.model_validate_json(body) == record
    assert (record.item_id, record.label, record.blind, record.relabel_of, record.critique, record.recorded_at) == (
        t.thesis_id, "not met", True, None, "the reason never showed up", NOW)
    assert (record.dataset_id, record.rubric, record.source) == ("p1_thesis_quality", label.RUBRIC, "human")


def test_add_refuses_a_thesis_not_closed_a_teacher_thesis_and_an_unknown_id(conn):
    open_ = seed(conn, "FAKEO")  # PROPOSED: never settled
    teacher = seed(conn, "FAKET", arm="teacher")
    with pytest.raises(label.Refused, match="is PROPOSED with no grade: only a CLOSED thesis"):
        label.add(conn, open_.thesis_id, "met")
    with pytest.raises(label.Refused, match="is a teacher thesis"):
        label.add(conn, teacher.thesis_id, "met")
    with pytest.raises(label.Refused, match="no thesis th_missing"):
        label.add(conn, "th_missing", "met")
    with pytest.raises(label.Refused, match="verdict 'maybe'"):
        label.add(conn, open_.thesis_id, "maybe")
    assert rows(conn, "label") == 0


def test_a_second_label_needs_relabel_and_points_at_the_one_it_replaces(conn):
    [t] = graded(conn, "FAKEA")
    with pytest.raises(label.Refused, match="has no label to replace"):
        label.add(conn, t.thesis_id, "met", relabel=True)
    first = label.add(conn, t.thesis_id, "met")
    with pytest.raises(label.Refused, match=f"already labelled \\({first.label_id}\\); --relabel"):
        label.add(conn, t.thesis_id, "not_met")
    second = label.add(conn, t.thesis_id, "not_met", relabel=True)
    third = label.add(conn, t.thesis_id, "unknown", relabel=True)
    assert (second.relabel_of, third.relabel_of) == (first.label_id, second.label_id)
    assert rows(conn, "label") == 3 and label.labels(conn) == {t.thesis_id: third}


def test_relabel_changes_what_agree_counts(conn):
    a, b = graded(conn, "FAKEA", "FAKEB")
    journal.add_judge_verdict(conn, a.thesis_id, "pass", "held")
    journal.add_judge_verdict(conn, b.thesis_id, "fail", "broke")
    label.add(conn, a.thesis_id, "not_met")
    label.add(conn, b.thesis_id, "not_met")
    assert label.pairing(conn).pairs == ((0, 1), (0, 0))
    label.add(conn, a.thesis_id, "met", relabel=True)
    assert label.pairing(conn).pairs == ((1, 1), (0, 0))  # the latest label wins


# ---------- the judge-verdict store ----------

def test_the_latest_judge_verdict_per_thesis_wins_and_every_call_is_kept(conn):
    a, b = graded(conn, "FAKEA", "FAKEB")
    assert journal.judge_verdict(conn, a.thesis_id) is None and journal.judge_verdicts(conn) == {}
    journal.add_judge_verdict(conn, a.thesis_id, "fail", "unknown: no catalyst stated")
    journal.add_judge_verdict(conn, b.thesis_id, "fail", "broke", score_id="sc_b")
    journal.add_judge_verdict(conn, a.thesis_id, "pass", "held", score_id="sc_a2")
    latest = journal.judge_verdict(conn, a.thesis_id)
    assert (latest["verdict"], latest["reason"], latest["score_id"]) == ("pass", "held", "sc_a2")
    assert {k: v["verdict"] for k, v in journal.judge_verdicts(conn).items()} == {a.thesis_id: "pass",
                                                                                 b.thesis_id: "fail"}
    assert rows(conn, "judge_verdict") == 3
    assert journal.abstained({"verdict": "fail", "reason": "unknown: no catalyst stated"})
    assert not journal.abstained({"verdict": "pass", "reason": "unknown: odd"})
    with pytest.raises(Exception, match="CHECK constraint"):
        journal.add_judge_verdict(conn, a.thesis_id, "met", "not a judge word")


# ---------- agree ----------

def labelled_pairs(conn, cells: list[tuple[str, str, str]]) -> None:
    """One thesis per (label, judge verdict, judge reason); `-` means no row on that side."""
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    for i, (value, verdict, reason) in enumerate(cells):
        t = thesis(a.analysis_id, ticker=f"FAK{i:02d}")
        journal.add(conn, t)
        if value != "-":
            journal.add(conn, LabelRecord(label_id=f"lb_{i}", dataset_id=label.DATASET_ID, item_id=t.thesis_id,
                                          item_version="v0", label=value, source="human", recorded_at=T0, blind=True))
        if verdict != "-":
            journal.add_judge_verdict(conn, t.thesis_id, verdict, reason)


def test_kappa_on_a_hand_computed_two_by_two(conn):
    # human x judge: met/pass 4, met/fail 2, not met/pass 1, not met/fail 3 -> n 10, p_o = 7/10;
    # human met 6/10, judge pass 5/10 -> p_e = 0.6*0.5 + 0.4*0.5 = 0.5; kappa = (0.7 - 0.5) / (1 - 0.5) = 0.4
    labelled_pairs(conn, [("met", "pass", "ok")] * 4 + [("met", "fail", "broke")] * 2 + [("not met", "pass", "ok")]
                   + [("not met", "fail", "broke")] * 3 + [("unknown", "pass", "ok"), ("met", "fail", "unknown: x"),
                                                           ("not met", "-", ""), ("-", "pass", "ok")])
    p = label.pairing(conn)
    assert (len(p.pairs), p.decided, p.unknown_labels, p.abstains, p.not_judged, p.unlabelled_verdicts) == (
        10, 12, 1, 1, 1, 1)
    assert agreement(p.pairs).kappa.kappa == pytest.approx(0.4)
    lines = label.render_agree(p)
    assert lines[:2] == ["agree: n = 10 pairs", "  raw agreement 7/10 = 70.0%"]
    assert lines[2].startswith("  kappa 0.40, 95% CI [") and "(descriptive: n < 30 proposed labels)" in lines[2]
    assert lines[3] == "  judge pass rate on your met: 66.7%; judge fail rate on your not met: 75.0%"
    assert "±0.29" in lines[5] and "0.31 to 0.89" in lines[5]
    assert lines[6].startswith("  thresholds PROPOSED (ADR-003, operator decision Q1 pending; not applied): "
                               "kappa >= 0.6") and "n >= 126" in lines[6]
    assert lines[7] == "  p1_judge stays validated = False: only an ADR that records the measured kappa changes it"
    assert not any(re.search(r"\b(PASS|FAIL|validated = True)\b", line) for line in lines)


def test_kappa_is_undefined_when_both_raters_use_one_category(conn):
    labelled_pairs(conn, [("met", "pass", "ok")] * 3)
    assert label.render_agree(label.pairing(conn))[2].startswith("  kappa undefined: ")


def test_agree_waits_for_labels_then_for_judge_verdicts(conn):
    assert label.render_agree(label.pairing(conn))[0] == "agree: awaiting labels (n = 0 pairs; kappa needs at least 2)"
    labelled_pairs(conn, [("met", "-", ""), ("not met", "pass", "ok"), ("-", "fail", "x")])
    lines = label.render_agree(label.pairing(conn))
    assert lines[0] == "agree: awaiting judge verdicts (n = 1 pairs; kappa needs at least 2)"
    assert lines[1] == ("  labels: 2 met/not met, 0 unknown (left out); of the 2: 1 paired, 0 judge unknown: "
                        "(left out), 1 not judged; 1 judged without a label")


# ---------- the command ----------

def test_tr_label_list_add_and_agree_on_a_journal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    conn = journal.connect(tmp_path / "journal.db")
    [t] = graded(conn, "FAKEA")
    conn.close()
    main(["label", "list"])
    assert capsys.readouterr().out.splitlines()[0] == f"FAKEA  short champion   {t.thesis_id}"
    main(["label", "add", t.thesis_id, "not_met", "--note", "no volume"])
    out = capsys.readouterr().out
    assert re.fullmatch(rf"stored lb_\w+: {t.thesis_id} not met \(blind\)\n", out)
    with pytest.raises(SystemExit, match="already labelled"):
        main(["label", "add", t.thesis_id, "met"])
    main(["label", "add", t.thesis_id, "met", "--relabel"])
    assert ", replaces lb_" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no thesis th_missing"):
        main(["label", "show", "th_missing"])  # refused before any Alpaca call
    main(["label", "agree"])
    assert capsys.readouterr().out.startswith("agree: awaiting labels (n = 0 pairs")

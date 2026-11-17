"""`tr label --claims` (TRAINING-SPIKE §7.2 row 5, §7.4): blind claim labels of teacher claims. The view never shows
the model's tag or a verdict; duplicates, blank labellers and main-arm claims are refused. No model call."""

from datetime import UTC, datetime

import pytest

from factories import T0, analysis, claim, snapshot, source
from tradingresearch import journal, label
from tradingresearch.cli import main
from tradingresearch.hashing import new_id
from tradingresearch.records import ClaimLabel

TEACHER = dict(arm="teacher", terms_class="trainable", provider_route="openrouter:deepinfra/fp8/flex",
               model="deepseek/deepseek-v4-pro")
NOW = datetime(2026, 11, 17, 22, 0, tzinfo=UTC)


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def teacher_analysis(conn, ticker: str = "AAPL"):
    """A teacher analysis with one fact (close, cited) and one inference built on it."""
    analysis_id = new_id("an")
    fact = claim(analysis_id, claim_id=f"cl_{ticker.lower()}_fact", text="Close was {value} USD.", value=231.5)
    inference = claim(analysis_id, claim_id=f"cl_{ticker.lower()}_inf", text="Price sits above its 20-day range.",
                      tag="inference", value=None, unit=None, source_ids=(), derived_from=(fact.claim_id,),
                      steps="close > high_20")
    a = analysis(analysis_id=analysis_id, ticker=ticker, snapshot=snapshot(ticker=ticker), claims=(fact, inference),
                 **TEACHER)
    journal.add_analysis(conn, a, [source()])
    return a


def rows(conn) -> int:
    return conn.execute("SELECT count(*) FROM claim_label").fetchone()[0]


# ---------- list ----------

def test_list_has_teacher_claims_only_and_states_n_unlabelled_and_n_labelled(conn):
    assert label.render_claims_list(conn) == [
        "nothing to label: no teacher claim without a claim label (0 unlabelled, 0 labelled)"]
    journal.add_analysis(conn, analysis(), [source()])  # a main-arm (Sonnet) analysis: its claims never show
    teacher_analysis(conn, "AAPL")
    lines = label.render_claims_list(conn)
    assert lines[:2] == ["AAPL   2026-11-13 cl_aapl_fact", "AAPL   2026-11-13 cl_aapl_inf"]
    assert lines[-1].startswith("2 unlabelled, 0 labelled: `tr label --claims show <claim_id>`")
    label.add_claim_label(conn, "cl_aapl_fact", "fact", "operator", now=NOW)
    assert label.render_claims_list(conn)[0] == "AAPL   2026-11-13 cl_aapl_inf"
    assert label.render_claims_list(conn)[-1].startswith("1 unlabelled, 1 labelled")
    label.add_claim_label(conn, "cl_aapl_inf", "opinion", "operator", now=NOW)
    assert label.render_claims_list(conn) == [
        "nothing to label: no teacher claim without a claim label (0 unlabelled, 2 labelled)"]


# ---------- show (blind) ----------

def test_show_is_blind_no_model_tag_no_verdict_no_earlier_label(conn):
    teacher_analysis(conn)
    view = label.show_claim(conn, "cl_aapl_inf")
    body = "\n".join(view[:-1])  # the last line is the instruction listing every tag, the same for every claim
    for word in ("fact", "inference", "opinion", "claims_valid", "close > high_20", "steps", "derived", "cl_aapl_fact"):
        assert word not in body, word
    assert view[1] == "text: Price sits above its 20-day range."
    assert view[-1].endswith("`tr label --claims add cl_aapl_inf --tag fact|inference|opinion "
                             "[--supported|--unsupported] --labeller NAME`")
    label.add_claim_label(conn, "cl_aapl_inf", "inference", "operator", supported=True, now=NOW)
    again = "\n".join(label.show_claim(conn, "cl_aapl_inf")[:-1])
    assert again == body  # an earlier label never shows
    assert rows(conn) == 1


def test_show_fills_the_value_and_lists_the_cited_source_rows(conn):
    teacher_analysis(conn)
    view = label.show_claim(conn, "cl_aapl_fact")
    assert view[:5] == [
        view[0], "text: Close was 231.5 USD.", "value: 231.5 USD",
        "cited sources (source_id | kind | uri | feed | retrieved_at)",
        f"  src_0123456789abcdef | computed | tradingresearch:indicators.py#rsi_14 | feed - | {T0.isoformat()}"]
    assert view[0].startswith("cl_aapl_fact AAPL 2026-11-13 (analysis an_")


def test_show_refuses_an_unknown_claim_and_a_main_arm_claim(conn):
    main_arm = analysis()
    journal.add_analysis(conn, main_arm, [source()])
    with pytest.raises(label.Refused, match="no claim cl_missing"):
        label.show_claim(conn, "cl_missing")
    with pytest.raises(label.Refused, match="from a main analysis: claim labels are for teacher claims"):
        label.show_claim(conn, main_arm.claims[0].claim_id)


# ---------- add ----------

def test_add_writes_one_blind_claim_label_with_the_clock(conn):
    teacher_analysis(conn)
    record = label.add_claim_label(conn, "cl_aapl_fact", "fact", "  kar ", supported=False, now=NOW)
    assert (record.tag, record.supported, record.labeller, record.blind, record.labelled_at) == (
        "fact", False, "kar", True, NOW)
    assert journal.get(conn, ClaimLabel, record.claim_label_id) == record
    assert label.add_claim_label(conn, "cl_aapl_inf", "opinion", "kar").supported is None
    assert label.claim_labels(conn)["cl_aapl_inf"].labelled_at.tzinfo is not None


@pytest.mark.parametrize(("claim_id", "tag", "labeller", "why"), [
    ("cl_aapl_fact", "fact", "", "--labeller is blank"),
    ("cl_aapl_fact", "fact", "   ", "--labeller is blank"),
    ("cl_aapl_fact", "guess", "kar", "tag 'guess'"),
    ("cl_missing", "fact", "kar", "no claim cl_missing"),
])
def test_add_refuses_a_blank_labeller_an_unknown_tag_and_an_unknown_claim(conn, claim_id, tag, labeller, why):
    teacher_analysis(conn)
    with pytest.raises(label.Refused, match=why):
        label.add_claim_label(conn, claim_id, tag, labeller, now=NOW)
    assert rows(conn) == 0


def test_add_refuses_a_duplicate_and_a_main_arm_claim(conn):
    teacher_analysis(conn)
    first = label.add_claim_label(conn, "cl_aapl_fact", "fact", "kar", now=NOW)
    with pytest.raises(label.Refused, match=f"already labelled \\({first.claim_label_id}\\)"):
        label.add_claim_label(conn, "cl_aapl_fact", "opinion", "someone else", now=NOW)
    main_arm = analysis()
    journal.add_analysis(conn, main_arm, [])
    with pytest.raises(label.Refused, match="claim labels are for teacher claims"):
        label.add_claim_label(conn, main_arm.claims[0].claim_id, "fact", "kar", now=NOW)
    assert rows(conn) == 1


# ---------- CLI ----------

def test_cli_claims_list_show_add_and_the_p1_mode_untouched(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    teacher_analysis(journal.connect(tmp_path / "journal.db"))
    main(["label", "--claims", "list"])
    assert capsys.readouterr().out.splitlines()[-1].startswith("2 unlabelled, 0 labelled")
    main(["label", "--claims", "show", "cl_aapl_fact"])
    assert "text: Close was 231.5 USD." in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--labeller is blank"):
        main(["label", "--claims", "add", "cl_aapl_fact", "--tag", "fact", "--labeller", " "])
    with pytest.raises(SystemExit, match="needs --tag fact\\|inference\\|opinion and --labeller NAME"):
        main(["label", "--claims", "add", "cl_aapl_fact", "--tag", "fact"])
    with pytest.raises(SystemExit, match="not a P1 verdict"):
        main(["label", "--claims", "add", "cl_aapl_fact", "met", "--tag", "fact", "--labeller", "kar"])
    main(["label", "--claims", "add", "cl_aapl_fact", "--tag", "fact", "--supported", "--labeller", "kar"])
    out = capsys.readouterr().out
    assert out.startswith("stored clb_") and "cl_aapl_fact fact, supported by kar (blind)" in out
    with pytest.raises(SystemExit, match="already labelled"):
        main(["label", "--claims", "add", "cl_aapl_fact", "--tag", "opinion", "--labeller", "kar"])
    main(["label", "--claims", "list"])
    assert capsys.readouterr().out.splitlines()[-1].startswith("1 unlabelled, 1 labelled")
    with pytest.raises(SystemExit, match="are for --claims"):
        main(["label", "add", "th_x", "met", "--tag", "fact"])
    with pytest.raises(SystemExit, match="a P1 label needs a verdict"):
        main(["label", "add", "th_x"])
    with pytest.raises(SystemExit, match="--claims has list, show and add"):
        main(["label", "--claims", "agree"])

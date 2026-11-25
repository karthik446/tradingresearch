"""w5l1.1 the claims that cite a section: a claim cites a section when one of its own `source_ids` is a row that
masking.section_of puts in it; the score is the share of those claims that validate_claims keeps. A claim citing two
sections counts in both; text, `derived_from` and source ids that are not rows cite nothing.

Each check builds its grader as the four registered ones are built (w5l1.3): a subclass of the stub's
SectionGrounded that only sets `section`. Every sample is a parsed reply about the FAKEA context (tools/fakea.py) in
which at least one claim cites the section graded; a section no claim cites, a reply that did not parse and the
explanation are w5l1.2.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import evals  # noqa: E402

HEADLINE = [r.name for r in fakea.rows("headlines")]


def grader(section: str):
    """A SectionGrounded for `section`: a subclass that sets it, as the registered graders are."""
    return type(f"Lab{section.title()}", (evals.SectionGrounded,), {"section": section})()


def share(section: str, claims: list, g=None) -> float:
    """The section's score on a parsed sample of `claims`, checked on every call: a value from 0 to 1."""
    g = g or grader(section)
    try:
        score = g.grade(fakea.sample_of({"claims": claims}), fakea.expected())
    except NotImplementedError:
        raise AssertionError(f"SectionGrounded raised NotImplementedError grading {section} on claims "
                             f"[{fakea.describe(claims)}]: write cites and grade (TODO(w5l1.1))") from None
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"the {section} grader raised {exc!r} on claims [{fakea.describe(claims)}]; at least "
                             f"one of them cites a {section} row, so it returns a score") from None
    assert 0.0 <= score.value <= 1.0, f"the {section} grader scored {score.value!r}; a share runs from 0 to 1"
    return score.value


def expect(section: str, claims: list, want: float, why: str, g=None) -> None:
    got = share(section, claims, g)
    assert got == pytest.approx(want), (
        f"{section} scored {got:.3f} on claims [{fakea.describe(claims)}]; expected {want:.3f}: {why}")


def test_the_share_counts_only_the_claims_citing_the_section():
    claims = [fakea.fact("i1", "sma_20", value=1.0), fakea.fact("i2", "close"),
              fakea.fact("e1", "revenue_CY2026Q2", value=5.0), fakea.fact("h1", HEADLINE[0]),
              fakea.fact("i3", "sma_50")]
    expect("indicators", claims, 2 / 3, "i1, i2 and i3 cite indicator rows and validate_claims rejects i1 (its "
           "value is not the row's); e1 and h1 cite other sections and do not count here")
    expect("edgar", claims, 0.0, "e1 is the one claim citing an EDGAR row, and it is rejected")
    expect("headlines", claims, 1.0, "h1 is the one claim citing a headline row, and it is kept")
    other = [fakea.fact("l1", "level_hvn_1"), fakea.fact("i1", "close"), fakea.fact("l2", "level_hvn_2", value=1.0)]
    expect("levels", other, 0.5, "l1 and l2 cite level rows; l2 is rejected")
    expect("indicators", other, 1.0, "i1 is the one claim citing an indicator row, and it is kept")


def test_a_claim_citing_two_sections_counts_in_both():
    claims = [fakea.fact("m1", "close", "level_hvn_1"), fakea.fact("m2", "sma_20", "level_hvn_2", value=1.0),
              fakea.fact("x1", HEADLINE[1], "close", value=None, text="Up on the news.")]
    expect("indicators", claims, 2 / 3, "m1, m2 and x1 each cite an indicator row (x1 after a headline row); m2 is "
           "rejected")
    expect("levels", claims, 0.5, "m1 and m2 each cite a level row (after an indicator row); m2 is rejected")
    expect("headlines", claims, 1.0, "x1 cites a headline row and is kept")
    wide = [fakea.fact("w1", "level_hvn_1", "level_hvn_2", HEADLINE[0], "close"), fakea.fact("i1", "sma_20", value=1.0)]
    expect("indicators", wide, 0.5, "w1 cites four rows, the close row the fourth, and is kept; i1 is rejected")
    expect("headlines", wide, 1.0, "w1's third row is a headline row")


def test_only_the_claims_own_source_ids_cite():
    close = fakea.row("close")
    claims = [fakea.fact("t1", "level_hvn_1", text="Near the close and its sma_20, the level reads {value}."),
              fakea.fact("i1", "close"),
              dict(id="d1", tag="inference", text="The close leads its moving average.", value=None, unit=None,
                   source_ids=[], derived_from=["i1"], steps="It sits above the average."),
              dict(id="u1", tag="fact", text="The row reads {value}.", value=close.value, unit=close.unit,
                   source_ids=[close.source_id, "src_not_a_row"], derived_from=[], steps=None),
              dict(id="s1", tag="fact", text="The row reads {value}.", value=close.value, unit=close.unit,
                   source_ids=close.source_id, derived_from=[], steps=None)]
    expect("indicators", claims, 0.5, "i1 and u1 cite the close row in their source_ids, and u1 is rejected (it also "
           "cites an id that is no row); t1 only names indicators in its text, d1 is derived from i1 and cites "
           "nothing itself, and s1's source_ids is not a list, so none of the three cites an indicator row")
    expect("levels", claims, 1.0, "t1 cites a level row and is kept")


def test_an_id_that_is_no_row_cites_nothing():
    close = fakea.row("close")
    unknown = dict(id="u1", tag="fact", text="The row reads {value}.", value=close.value, unit=close.unit,
                   source_ids=["src_not_a_row"], derived_from=[], steps=None)
    spaced = dict(unknown, id="w1", source_ids=[" " + close.source_id])
    expect("indicators", [fakea.fact("i4", "close"), unknown], 1.0, "u1's one id names no row, so u1 cites no "
           "section, whatever the id spells; i4 is the one claim citing an indicator row")
    expect("indicators", [fakea.fact("i4", "close"), spaced], 1.0, "w1's one id is the close row's with a space in "
           "front, and no row has that id, so w1 cites nothing")
    upper = dict(unknown, id="c1", source_ids=[close.source_id.upper()])
    expect("indicators", [fakea.fact("i4", "close"), upper], 1.0, "c1's one id is the close row's in upper case, "
           "and no row has that id either: an id cites a row when it equals the row's, letter for letter")


def test_an_inference_keeps_the_claim_of_another_section_it_derives_from():
    close = fakea.row("close")
    claims = [fakea.fact("l1", "level_hvn_1"),
              dict(id="n1", tag="inference", text="The close sits near the level.", value=None, unit=None,
                   source_ids=[close.source_id], derived_from=["l1"], steps="The close is just under the level.")]
    expect("indicators", claims, 1.0, "n1 cites the close row and derives from l1, a kept level claim: "
           "validate_claims runs on the whole reply, so n1 is kept")


def test_every_rejected_claim_counts():
    claims = [fakea.fact("i1", "sma_20", value=1.0), fakea.fact("i3", "sma_50", value=2.0), fakea.fact("i4", "close")]
    expect("indicators", claims, 1 / 3, "i1 and i3 are rejected for the same reason, and each is a citing claim "
           "that fails")


def test_the_citing_claim_may_sit_anywhere_in_the_reply():
    others = [fakea.fact("e1", "revenue_CY2026Q2"), fakea.fact("h1", HEADLINE[0]), fakea.fact("l1", "level_hvn_1")]
    for at in range(len(others) + 1):
        claims = others[:at] + [fakea.fact("i1", "sma_20", value=1.0)] + others[at:] + [fakea.fact("i2", "close")]
        expect("indicators", claims, 0.5, f"i1 (rejected, at position {at + 1}) and i2 (kept, last) are the claims "
               f"citing indicator rows")
    many = [fakea.fact(f"l{k}", "level_hvn_1") for k in range(11)] + [fakea.fact("i1", "sma_20", value=1.0),
                                                                     fakea.fact(8, "close"), fakea.fact("i2", "close")]
    expect("indicators", many, 1 / 3, "the 12th to 14th claims cite indicator rows; the 12th is rejected, and so is "
           "the 13th, whose id is the number 8: validate_claims reports it under the id as text, '8'")
    long = ([fakea.fact("i1", "close")] + [fakea.fact(f"l{k}", "level_hvn_1") for k in range(22)]
            + [fakea.fact("i2", "sma_50"), fakea.fact("i3", "sma_20", value=1.0)])
    expect("indicators", long, 2 / 3, "the 1st, 24th and 25th claims cite indicator rows; the 25th is rejected")


def test_one_grader_grades_sample_after_sample():
    g = grader("indicators")
    mixed = [fakea.fact("i1", "sma_20", value=1.0), fakea.fact("i2", "close"), fakea.fact("i3", "sma_50")]
    clean = [fakea.fact("i1", "close"), fakea.fact("i9", "sma_50")]
    expect("indicators", mixed, 2 / 3, "i1 is rejected", g)
    expect("indicators", clean, 1.0, "the same grader instance grades every sample of a run, and nothing of the "
           "previous sample may count in this one", g)
    expect("indicators", mixed, 2 / 3, "the first sample again, after another", g)


def test_the_recorded_reply_scores_six_of_seven_indicators_and_its_headline():
    claims = fakea.recorded()["claims"]
    expect("indicators", claims, 6 / 7, "7 claims of the recorded reply cite indicator rows; validate_claims "
           "rejects c10 (empty_placeholder)")
    expect("headlines", claims, 1.0, "c9 is the one claim citing a headline row, and it is kept")


def test_claims_sharing_an_id_each_count():
    claims = [fakea.fact("i1", "sma_20", value=1.0), fakea.fact("i1", "sma_50", value=2.0), fakea.fact("i2", "close"),
              fakea.fact("h1", HEADLINE[0]), fakea.fact("h1", HEADLINE[1])]
    expect("indicators", claims, 1 / 3, "three claims cite indicator rows, two of them under the one id i1, and both "
           "of those are rejected: the share counts claims, not distinct ids")
    expect("headlines", claims, 1.0, "two claims cite headline rows under the one id h1, and both are kept")


def test_a_long_reply_counts_every_citing_claim():
    claims = ([fakea.fact(f"i{k}", "close") for k in range(36)]
              + [fakea.fact(f"w{k}", "sma_20", value=1.0) for k in range(4)])
    expect("indicators", claims, 0.9, "all 40 claims cite indicator rows and the last four are rejected: 36 of 40, "
           "however long the reply")

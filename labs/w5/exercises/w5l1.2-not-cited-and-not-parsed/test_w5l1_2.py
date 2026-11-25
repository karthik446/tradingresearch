"""w5l1.2 not cited, not parsed, and the explanation. A section no claim cites raises CannotGrade with a message
starting `not_cited`: no score, so a mean never counts it as 1.0. A parsed reply with no claims list, or none that
cite the section, is not cited. A reply that did not parse (parse_status other than "ok") raises CannotGrade for
another reason. Below 1.0 the explanation is `<reasons>: <k> of <n> claims citing <section> fail`, the failed
claims' rejection reasons sorted and each named once.

The grader is built as in w5l1.1 (a SectionGrounded subclass that sets `section`); samples are about the FAKEA
context (tools/fakea.py), the recorded analyze-3 reply among them.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.graders.protocol import CannotGrade  # noqa: E402

from tradingresearch import evals  # noqa: E402

HEADLINE = [r.name for r in fakea.rows("headlines")]


def grader(section: str):
    return type(f"Lab{section.title()}", (evals.SectionGrounded,), {"section": section})()


def graded(section: str, parsed, parse_status: str = "ok", g=None):
    """The Score, or the CannotGrade raised; any other exception fails the check."""
    try:
        return (g or grader(section)).grade(fakea.sample_of(parsed, parse_status), fakea.expected())
    except CannotGrade as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"the {section} grader raised {exc!r} on {parse_status} reply {fakea.describe(parsed)}; "
                             f"it returns a score or raises CannotGrade") from None


def not_cited(section: str, parsed, why: str, g=None) -> None:
    got = graded(section, parsed, g=g)
    shown = repr(got) if isinstance(got, CannotGrade) else f"{got.value} ({got.explanation!r})"
    assert isinstance(got, CannotGrade) and str(got).startswith("not_cited"), (
        f"{section} gave {shown} on claims [{fakea.describe(parsed)}]; expected CannotGrade('not_cited: ...'): "
        f"{why}. A section nobody cites has no score; a 1.0 would count as a pass in every mean")


def explained(section: str, claims: list, want: str, value: float) -> None:
    got = graded(section, {"claims": claims})
    assert not isinstance(got, CannotGrade), f"{section} raised {got!r} on claims [{fakea.describe(claims)}]"
    assert got.explanation == want and got.value == pytest.approx(value), (
        f"{section} gave {got.value:.3f} ({got.explanation!r}) on claims [{fakea.describe(claims)}]; expected "
        f"{value:.3f} ({want!r}): the failed claims' reasons, sorted and each once, then how many of the claims "
        f"citing {section} fail")


def test_a_section_no_claim_cites_gets_no_score():
    recorded = fakea.recorded()
    not_cited("levels", recorded, "no claim of the recorded reply cites a level row")
    not_cited("edgar", recorded, "no claim of the recorded reply cites an EDGAR row")
    only = [fakea.fact("i1", "close"), fakea.fact("l1", "level_hvn_1", value=1.0)]
    not_cited("headlines", {"claims": only}, "i1 and l1 cite an indicator and a level row")
    not_cited("indicators", {"claims": [fakea.fact("h1", HEADLINE[0])]}, "h1 cites a headline row")
    g = grader("levels")
    not_cited("levels", recorded, "the recorded reply cites no level row", g)
    got = graded("levels", {"claims": only}, g=g)
    assert not isinstance(got, CannotGrade) and got.value == 0.0, (
        f"the same levels grader gave {got!r} on a later sample whose l1 cites a level row (rejected); expected 0.0: "
        f"a grader grades every sample on its own")


@pytest.mark.parametrize("parsed", [{}, {"claims": []}, {"claims": "none"}, [], {"claims": ["c1", 3]},
                                    {"claims": [{"id": "c1", "tag": "fact", "text": "No sources."}]}],
                         ids=["no-claims-key", "empty", "claims-not-a-list", "reply-a-list", "claims-not-objects",
                              "no-source-ids"])
def test_a_parsed_reply_with_no_citing_claim_is_not_cited(parsed):
    not_cited("indicators", parsed, "a parsed reply without a claim that cites a row cites no section")


def test_a_reply_that_did_not_parse_cannot_be_graded():
    for status, parsed in [("not_json", None), ("not_json", {"claims": [fakea.fact("i1", "close")]}),
                           ("invalid", {"claims": [fakea.fact("i1", "close")]}), ("not_parsed", None)]:
        got = graded("indicators", parsed, parse_status=status)
        shown = repr(got) if isinstance(got, CannotGrade) else f"{got.value} ({got.explanation!r})"
        assert isinstance(got, CannotGrade) and not str(got).startswith("not_cited"), (
            f"indicators gave {shown} on a reply that did not parse (parse_status {status!r}, parsed "
            f"{fakea.describe(parsed)}); expected CannotGrade with another reason than not_cited: a reply that did "
            f"not parse is not graded at all, whatever it holds, and it is not a section nobody cited")


def test_the_explanation_names_sorted_distinct_reasons_and_the_count():
    regime = fakea.row("regime_spy")
    claims = [fakea.fact("i1", "sma_20", value=1.0), fakea.fact("i2", "close", text="The close is 5 {value}."),
              fakea.fact("e1", "revenue_CY2026Q2", value=5.0), fakea.fact("i3", "sma_50", value=2.0),
              dict(id="u1", tag="fact", text="The row reads {value}.", value=1.0, unit="USD",
                   source_ids=["src_not_a_row"], derived_from=[], steps=None),
              fakea.fact("i4", "close"),
              dict(id="i5", tag="fact", text="The regime is {value}.", value=None, unit=None,
                   source_ids=[regime.source_id], derived_from=[], steps=None)]
    explained("indicators", claims,
              "empty_placeholder, number_in_text, unsourced_number: 4 of 5 claims citing indicators fail", 0.2)
    explained("levels", [fakea.fact("l1", "level_hvn_1", value=1.0), fakea.fact("l2", "level_hvn_2")],
              "unsourced_number: 1 of 2 claims citing levels fail", 0.5)
    explained("headlines", [fakea.fact("h1", HEADLINE[0], text="Up 5 on the news.")],
              "number_in_text: 1 of 1 claims citing headlines fail", 0.0)


def test_the_recorded_reply_explains_its_indicator_failure():
    explained("indicators", fakea.recorded()["claims"], "empty_placeholder: 1 of 7 claims citing indicators fail",
              6 / 7)

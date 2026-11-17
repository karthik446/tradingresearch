"""Per-section grounding beyond the week-5 contract: malformed replies, the headline boundary, direct sources only.

Spec: evals/specs/section_grounding.md. Builds on test_week5's FAKEA context and claim helpers.
"""

from __future__ import annotations

import pytest
from gigai_core.graders.protocol import CannotGrade
from test_week5 import SECTIONS, expected, fact, grade, headline_name, name_of, sample_of

from tradingresearch import evals


@pytest.mark.parametrize("parsed", [{}, {"claims": "c1"}, {"claims": [1, "c1", None]},
                                    {"claims": [{"id": "c1", "source_ids": "src_x"}]}],
                         ids=["no_claims_key", "claims_not_a_list", "claims_not_dicts", "source_ids_not_a_list"])
def test_a_malformed_reply_is_not_cited_rather_than_a_crash(parsed):
    for section in SECTIONS:
        [grader] = evals.graders([name_of(section)])
        with pytest.raises(CannotGrade, match=r"^not_cited"):
            grader.grade(sample_of(parsed), expected())


def test_a_headline_claim_with_a_number_fails_only_on_the_number():
    """A headline row has no number: a null value passes on the citation alone, a value is `unsourced_number`."""
    assert grade("headlines", [fact("c1", headline_name())]).value == 1.0
    score = grade("headlines", [fact("c1", headline_name()), fact("c2", headline_name(), value=3.0)])
    assert score.value == 0.5 and score.explanation == "unsourced_number: 1 of 2 claims citing headlines fail", score


def test_only_direct_source_ids_count_toward_a_section():
    """An inference citing no row (only `derived_from`) is not counted for its parent's section."""
    inference = dict(id="c2", tag="inference", text="So the trend holds.", value=None, unit=None, source_ids=[],
                     derived_from=["c1"], steps=None)
    score = grade("indicators", [fact("c1", "close"), inference])
    assert score.value == 1.0 and score.explanation == "1 of 1 claims citing indicators pass", score

"""w5l1.3 four registered graders and the drop. One registered code grader per masking.SECTIONS, with the id
`<section>_grounded`, a `section` and a `drop` attribute (default: nothing dropped). `evals.graders(names, drop)`
builds them as an experiment arm does and hands a drop arm's list to every grader that has the attribute; a claim
citing a row the arm never saw then fails (`dropped_source`) in each section it cites. The drop belongs to the
grader an arm builds: another arm's grader, or the next sample's rows, are not affected by it.

Samples are about the FAKEA context (tools/fakea.py), the recorded analyze-3 reply among them.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.graders.protocol import CannotGrade  # noqa: E402

from tradingresearch import evals, masking  # noqa: E402

HEADLINE = [r.name for r in fakea.rows("headlines")]
CLAIMS = [fakea.fact("i1", "close"), fakea.fact("x1", HEADLINE[1], "close", value=None, text="Up on the news."),
          fakea.fact("h1", HEADLINE[0]), fakea.fact("e1", "revenue_CY2026Q2")]


def built(section: str, drop: tuple[str, ...] = ()):
    """The section's grader, built by evals.graders as an arm builds it."""
    name = f"{section}_grounded"
    registered = sorted(n for n in evals.GRADERS if n.endswith("_grounded"))
    assert name in evals.GRADERS, f"evals.GRADERS has no {name}; the *_grounded ids registered: {registered}"
    [g] = evals.graders([name], drop)
    return g


def graded(g, claims, expected=None):
    try:
        return g.grade(fakea.sample_of({"claims": claims}), expected or fakea.expected())
    except CannotGrade as exc:
        return exc


def scores(section: str, claims, drop, want, why: str, g=None, expected=None) -> None:
    """`want` is (value, explanation) or "not_cited"."""
    got = graded(g or built(section, drop), claims, expected)
    shown = got if isinstance(got, CannotGrade) else (got.value, got.explanation)
    ok = (str(got).startswith("not_cited") if want == "not_cited" else
          not isinstance(got, CannotGrade) and got.value == pytest.approx(want[0])
          and want[1] in (None, got.explanation))
    assert ok, (f"{section}_grounded with drop {list(drop)} gave {shown!r} on claims [{fakea.describe(claims)}]; "
                f"expected {want!r}: {why}")


def renamed(claims: list) -> tuple[list, dict]:
    """The same claims and FAKEA rows under other source ids: another item's expected."""
    exp = fakea.expected()
    expected = {key: {f"{s}_b": v for s, v in table.items()} for key, table in exp.items()}
    return [{**c, "source_ids": [f"{s}_b" for s in c["source_ids"]]} for c in claims], expected


def test_four_registered_code_graders_one_per_section():
    for section in masking.SECTIONS:
        g = built(section)
        assert (g.kind, g.section, g.drop) == ("code", section, ()), (
            f"{section}_grounded has kind {g.kind!r}, section {g.section!r}, drop {g.drop!r}; expected 'code', "
            f"{section!r} and () (nothing dropped)")
    scores("levels", [fakea.fact("l1", "level_hvn_1")], (), (1.0, None),
           "l1 cites a level row and is kept")
    scores("edgar", CLAIMS, (), (1.0, None), "e1 cites an EDGAR row and is kept")
    scores("edgar", CLAIMS[:3], (), "not_cited", "no claim cites an EDGAR row")
    scores("headlines", CLAIMS, (), (1.0, None), "x1 and h1 cite headline rows")
    scores("indicators", CLAIMS[2:], (), "not_cited", "h1 and e1 cite no indicator row")


def test_a_drop_arm_fails_the_claims_citing_rows_it_never_saw():
    scores("headlines", CLAIMS, ("headlines",), (0.0, "dropped_source: 2 of 2 claims citing headlines fail"),
           "an arm that never saw the headlines cannot have read x1's or h1's headline row")
    scores("indicators", CLAIMS, ("headlines",), (0.5, "dropped_source: 1 of 2 claims citing indicators fail"),
           "x1 also cites a headline row this arm never saw, so it fails in every section it cites")
    scores("indicators", CLAIMS, ("edgar",), (1.0, None),
           "dropping EDGAR rows touches no claim citing an indicator row here")
    scores("edgar", CLAIMS, ("edgar",), (0.0, "dropped_source: 1 of 1 claims citing edgar fail"),
           "e1 cites an EDGAR row this arm never saw")
    scores("edgar", CLAIMS, ("headlines", "edgar"), (0.0, "dropped_source: 1 of 1 claims citing edgar fail"),
           "an arm may drop two sections")


def test_the_drop_belongs_to_the_grader_an_arm_builds():
    scores("indicators", CLAIMS, ("headlines",), (0.5, "dropped_source: 1 of 2 claims citing indicators fail"),
           "x1 cites a headline row this arm never saw")
    g = built("indicators", ("headlines",))
    scores("indicators", CLAIMS, (), (1.0, None), "the full arm's grader, built after the no-headlines arm's, "
           "drops nothing")
    scores("indicators", CLAIMS, ("headlines",), (0.5, "dropped_source: 1 of 2 claims citing indicators fail"),
           "the no-headlines arm's grader still hides its headline rows after the full arm built its own", g)
    claims, expected = renamed(CLAIMS)
    scores("indicators", claims, ("headlines",), (0.5, "dropped_source: 1 of 2 claims citing indicators fail"),
           "the next item's rows have other source ids; the rows hidden from this arm are that item's headline rows",
           g, expected)


def test_the_recorded_reply_in_each_arm():
    claims = fakea.recorded()["claims"]
    indicators = (6 / 7, "empty_placeholder: 1 of 7 claims citing indicators fail")
    for drop in [(), ("edgar",)]:
        scores("headlines", claims, drop, (1.0, None), "c9 cites a headline row")
        scores("indicators", claims, drop, indicators, "c10 is rejected (empty_placeholder)")
        scores("edgar", claims, drop, "not_cited", "the reply cites no EDGAR row")
    scores("headlines", claims, ("headlines",), (0.0, "dropped_source: 1 of 1 claims citing headlines fail"),
           "c9 cites a headline row the no-headlines arm never saw")
    scores("indicators", claims, ("headlines",), indicators, "no indicator claim cites a headline row")

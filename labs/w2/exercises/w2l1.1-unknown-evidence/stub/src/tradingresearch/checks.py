"""The P2-P4 process code checks (SPIKE §7.2): pure functions on one stored thesis and its analysis.

Specs: evals/specs/p2_evidence_valid.md, p3_invalidation_testable.md, p4_levels_coherent.md. The graders that run
them on a thesis-run sample are in evals.py.
"""

from __future__ import annotations

from .records import Claim, Thesis

TOLERANCE = 0.005  # relative, as analyze.REL_TOL: a cited number may differ from its source by 0.5%


def entry_price(thesis: Thesis, reference_close: float) -> float:
    """The entry price, or the snapshot's last close for a market_open entry (SPIKE §1.1 Thesis rule 1)."""
    return reference_close if thesis.entry.kind == "market_open" else thesis.entry.price


def close_within(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * max(abs(a), abs(b))


def evidence_ok(claim: Claim | None, values: dict[str, float | None], tolerance: float) -> bool:
    """P2 rules 1-4 for one evidence id; an inference's numbers were checked against its parents at analyze time."""
    # TODO(w2l1.1) rule 1: `claim` is None when the evidence id names no claim of the analysis. Such an id is not
    #   evidence.
    # TODO(w2l1.2) rule 2: an opinion is not evidence, even beside facts.
    # TODO(w2l1.3) rules 3-4 judge facts only: an inference passes here. Rule 3: a fact that cites a source id
    #   missing from `values` (the thesis-stage source table) fails.
    # TODO(w2l1.4) rule 4: a fact with a value must match at least one cited source within `tolerance` (close_within).
    #   A fact without a value passes; a source holding None matches nothing.
    return True


def p2_evidence_valid(thesis: Thesis, claims: tuple[Claim, ...], values: dict[str, float | None],
                      tolerance: float = TOLERANCE) -> bool:
    """True if every evidence id is a fact or inference of the analysis and every fact traces to its source table."""
    # TODO(w2l1.1) find the claim each id in thesis.evidence names (match on claim_id; None when no claim has that id)
    #   and ask evidence_ok about it. The thesis passes only if every evidence id does.
    return True

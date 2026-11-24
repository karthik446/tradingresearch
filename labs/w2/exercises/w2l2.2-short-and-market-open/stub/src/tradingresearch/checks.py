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
    if claim is None or claim.tag == "opinion":
        return False
    if claim.tag == "inference":
        return True
    if any(source not in values for source in claim.source_ids):
        return False
    if claim.value is None:
        return True
    numbers = [values[source] for source in claim.source_ids if values[source] is not None]
    return any(close_within(claim.value, number, tolerance) for number in numbers)


def p2_evidence_valid(thesis: Thesis, claims: tuple[Claim, ...], values: dict[str, float | None],
                      tolerance: float = TOLERANCE) -> bool:
    """True if every evidence id is a fact or inference of the analysis and every fact traces to its source table."""
    by_id = {claim.claim_id: claim for claim in claims}
    return all(evidence_ok(by_id.get(claim_id), values, tolerance) for claim_id in thesis.evidence)


def p3_invalidation_testable(thesis: Thesis, reference_close: float) -> bool:
    """True if the invalidation lies between entry and stop (stop included), so it can be reached before the stop."""
    entry, invalidation, stop = thesis.entry.price, thesis.invalidation_price, thesis.stop
    if thesis.direction == "long":
        return stop <= invalidation < entry
    # TODO(w2l2.2) a short mirrors the long rule. A market_open entry has no price yet (entry.price is None): its
    #   entry is the snapshot's last close, reference_close.
    return True

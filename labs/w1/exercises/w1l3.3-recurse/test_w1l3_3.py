"""w1l3.3 recursion: an inference built on another inference inherits what that one's parents cite."""

from types import SimpleNamespace

from tradingresearch.evals import InferencesGrounded

NAMES = {"s1": "close", "s2": "sma_200", "s3": "dist_sma_200_atr", "s4": "sma_20", "s5": "sma_50", "s6": "high_20"}


def grade(*claims):
    sample = SimpleNamespace(parse_status="ok", output_parsed={"claims": list(claims)})
    try:
        return InferencesGrounded().grade(sample, {"names": NAMES})
    except RecursionError:
        raise AssertionError(
            "RecursionError: c2 derives from c3 and c3 from c2, and the walk up the parents never ended. A claim the "
            "walk has already passed through adds nothing new: stop there."
        ) from None


def fact(cid, *sources):
    return {"id": cid, "tag": "fact", "text": "x", "source_ids": list(sources), "derived_from": [], "steps": None}


def inference(cid, text, *parents, steps="s"):
    return {"id": cid, "tag": "inference", "text": text, "source_ids": [], "derived_from": list(parents), "steps": steps}


def test_grounding_passes_through_an_inference_parent():
    score = grade(fact("c1", "s6"), inference("c2", "Price is near high_20.", "c1"),
                  inference("c3", "No breakout yet.", "c2", steps="high_20 holds and ema_9 is flat."))
    assert score.value == 1.0, (
        f"c3 scored 0 ({score.explanation}): its parent c2 is an inference that cites nothing itself, but c2's parent "
        "c1 cites high_20. cited(c2) must include what c2's own parents cite. (ema_9 is not in this table, so it is "
        "not judged.)"
    )


def test_grounding_passes_through_any_number_of_inferences():
    score = grade(fact("c1", "s6"), inference("c2", "Price is close to its recent high.", "c1"),
                  inference("c3", "Momentum holds.", "c2"), inference("c4", "Near high_20.", "c3"))
    assert score.value == 1.0, (
        f"a chain of four scored 0 ({score.explanation}): c4 names high_20, its parent c3 and grandparent c2 cite "
        "nothing, and only c1, three steps up, cites high_20. Looking one or two levels up is not enough: cited(c) "
        "must reach every ancestor, however long the chain."
    )


def test_a_cycle_stops():
    score = grade(fact("c1", "s1"), inference("c2", "Above sma_20.", "c1", "c3"), inference("c3", "So up.", "c2"))
    assert score.explanation == "c2: sma_20", f"explanation is {score.explanation!r}; expected 'c2: sma_20'"


def test_a_chain_of_eight_still_reaches_the_fact():
    chain = [inference(f"c{i}", "The move goes on.", f"c{i - 1}") for i in range(2, 8)]
    score = grade(fact("c1", "s6"), *chain, inference("c8", "Near high_20.", "c7"))
    assert score.value == 1.0, (
        f"a chain of eight scored 0 ({score.explanation}): c8 names high_20, c2 to c7 are inferences that cite "
        "nothing, and c1, seven steps up, cites high_20. The walk stops only at a claim it has already passed "
        "through, never after a fixed number of steps."
    )


def test_every_parent_of_an_inference_parent_counts():
    score = grade(fact("c1", "s1"), fact("c2", "s6"), inference("c3", "Price nears its high.", "c1", "c2"),
                  inference("c4", "Near high_20.", "c3"))
    assert score.value == 1.0, (
        f"c4 scored 0 ({score.explanation}): c4 names high_20 and stands on c3, whose parents are c1 (close) and "
        "c2 (high_20). cited(c3) is the union over all of c3's parents, not its first one."
    )

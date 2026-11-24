"""w1l3.2 the rule on direct parents: an inference may name only indicators its parents cite.

Claim texts are the author's, from the recorded observe run (run_c40caab0968e44a3); source ids are short aliases.
"""

from types import SimpleNamespace

from tradingresearch.evals import InferencesGrounded

NAMES = {"s1": "close", "s2": "sma_200", "s3": "dist_sma_200_atr", "s4": "sma_20", "s5": "sma_50", "s6": "high_20"}


def grade(*claims):
    sample = SimpleNamespace(parse_status="ok", output_parsed={"claims": list(claims)})
    return InferencesGrounded().grade(sample, {"names": NAMES})


def fact(cid, *sources):
    return {"id": cid, "tag": "fact", "text": "x", "source_ids": list(sources), "derived_from": [], "steps": None}


def inference(cid, text, *parents, steps="s"):
    return {"id": cid, "tag": "inference", "text": text, "source_ids": [], "derived_from": list(parents), "steps": steps}


def test_amzn_2026_11_13_c4_names_two_averages_it_never_cited():
    score = grade(fact("c1", "s1"), fact("c2", "s2"), fact("c3", "s3"),
                  inference("c4", "Price is above sma_20, sma_50 and sma_200, so the trend is up on all three horizons.",
                            "c1", "c2", "c3"))
    assert score.value == 0.0, (
        "AMZN 2026-11-13 c4 scored 1: it names sma_20 and sma_50, but its parents c1, c2, c3 cite only close, sma_200 "
        "and dist_sma_200_atr. This is the claim in the inference_wider row of your taxonomy."
    )
    flagged = set((score.explanation or "").removeprefix("c4: ").split(", ")) - {""}
    by_parent = {"close": "c1", "sma_200": "c2", "dist_sma_200_atr": "c3"}
    wrong = "".join(f"{name} is cited by parent {by_parent[name]}, yet you flagged it; " for name in sorted(flagged)
                    if name in by_parent)
    assert score.explanation == "c4: sma_20, sma_50", (
        f"explanation is {score.explanation!r}. {wrong}allowed is the union of what every parent cites. "
        "Write the claim id and the ungrounded names, sorted: 'c4: sma_20, sma_50'"
    )


def test_a_fact_that_is_not_a_parent_grounds_nothing():
    score = grade(fact("c1", "s1"), fact("c2", "s4"), inference("c3", "The close is above sma_20.", "c1"))
    assert score.explanation == "c3: sma_20", (
        f"c3 scored {score.value:g} ({score.explanation}): c3 names sma_20, which fact c2 cites, but c3's "
        "derived_from is [c1] and c1 cites only close. Allowed is what c3's own parents cite, not everything "
        "cited anywhere in the reply."
    )


def test_msft_2026_11_13_c6_cites_every_average_it_names():
    score = grade(fact("c1", "s1"), fact("c2", "s2"), fact("c4", "s4"), fact("c5", "s5"),
                  inference("c6", "The close sits between sma_50 and sma_20 while far above sma_200.",
                            "c1", "c2", "c4", "c5"))
    assert score.value == 1.0 and score.explanation is None, (
        f"MSFT 2026-11-13 c6 cites every average it names, yet scored {score.value:g} ({score.explanation}). Allowed is "
        "the union of what each parent cites, not what one parent cites."
    )


def test_two_ungrounded_inferences_are_both_reported():
    score = grade(fact("c1", "s1"), inference("c2", "Above sma_20.", "c1"), inference("c3", "Below high_20.", "c1"))
    assert score.explanation == "c2: sma_20; c3: high_20", (
        f"explanation is {score.explanation!r}: report every ungrounded inference, joined by '; '"
    )


def test_facts_and_opinions_are_not_judged():
    opinion = {"id": "c2", "tag": "opinion", "text": "sma_50 matters most.", "source_ids": [], "derived_from": []}
    score = grade(fact("c1", "s4"), opinion)
    assert score.value == 1.0, "only inferences are judged: a fact cites its own sources, an opinion cites nothing"


def test_names_in_steps_count_too():
    score = grade(fact("c1", "s1"), inference("c2", "Near the high.", "c1", steps="high_20 is just above the close."))
    assert score.explanation == "c2: high_20", (
        f"c2 scored {score.value:g} ({score.explanation}): its text names no indicator, but its steps name high_20 and "
        "its only parent c1 cites close. The steps are part of the inference, so a name there needs grounding too."
    )


def test_an_inference_with_no_parents_grounds_nothing():
    score = grade(fact("c1", "s4"), inference("c2", "Price is above sma_20."))
    assert score.explanation == "c2: sma_20", (
        f"c2 'Price is above sma_20.' has derived_from [] and scored {score.value:g} ({score.explanation}). With no "
        "parents nothing is allowed, so every name it uses is ungrounded: 'c2: sma_20'. (Fact c1 cites sma_20, but "
        "c1 is not c2's parent.)"
    )


def test_every_ungrounded_name_is_listed():
    score = grade(fact("c1", "s1"), inference("c2", "Above sma_20 and sma_50, below high_20.", "c1"))
    assert score.explanation == "c2: high_20, sma_20, sma_50", (
        f"c2 names sma_20, sma_50 and high_20, its parent c1 cites only close; explanation is {score.explanation!r}. "
        "List all three, sorted: 'c2: high_20, sma_20, sma_50'"
    )

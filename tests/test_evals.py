"""inferences_grounded, on claims copied from the week 1 observe run (run_c40caab0968e44a3)."""

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
    assert score.value == 0.0 and score.explanation == "c4: sma_20, sma_50"


def test_msft_2026_11_13_c6_cites_every_average_it_names():
    score = grade(fact("c1", "s1"), fact("c2", "s2"), fact("c4", "s4"), fact("c5", "s5"),
                  inference("c6", "The close sits between sma_50 and sma_20 while far above sma_200.",
                            "c1", "c2", "c4", "c5"))
    assert score.value == 1.0 and score.explanation is None


def test_steps_count_and_grounding_passes_through_an_inference_parent():
    score = grade(fact("c1", "s6"), inference("c2", "Price is near high_20.", "c1"),
                  inference("c3", "No breakout yet.", "c2", steps="high_20 holds and ema_9 is flat."))
    assert score.value == 1.0  # high_20 comes through c2; ema_9 is not a table name here, so it is not judged


def test_a_dist_atr_parent_grounds_the_level_and_plain_words_never_match():
    score = grade(fact("c3", "s3"), inference("c4", "The close is far above sma_200.", "c3"))
    assert score.value == 1.0

"""w1l3.5 dist alias: a parent that cites dist_sma_200_atr (distance to sma_200, in ATRs) also grounds sma_200."""

from types import SimpleNamespace

from tradingresearch.evals import InferencesGrounded

NAMES = {"s1": "close", "s2": "sma_200", "s3": "dist_sma_200_atr", "s4": "sma_20", "s5": "sma_50", "s6": "high_20"}


def grade(*claims, names=NAMES):
    sample = SimpleNamespace(parse_status="ok", output_parsed={"claims": list(claims)})
    return InferencesGrounded().grade(sample, {"names": names})


def fact(cid, *sources):
    return {"id": cid, "tag": "fact", "text": "x", "source_ids": list(sources), "derived_from": [], "steps": None}


def inference(cid, text, *parents, steps="s"):
    return {"id": cid, "tag": "inference", "text": text, "source_ids": [], "derived_from": list(parents), "steps": steps}


def test_a_dist_atr_parent_grounds_the_level():
    score = grade(fact("c3", "s3"), inference("c4", "The close is far above sma_200.", "c3"))
    assert score.value == 1.0, (
        f"scored 0 ({score.explanation}): c3 cites dist_sma_200_atr, the distance from sma_200 in ATRs, so naming "
        "sma_200 is grounded. For a cited dist_<name>_atr also allow <name> (spec, evals/specs/inferences_grounded.md)."
    )


def test_plain_words_never_match():
    score = grade(fact("c1", "s2"), inference("c2", "The close is above sma_200.", "c1"))
    assert score.value == 1.0, "'close' has no underscore, so it is not in the vocabulary and is never judged"


def test_every_dist_atr_name_is_an_alias_not_only_averages():
    score = grade(fact("c1", "s1"), inference("c2", "Near high_20.", "c1"),
                  names={"s1": "dist_high_20_atr", "s2": "high_20"})
    assert score.value == 1.0, (
        f"scored 0 ({score.explanation}): c1 cites dist_high_20_atr, the distance from high_20 in ATRs, so naming "
        "high_20 is grounded. The alias holds for any dist_<name>_atr in the table, not one family of names."
    )


def test_only_the_exact_dist_atr_shape_is_an_alias():
    cases = [({"s1": "dist_sma_50_pct", "s2": "sma_50"}, "sma_50", "it does not end in _atr"),
             ({"s1": "sma_50_atr", "s2": "sma_50"}, "sma_50", "it does not start with dist_"),
             ({"s1": "dist_sma_200_atr", "s2": "sma_20"}, "sma_20", "its <name> is sma_200, not sma_20")]
    for names, named, why in cases:
        score = grade(fact("c1", "s1"), inference("c2", f"Above {named}.", "c1"), names=names)
        assert score.explanation == f"c2: {named}", (
            f"c2 'Above {named}.' derives from a fact citing only {names['s1']}, yet scored {score.value:g} "
            f"({score.explanation}). {names['s1']} grounds nothing extra: {why}."
        )

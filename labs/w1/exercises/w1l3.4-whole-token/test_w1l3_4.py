"""w1l3.4 whole tokens: a name matches only as a whole token, never inside a longer name."""

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


def test_sma_20_is_not_inside_sma_200():
    score = grade(fact("c1", "s1"), fact("c2", "s2"), inference("c3", "The close is far above sma_200.", "c1", "c2"))
    assert score.value == 1.0, (
        f"scored 0 ({score.explanation}): 'sma_20' matched inside 'sma_200'. A substring test is not a token test; "
        "match the name only where no letter, digit or _ touches it on either side."
    )


def test_a_name_next_to_punctuation_still_counts():
    score = grade(fact("c1", "s1"), inference("c2", "Close (above sma_50) holds.", "c1"))
    assert score.explanation == "c2: sma_50", (
        f"explanation is {score.explanation!r}: '(sma_50)' must still match; only letters, digits and _ end a token"
    )


def test_a_name_at_the_end_of_a_longer_token_is_not_that_name():
    score = grade(fact("c1", "s1"), inference("c2", "Above dist_sma_20 and xsma_20.", "c1"),
                  names={"s1": "close", "s2": "sma_20"})
    assert score.value == 1.0, (
        f"c2 'Above dist_sma_20 and xsma_20.' scored 0 ({score.explanation}) with sma_20 in the table: both words end in "
        "sma_20 but are other tokens. The left side of a name is a boundary too, not only the right."
    )


def test_case_is_part_of_the_name():
    score = grade(fact("c1", "s1"), inference("c2", "Above SMA_20 and Sma_50.", "c1"))
    assert score.value == 1.0, (
        f"c2 'Above SMA_20 and Sma_50.' scored 0 ({score.explanation}): neither word is a name of the table. "
        "Names match as written, case included (the table has names such as revenue_CY2025Q2)."
    )


def test_a_capital_letter_next_to_a_name_makes_another_token():
    score = grade(fact("c1", "s1"), inference("c2", "Above Xsma_20 and sma_20Y.", "c1"),
                  names={"s1": "close", "s2": "sma_20"})
    assert score.value == 1.0, (
        f"c2 'Above Xsma_20 and sma_20Y.' scored 0 ({score.explanation}): a capital letter is a letter too, so "
        "both words are other tokens, on the left as on the right."
    )


def test_a_name_is_matched_literally():
    score = grade(fact("c1", "s1"), inference("c2", "Above rsi_14(close) now.", "c1"),
                  names={"s1": "close", "s2": "rsi_14(close)"})
    assert score.explanation == "c2: rsi_14(close)", (
        f"with rsi_14(close) in the table, c2 'Above rsi_14(close) now.' from a parent citing only close gave "
        f"{score.explanation!r}; expected 'c2: rsi_14(close)'. A table name is text to find as it is: characters "
        "such as ( ) . + mean nothing special in it."
    )

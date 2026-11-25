"""w3l1.1 the last JSON object: p1_verdict reads the verdict and the explanation of the LAST object in the reply.

Replies are labs/w3/data/replies.json: `recorded` is the one recorded openai/gpt-6-sol reply on the FAKEA trade; the
others are reply shapes from tests/test_week3.py, gigai-core's judge tests or built for these labs (`source` says
which). `expect` is the rubric's reading of each.
"""

import json
import os
from pathlib import Path

from tradingresearch.evals import p1_verdict

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def row(rid: str) -> dict:
    return next(r for r in json.loads((DATA / "replies.json").read_text())["replies"] if r["id"] == rid)


def read(reply: str) -> object:
    try:
        return p1_verdict(reply)
    except Exception as exc:  # show a crash as a result, so the message can say which reply caused it
        return f"{type(exc).__name__}: {exc}"


def test_the_recorded_reply_reads_pass_with_its_explanation():
    r = row("recorded")
    got, last = read(r["reply"]), r["reply"].strip().splitlines()[-1]
    assert got == tuple(r["expect"]), (
        f"The one recorded judge reply (run_54953ec7ce484649) thinks aloud, then ends with {last[:90]!r}...; "
        f"p1_verdict returned {got!r}. The verdict is that object's \"verdict\", the reason its \"explanation\"."
    )


def test_the_last_object_wins_over_one_quoted_earlier():
    for rid, earlier in (("last_json_wins", "quotes the rubric's format example"),
                         ("nested_object", "shows a draft verdict, and the answer nests an object of its own")):
        r = row(rid)
        got = read(r["reply"])
        assert got == tuple(r["expect"]), (
            f"{rid}: the reply {earlier}: {r['reply'][:110]!r}...; p1_verdict returned {got!r}, the answer is "
            f"{tuple(r['expect'])!r}. The rubric's Verdict format: the answer is the last JSON object in the reply; "
            f"an object nested inside it is part of it, not a later one."
        )


def test_the_answer_reads_wherever_it_sits_and_whatever_it_quotes():
    for rid, shape in (("fenced_block", "pretty-prints the object in a ```json fence, so it is not the last line"),
                       ("quoted_words", "quotes words inside the explanation, escaped as \\\" in JSON"),
                       ("pass", "puts the object on its own last line")):
        r = row(rid)
        got = read(r["reply"])
        assert got == tuple(r["expect"]), (
            f"{rid}: the reply {shape}: {r['reply'][-120:]!r}; p1_verdict returned {got!r}, the answer is "
            f"{tuple(r['expect'])!r}. Parse the JSON; a line split or a regex over the text breaks on such replies."
        )


def test_a_missing_null_or_non_text_explanation_reads_empty():
    for rid in ("no_explanation", "null_explanation", "list_explanation"):
        r = row(rid)
        got = read(r["reply"])
        assert got == tuple(r["expect"]), (
            f"{rid}: {r['reply']!r} has a verdict and no usable explanation; p1_verdict returned {got!r}, expected "
            f"{tuple(r['expect'])!r}. The reason is stored as text in judge_verdict.reason (NOT NULL): an explanation "
            f"that is missing, null or not a string is \"\", not None, not the string 'None' and not a list."
        )

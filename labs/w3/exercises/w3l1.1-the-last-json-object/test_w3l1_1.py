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


def test_replies_in_no_data_row_read_by_the_same_rule():
    # Built here, so they are in no row of replies.json: the rule reads them, a lookup of the 26 rows does not.
    for reply, why, want in (
        ('Draft: {"verdict": "fail", "explanation": "first look"}\n'
         '{"verdict": "pass", "explanation": "FAKEA closed 101.3 and 106.2, both over {100.5}"}',
         "drafts a fail, then answers pass with braces and capitals in its explanation",
         ("pass", "FAKEA closed 101.3 and 106.2, both over {100.5}")),
        ('{"verdict": "pass", "explanation": "Closes held over 98", "first_try": {"verdict": "fail"}}',
         'answers pass and nests an earlier "verdict" key inside its answer',
         ("pass", "Closes held over 98")),
        (json.dumps({"verdict": "pass", "explanation": f"  {'both closes held over 98, ' * 9}so the break held\n"}),
         "explains at length, with two spaces before and a newline after",
         ("pass", f"  {'both closes held over 98, ' * 9}so the break held\n")),
    ):
        got = read(reply)
        assert got == want, (
            f"p1_verdict returned {got!r}, the answer is {want!r}, for a reply that {why}: {reply!r}. These replies are "
            f"in no row of replies.json: the rule (the last top-level JSON object; an object nested in it is part of "
            f"it) reads any reply, a lookup of the data rows reads only those, and the explanation is kept as written."
        )


def test_the_explanation_is_the_decoded_text_untouched():
    # JSON decoding is the one transformation: "\u00e9" is é, "&amp;" stays "&amp;", "\u0000" is a NUL character,
    # "e\u0301" stays two code points, an emoji stays, "\r\n" stays, and a long explanation stays whole.
    for explanation, how in (("the break held at the café level", "with an accented letter"),
                             ("A &amp; B held: both closes over 100.5", "with an HTML entity, which JSON leaves literal"),
                             ("① the level held, ② volume rose", "with circled digits"),
                             ("held\x00(cut here by the judge)", "with an escaped NUL character"),
                             ("the break held at the cafe\u0301 level", "with a decomposed accent (e + U+0301)"),
                             ("📈 held: both closes over 100.5", "with an emoji outside the Basic Multilingual Plane"),
                             ("held over 100.5\r\nvolume rose", "with a CRLF line break"),
                             ("both closes held over 98, " * 25 + "so the break held", "of over 600 characters")):
        reply = json.dumps({"verdict": "pass", "explanation": explanation})
        got = read(reply)
        assert got == ("pass", explanation), (
            f"p1_verdict returned {got!r} for an explanation {how}: the judge sent {reply!r}, so the reason is "
            f"{explanation!r}. Decoding the JSON is the only change between the reply and the stored reason: no "
            f"ASCII filter, no HTML unescape, no Unicode normalisation, no characters dropped, no cut, no line-break "
            f"change. judge_verdict.reason is what the judge wrote, for whoever reads it next to the trade."
        )

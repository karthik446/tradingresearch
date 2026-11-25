"""w3l1.3 no verdict cannot be graded: a reply without a pass, fail or unknown verdict raises CannotGrade.

An abstain is the judge saying it cannot decide (`unknown`, w3l1.2); a reply nobody can read is not an answer at all.
CannotGrade (gigai-core) means nothing is stored and the trade stays unjudged; the call's cost is still in its run
file. Replies are labs/w3/data/replies.json.
"""

import json
import os
from pathlib import Path

from gigai_core.graders.protocol import CannotGrade

from tradingresearch.evals import p1_verdict

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def rows() -> list[dict]:
    return json.loads((DATA / "replies.json").read_text())["replies"]


def row(rid: str) -> dict:
    return next(r for r in rows() if r["id"] == rid)


def read(reply: str) -> object:
    try:
        got = p1_verdict(reply)
    except Exception as exc:  # shown as a result: CannotGrade is the right one here, anything else is a bug
        return exc
    # A returned exception is a value: no caller sees it as an error, so it is shown as text, not as the exception.
    return f"{type(got).__name__}({got}) returned, not raised" if isinstance(got, Exception) else got


def shown(got: object) -> str:
    return f"{type(got).__name__}({got})" if isinstance(got, Exception) else repr(got)


def test_a_reply_with_no_verdict_cannot_be_graded():
    for rid in ("no_json", "no_verdict", "cut_off"):
        r = row(rid)
        got = read(r["reply"])
        assert isinstance(got, CannotGrade), (
            f"{rid}: {r['reply']!r} holds no verdict; p1_verdict returned {shown(got)}. That is not a fail and not an "
            f"abstain: storing it would count a reply nobody can read as the judge's answer. Raise CannotGrade."
        )


def test_only_the_three_lower_case_verdicts_count():
    for rid in ("maybe", "capitalised", "null_verdict", "padded_verdict", "hedged", "list_verdict"):
        r = row(rid)
        got = read(r["reply"])
        assert isinstance(got, CannotGrade), (
            f"{rid}: {r['reply'].splitlines()[-1]!r}; p1_verdict returned {shown(got)}. The rubric asks for exactly "
            f"the string pass or fail (or unknown), in lower case, nothing around it; anything else is a reply the "
            f"rubric does not define, so CannotGrade, not a guess at what the judge meant."
        )
    # Words that sound like an abstain: the rubric's one word for an abstain is unknown (w3l1.2).
    for word in ("abstain", "inconclusive", "neutral"):
        reply = f'{{"verdict": "{word}", "explanation": "the closes neither held nor broke"}}'
        got = read(reply)
        assert isinstance(got, CannotGrade), (
            f"p1_verdict returned {shown(got)} for {reply!r}, expected CannotGrade. {word} sounds like an abstain, but "
            f"the rubric's word for an abstain is unknown (w3l1.2): {word} is a verdict the rubric does not define. "
            f"Returned as a verdict, it reaches the journal, which refuses it only when it is stored, after the call "
            f"was paid. Refuse it here, before anything is stored."
        )


def test_the_answer_is_the_last_object_or_nothing():
    r = row("answer_then_notes")
    got = read(r["reply"])
    assert isinstance(got, CannotGrade), (
        f"answer_then_notes: {r['reply']!r}; p1_verdict returned {shown(got)}. The last JSON object wins, and it has "
        f"no verdict: falling back to an earlier object would pick one the judge did not end on."
    )


def test_the_refusal_quotes_the_reply():
    r = row("no_json")
    got = read(r["reply"])
    assert isinstance(got, CannotGrade) and r["reply"] in str(got), (
        f"p1_verdict on {r['reply']!r} returned {shown(got)}. The CannotGrade message must quote the reply, so whoever "
        f"reads `tr grade --judge`'s refusal sees what the judge sent."
    )


def test_readable_replies_still_read():
    for r in rows():
        if r["expect"] == "CannotGrade":
            continue
        got = read(r["reply"])
        why = ("Only a reply with no pass, fail or unknown verdict is CannotGrade; unknown is still an abstain."
               if isinstance(got, Exception) else
               f"This row is {r['exercise']}'s rule, and its reading changed: run that exercise's check again.")
        assert got == tuple(r["expect"]), (
            f"{r['id']} ({r['exercise']}): {r['reply'].strip().splitlines()[-1][:90]!r}; p1_verdict returned "
            f"{shown(got)}, expected {tuple(r['expect'])!r}. {why}"
        )


def test_replies_in_no_data_row_follow_the_same_rule():
    # Built here, so they are in no row of replies.json: exactly pass, fail or unknown, or CannotGrade.
    for reply in ('{"verdict": "PASS", "explanation": "closes held over 98"}', 'Verdict: pass. Closes held.',
                  '{"verdict": "pass.", "explanation": "closes held over 98"}',
                  '{"verdict": true, "explanation": "closes held over 98"}',
                  '{"verdict": false, "explanation": "a close fell under 98"}',
                  '{"verdict": {"value": "pass"}, "explanation": "closes held over 98"}'):
        got = read(reply)
        assert isinstance(got, CannotGrade), (
            f"p1_verdict returned {shown(got)} for {reply!r}, expected CannotGrade. That reply is in no row of "
            f"replies.json and holds no verdict the rubric defines. The rule decides, not a list of known replies: a "
            f"last JSON object whose verdict is not the string pass, fail or unknown (JSON true or false and an object "
            f"holding a verdict are not), or no JSON at all, is CannotGrade."
        )
    reply = '{"verdict": "fail", "explanation": "a close at 97.9 fell under 98"}'
    got = read(reply)
    assert got == ("fail", "a close at 97.9 fell under 98"), (
        f"{reply!r} is in no row of replies.json; p1_verdict returned {shown(got)}. A plain fail reads as itself."
    )

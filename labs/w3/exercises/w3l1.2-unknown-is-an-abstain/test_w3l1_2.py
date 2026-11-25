"""w3l1.2 unknown is an abstain: a verdict of `unknown` becomes `fail` with `unknown: ` before its explanation.

ADR-003 and the rubric's Verdict format: the verdict is binary (gigai-core JudgeVerdict; journal.py's judge_verdict
table accepts only pass and fail); an unknown is a `fail` whose reason starts with `unknown:`, which
`journal.abstained` counts and kappa leaves out. Replies are labs/w3/data/replies.json.
"""

import json
import os
from pathlib import Path

from tradingresearch import journal
from tradingresearch.evals import p1_verdict

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def row(rid: str) -> dict:
    return next(r for r in json.loads((DATA / "replies.json").read_text())["replies"] if r["id"] == rid)


def read(reply: str) -> object:
    try:
        return p1_verdict(reply)
    except Exception as exc:  # show a crash as a result, so the message can say which reply caused it
        return f"{type(exc).__name__}: {exc}"


def test_unknown_becomes_fail_with_the_unknown_prefix():
    r = row("unknown_becomes_fail")
    got = read(r["reply"])
    assert got == tuple(r["expect"]), (
        f"The judge answered {r['reply'].splitlines()[-1]!r}; p1_verdict returned {got!r}, expected "
        f"{tuple(r['expect'])!r}. judge_verdict.verdict accepts only 'pass' or 'fail' (journal.py), so an unknown is "
        f"stored as fail with 'unknown: ' before the explanation: an abstain kappa leaves out, not a not-met."
    )


def test_the_prefix_is_never_doubled():
    for rid in ("unknown_prefixed", "unknown_tight_prefix", "fail_unknown_kept"):
        r = row(rid)
        got = read(r["reply"])
        assert got == tuple(r["expect"]), (
            f"{rid}: the judge answered {r['reply'].splitlines()[-1]!r}; p1_verdict returned {got!r}, expected "
            f"{tuple(r['expect'])!r}. An explanation that already starts with 'unknown:' keeps one prefix, and a fail "
            f"the judge wrote that way is already an abstain."
        )


def test_an_unknown_without_explanation_is_still_an_abstain():
    r = row("unknown_bare")
    got = read(r["reply"])
    assert isinstance(got, tuple) and got[0] == "fail" and got[1].startswith("unknown:"), (
        f"The judge answered {r['reply']!r}; p1_verdict returned {got!r}. With no explanation it is still an abstain: "
        f"fail, and a reason that starts with 'unknown:' (journal.abstained reads exactly that prefix)."
    )


def test_every_abstain_is_one_journal_abstained_counts():
    for rid in ("unknown_becomes_fail", "unknown_prefixed", "unknown_tight_prefix", "unknown_capital_prefix",
                "unknown_bare", "fail_unknown_kept"):
        got = read(row(rid)["reply"])
        stored = {"verdict": got[0], "reason": got[1]} if isinstance(got, tuple) else None
        assert stored is not None and journal.abstained(stored), (
            f"{rid}: p1_verdict returned {got!r}; journal.abstained, which `tr label agree` uses to leave unknowns "
            f"out of kappa, does not count it as an abstain (it wants verdict 'fail', reason starting 'unknown:' in "
            f"lower case)."
        )


def test_pass_and_fail_keep_their_explanations():
    for rid in ("recorded", "last_json_wins", "no_explanation", "pass_mentions_unknown"):
        r = row(rid)
        got = read(r["reply"])
        assert got == tuple(r["expect"]), (
            f"{rid}: the judge answered {r['reply'].strip().splitlines()[-1][:90]!r}; p1_verdict returned {got!r}, "
            f"expected {tuple(r['expect'])!r}. Only an unknown verdict gets the prefix: a plain fail is a not-met, and "
            f"the verdict decides, not the word unknown somewhere in the text."
        )

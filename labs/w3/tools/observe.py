"""Observe for the week-3 labs: what your code does with judge replies, what it sends and what it keeps ($0, no network).

    python labs/w3/tools/observe.py verdicts   # w3l1: p1_verdict on every reply in labs/w3/data/replies.json
    python labs/w3/tools/observe.py judge      # w3l2: p1_judge on the closed FAKEA trade, replayed
    python labs/w3/tools/observe.py store      # w3l3: what p1_judge ends with and keeps, reply by reply
    python labs/w3/tools/observe.py grade      # w3l4: the judge queue, two judge runs, and `tr grade` four times

`verdicts` prints one row per reply: your (verdict, reason) or the exception, the rubric's reading, and whether they
match. Only `recorded` is model output; the other replies are shapes from tests/test_week3.py, gigai-core's judge
tests or built for these labs (`source` in the JSON says which).

`judge` runs p1_judge through the real OpenRouter adapter whose transport answers with the one recorded reply, then
compares what was sent with the recorded request, and runs it again under a $0.001 cap. The reply
cannot react to what you send: it is evidence for your prompt only when the body equals the recorded one.

`store` runs p1_judge once per case on a fresh journal: the recorded reply, the same reply ending in unknown, with no
verdict line, an HTTP 400, a teacher and a never-entered thesis, then the recorded reply with the journal's verdict
write or score write failing. Each row: requests sent, run files and what they say was spent, the judge_verdict row,
the p1_judge scores, and what p1_judge returned or raised.

`grade` runs grade.to_judge on a journal of six theses, grade.judge twice on four waiting theses (a $0.25 cap with
four kinds of reply, a $0.05 cap with the recorded one), then `tr grade` plain, `--judge --dry-run` and `--judge`
twice on two waiting theses.

In `store` and `grade` the replies are the recording or edits of it (tools/fakea.py `answer`), so verdicts and what a
paid call costs cannot move; what your code returns, keeps and prints can.

TR_LAB_DATA overrides labs/w3/data. Exits 0 in every mode: it shows what your code does, the exercise's check decides.
The offline guard (tools/offline.py) is installed before your code is imported; a guarded call it tried is named in a
`note:` line at the end.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline  # noqa: E402

offline.install()  # before fakea and your evals.py are imported
import fakea  # noqa: E402

SECTIONS = ("Question", "Inputs", "Met", "Not met", "Unknown", "Hindsight", "Verdict format")
RAW_BAR_VALUES = ("100.2", "101.6", "106.5", "107.5", "107.2")  # tests/test_week3.py: opens, highs, a post-exit close


def evals() -> object | str:
    try:
        return importlib.import_module("tradingresearch.evals")
    except Exception as exc:  # a learner's half-written file: show it, keep going
        return f"{type(exc).__name__}: {exc}"


def cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def reading(module: object, reply: str) -> object:
    try:
        return tuple(module.p1_verdict(reply))
    except Exception as exc:
        return "CannotGrade" if type(exc).__name__ == "CannotGrade" else f"{type(exc).__name__}: {exc}"


def verdicts() -> None:
    module = evals()
    if isinstance(module, str):
        print(f"tradingresearch.evals did not import: {module}")
        return
    rows = json.loads((fakea.DATA / "replies.json").read_text())["replies"]
    width = max(len(r["id"]) for r in rows)
    print(f"  {'reply':<{width}}  ex      ok  yours -> the rubric's reading")
    matched: dict[str, list[int]] = {}
    for r in rows:
        got = reading(module, r["reply"])
        want = r["expect"] if r["expect"] == "CannotGrade" else tuple(r["expect"])
        ok = got == want
        tally = matched.setdefault(r["exercise"], [0, 0])
        tally[0] += ok
        tally[1] += 1
        line = f"  {r['id']:<{width}}  {r['exercise']}  {'1' if ok else '0'}   {cut(repr(got) if isinstance(got, tuple) else got, 70)}"
        print(line if ok else f"{line}\n  {'':<{width}}               the rubric: {cut(repr(want), 70)}")
    print("matches: " + ", ".join(f"{ex} {n}/{total}" for ex, (n, total) in matched.items()))
    print("recorded is the one model reply; the rest are shapes (see `source` in labs/w3/data/replies.json).")


def judge() -> None:
    module = evals()
    if isinstance(module, str):
        print(f"tradingresearch.evals did not import: {module}")
        return
    recorded = fakea.load("judge_request")["body"]
    rprompt = fakea.recorded_prompt()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        got, sent, _ = fakea.judge(data_dir)
        print(f"p1_judge ended with: {cut(fakea.shown(got), 150)}")
        if not sent:
            print("requests sent: 0 (nothing to compare)")
        else:
            body, prompt = sent[0], fakea.prompt_of(sent[0])
            print(f"requests sent: {len(sent)} (recorded: 1)")
            print(f"model: {body.get('model')} (recorded: {recorded['model']})")
            print(f"max_tokens: {body.get('max_tokens')} (recorded: {recorded['max_tokens']})")
            print(f"prompt chars: {len(prompt)} (recorded: {len(rprompt)})")
            print(f"rubric sections: {sum(f'## {s}' in prompt for s in SECTIONS)}/{len(SECTIONS)}; "
                  f"{{rubric}} placeholder left: {'{rubric}' in prompt}")
            for name in ("INPUT", "OUTPUT"):
                mine, theirs = fakea.block(prompt, name), fakea.block(rprompt, name)
                print(f"{name}: {len(mine)} lines (recorded: {len(theirs)}), same: {mine == theirs}")
            print(f"raw bar values in the prompt: {sum(v in prompt for v in RAW_BAR_VALUES)}/{len(RAW_BAR_VALUES)}")
            same = body == recorded
            print(f"same body as the recording: {same}")
            if not same and prompt == rprompt:
                keys = sorted(k for k in body.keys() | recorded.keys() if body.get(k) != recorded.get(k))
                print(f"  the prompt is the recorded one; the body differs in: {', '.join(keys)}")
            elif not same:
                a, b = prompt.splitlines(), rprompt.splitlines()
                first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                mine, theirs = (cut(x[first] if first < len(x) else "(end)", 70) for x in (a, b))
                print(f"  first differing prompt line {first + 1}: yours {mine!r}")
                print(f"  {'':<26}recorded {theirs!r}")
    with tempfile.TemporaryDirectory() as tmp:
        got, sent, _ = fakea.judge(Path(tmp), max_usd=0.001)
        print(f"under max_usd=0.001: {len(sent)} request(s) sent, ended with {cut(fakea.shown(got), 110)}")
    reply = fakea.load("judge_reply")["choices"][0]["message"]["content"]
    print(f"p1_verdict on the recorded reply: {cut(str(reading(module, reply)), 120)}")
    print("The reply is the recording: it says pass whatever you send. It is evidence for your prompt only when the "
          "body is the recorded one.")


STORE_CASES = (  # (row label, fakea.judging arguments)
    ("recorded", {}),
    ("unknown", {"replies": ("unknown",)}),
    ("no_verdict", {"replies": ("no_verdict",)}),
    ("http_400", {"replies": ("failed",)}),
    ("teacher", {"arm": "teacher"}),
    ("never_entered", {"arm": "never_entered"}),
    ("verdict write fails", {"broken": "add_judge_verdict"}),
    ("score write fails", {"broken": "_insert_score"}),
)


def ended(got: object, raised: bool) -> str:
    """What p1_judge did: a returned exception is shown as returned, so it cannot pass for a raised one."""
    if type(got).__name__ == "Score":
        return f"returned Score {got.value} ({got.answer})"
    return f"{'raised' if raised else 'returned'} {fakea.shown(got)}"


def store() -> None:
    module = evals()
    if isinstance(module, str):
        print(f"tradingresearch.evals did not import: {module}")
        return
    print(f"  {'case':<20} {'sent':<5} {'run files':<14} {'verdict row':<16} p1 scores")
    for label, kwargs in STORE_CASES:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                j = fakea.judging(Path(tmp), **kwargs)
                files = fakea.run_files(j.data_dir)
                runs = f"{len(files)} ${sum(fakea.spent(f) for f in files):.6f}" if files else "0"
                row, scores = fakea.stored(j.conn, j.thesis.thesis_id)
                j.conn.close()
            except Exception as exc:  # the journal or the trade could not be built: show it, keep going
                print(f"  {label:<20} could not run: {cut(fakea.shown(exc), 70)}")
                continue
        verdict = "none" if row is None else row["verdict"] + (" unknown:" if str(row["reason"]).startswith(
            "unknown:") else "")
        p1 = ", ".join(str(r.value) for r in scores) or "none"
        print(f"  {label:<20} {len(j.sent):<5} {runs:<14} {verdict:<16} {p1}")
        print(f"    p1_judge {cut(ended(j.got, j.raised), 78)}")
    print("The replies are the recording or edits of it: verdicts and a paid call's cost cannot move.")
    print("What moves is what p1_judge returns or raises, the run files it keeps and the rows it stores.")


ORDINALS = ("1st", "2nd", "3rd", "4th", "5th", "6th")
QUEUE = (("challenger", "graded"), ("champion", "graded"), ("teacher", "closed, no grade"),
         ("champion", "verdict stored"), ("challenger", "verdict stored"), ("champion", "never entered"))
RUN_ARMS = ("champion", "challenger", "champion", "challenger")


def queue(grade, journal) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn, theses, _ = fakea.journal_of(Path(tmp), tuple(arm for arm, _ in QUEUE[:5]))
        for t in theses[3:]:
            journal.add_judge_verdict(conn, t.thesis_id, "pass", "stored by hand")
        theses.append(fakea.trade(conn, "champion", 5))
        names = {t.thesis_id: f"{ORDINALS[i]} {t.arm}" for i, t in enumerate(theses)}
        try:
            listed = [names.get(t.thesis_id, "a thesis not in the journal") for t in grade.to_judge(conn)]
            said = f"lists {len(listed)}: {', '.join(listed) or 'none'}"
        except Exception as exc:
            said = f"raised {cut(fakea.shown(exc), 80)}"
        conn.close()
    print("queue: grade.to_judge on 6 FAKEA theses, written in this order:")
    for part in (QUEUE[:3], QUEUE[3:]):
        print("  " + ", ".join(f"{ORDINALS[QUEUE.index(q)]} {q[0]} {q[1]}" for q in part))
    print(f"  {cut(said, 92)}")


def judge_run(grade, replies: tuple[str, ...], max_usd: float) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        conn, theses, bars = fakea.journal_of(data_dir, RUN_ARMS)
        names = {t.thesis_id: f"{ORDINALS[i]} {t.arm}" for i, t in enumerate(theses)}
        sent: list[dict] = []
        try:
            out = grade.judge(conn, bars, fakea.replaying(sent, replies), prices=fakea.prices(), data_dir=data_dir,
                              max_usd=max_usd)
        except Exception as exc:
            out = exc
        spent = sum(fakea.spent(f) for f in fakea.run_files(data_dir))
        conn.close()
    head = f"grade.judge, ${max_usd:.2f} cap, replies {'/'.join(replies)}: {len(sent)} sent, ${spent:.6f} spent"
    if isinstance(out, Exception):
        print(f"{head}; raised {cut(fakea.shown(out), 80)}")
        return
    print(head)
    for j in out:
        said = f"P1 {j.verdict}" if j.verdict is not None else f"not judged: {fakea.masked(str(j.error))}"
        print(f"  {names.get(j.thesis.thesis_id, '?'):<14} ${j.cost_usd:.6f}  {cut(said, 66)}")


def tr_runs() -> None:
    import pytest

    flags = ([], ["--judge", "--dry-run"], ["--judge"], ["--judge"])
    argv = ["grade", "--session", fakea.SESSION]
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        data_dir = Path(tmp)
        conn, _, _ = fakea.journal_of(data_dir, ("champion", "challenger"))
        conn.close()
        try:
            runs = fakea.cli(mp, data_dir, [[*argv, *f] for f in flags], replies=("no_verdict", "recorded"))
        except BaseException as exc:  # SystemExit from argparse included: show it, keep going
            print(f"tr grade raised {cut(fakea.shown(exc), 90)}")
            return
    print(f"tr grade --session {fakea.SESSION} on 2 waiting theses (replies no_verdict, then recorded):")
    for i, (f, (out, sent)) in enumerate(zip(flags, runs)):
        part = [fakea.masked(line) for line in out.splitlines() if "th_" in line or line.startswith("judge")]
        name = " ".join(["tr grade", *f]) + (" again" if i == 3 else "")
        if i == 2:
            print(f"  {name}: {sent} sent")
            for line in part or ["(no judge line)"]:
                print(f"    {cut(line, 92)}")
            continue
        summary = next((line for line in reversed(part) if line.startswith("judge")), "no judge line")
        rows = len(part) - (summary in part)
        print(cut(f"  {name}: {sent} sent, {rows} thesis line(s); {summary}", 94))


def grade_mode() -> None:
    try:
        from tradingresearch import grade, journal
    except Exception as exc:  # a learner's half-written file: show it, keep going
        print(f"tradingresearch.grade did not import: {type(exc).__name__}: {exc}")
        return
    queue(grade, journal)
    judge_run(grade, ("recorded", "no_verdict", "failed", "recorded"), 0.25)
    judge_run(grade, ("recorded",), 0.05)
    tr_runs()
    print("The replies are the recording or edits of it: verdicts and a paid call's cost cannot move.")
    print("What moves is which theses wait, what each run sends under its cap, and what tr grade prints.")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    modes = {"verdicts": verdicts, "judge": judge, "store": store, "grade": grade_mode}
    if mode not in modes:
        print(f"usage: python labs/w3/tools/observe.py {'|'.join(modes)}")
        return 2
    modes[mode]()
    if offline.HITS:
        print(f"note: your code tried {', '.join(dict.fromkeys(offline.HITS))}: blocked, the week-3 labs open no "
              f"connection and start no process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

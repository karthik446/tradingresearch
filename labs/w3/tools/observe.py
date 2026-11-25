"""Observe for the week-3 labs: what your evals.py does with judge replies and what request it sends ($0, no network).

    python labs/w3/tools/observe.py verdicts   # w3l1: p1_verdict on every reply in labs/w3/data/replies.json
    python labs/w3/tools/observe.py judge      # w3l2: p1_judge on the closed FAKEA trade, replayed

`verdicts` prints one row per reply: your (verdict, reason) or the exception, the rubric's reading, and whether they
match. Only `recorded` is model output; the other replies are shapes from tests/test_week3.py, gigai-core's judge
tests or built for these labs (`source` in the JSON says which).

`judge` runs p1_judge through the real OpenRouter adapter whose transport answers with the one recorded reply, then
compares what was sent with the recorded request, and runs it again under a $0.001 cap. The reply
cannot react to what you send: it is evidence for your prompt only when the body equals the recorded one.

TR_LAB_DATA overrides labs/w3/data. Exits 0 in either mode: it shows what your code does, the exercise's check decides.
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


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("verdicts", "judge"):
        print("usage: python labs/w3/tools/observe.py verdicts|judge")
        return 2
    verdicts() if mode == "verdicts" else judge()
    if offline.HITS:
        print(f"note: your code tried {', '.join(dict.fromkeys(offline.HITS))}: blocked, the week-3 labs open no "
              f"connection and start no process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

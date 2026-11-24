"""Capture what `tr lab` really prints for a week's labs: each exercise's first FAIL and its PASS, and the walked-through
session of labs/<week>/session/session.toml. The lab pages on the site show these files; nothing in them is typed by hand.

    python labs/tools/capture.py w1              # capture in scratch copies, compare with the committed files
    python labs/tools/capture.py w1 --write      # rewrite the committed files
    python labs/tools/capture.py w1 --out DIR    # write the captured files under DIR instead (to compare two runs)
    python labs/tools/capture.py w1 --leakcheck  # no capture: check the committed texts hide every solution and hint

Run it from the root of a clone, after uv sync. It never touches the clone it runs from except with --write: it builds
scratch copies the way labs/tools/prove.py does (`Copy`) and runs `tr lab` there with this interpreter.

Exercises: one scratch copy, every lab of the week in order, as a learner would: `tr lab start <lab>`, then for each
exercise `tr lab verify` on the freshly installed stub (must exit 1; its output is
labs/<week>/exercises/<folder>/expected_output/fail.txt), `git apply solution.diff`, `tr lab verify` (must exit 0;
pass.txt), `tr lab next`.
Session: each [[part]] in its own scratch copy; each step either runs a shell line (`tr` is the runner) and, when the
step names an `output` file, keeps what it printed, or (`apply = "solution"`) applies the current exercise's
solution.diff silently.
Normalisation, here and nowhere else: the scratch copy's path becomes `<repo>`, pytest timings (` in 0.12s`) are
dropped, commit hashes become `<sha>` and the time in a backup folder name (`.tr-lab/backup/<id>-<time>/`) becomes
`<time>` (both differ in every clone). stdout and stderr are kept interleaved as a terminal shows them. pass.txt keeps
its first 30 lines and a session output its first 38, then a line `[... N more lines not shown]`.
Leak check: no added line of any solution.diff (unless the stub or the shown tests already hold it), no line of hint 2
or later, and no hint-1 line other than those the session's hint step prints, may occur in an exercise's goal,
what_tested, writes, shown tests, starting code, data lines, fail.txt or pass.txt, or in the session's text and output.
An exercise's starting code may hold the solutions of the exercises before it (a stub is their reference state).
Lines are compared stripped, with whitespace collapsed, 12 characters or more.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from prove import SOURCE, Copy, exercises, key  # the same scratch copies and exercise order as the proof

from tradingresearch.lab import EXERCISE_ID, Labs, _hints  # importable because prove.py put src/ on sys.path

EXERCISE_LINES = 30
SESSION_LINES = 38
SUBJECT = "the repo as you cloned it (capture scratch copy)"
RUNNER = "from tradingresearch.labmain import main; main()"
MIN_LINE = 12


class CaptureError(Exception):
    """A step did not do what the capture needs (a stub that is not red, a solution that is not green, a bad session)."""


def trim(text: str, limit: int) -> str:
    lines = text.rstrip("\n").split("\n")
    if len(lines) > limit:
        lines = lines[:limit] + [f"[... {len(lines) - limit} more lines not shown]"]
    return "\n".join(lines) + "\n"


def normalise(text: str, root: Path) -> str:
    for path in sorted({str(root.resolve()), str(root)}, key=len, reverse=True):
        text = text.replace(path, "<repo>")
    text = re.sub(r" in \d+(?:\.\d+)?s\b", "", text)
    text = re.sub(r"(\.tr-lab/backup/w\d+l\d+\.\d+)-\d{8}-\d{6}", r"\1-<time>", text)
    text = re.sub(r"\bcommit [0-9a-f]{7,40}\b", "commit <sha>", text)
    return re.sub(r"^[0-9a-f]{7,40}(?= )", "<sha>", text, flags=re.M)


class Clone:
    """A scratch copy (prove.py's `Copy`) where shell lines run with `tr` meaning this clone's runner."""

    def __init__(self, root: Path, base: str | None):
        self.copy = Copy(root, base, SUBJECT)
        self.root = root
        self.env = {**self.copy.env, "PYTHONUNBUFFERED": "1", "CAPTURE_PY": sys.executable}

    def sh(self, line: str) -> tuple[int, str]:
        script = f"tr() {{ \"$CAPTURE_PY\" -c '{RUNNER}' \"$@\"; }}\n{line}"
        proc = subprocess.run(["bash", "-c", script], cwd=self.root, env=self.env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return proc.returncode, normalise(proc.stdout, self.root)

    def apply_solution(self, ex_dir: Path) -> None:
        diff = self.root / ex_dir.relative_to(SOURCE) / "solution.diff"
        proc = self.copy.run(["git", "apply", "--whitespace=nowarn", str(diff)])
        if proc.returncode:
            raise CaptureError(f"{diff.relative_to(self.root)} does not apply: {proc.stderr.strip()}")

    def current(self, week_dir: Path) -> Path:
        state = json.loads((self.root / ".tr-lab" / "state.json").read_text())
        found = [ex for ex, meta in exercises(week_dir) if meta["id"] == state["current"]]
        if not found:
            raise CaptureError(f"no current exercise of {week_dir.name} to apply a solution to (state: {state['current']!r})")
        return found[0]


def expect(code: int, want: int, what: str, out: str) -> None:
    if code != want:
        raise CaptureError(f"{what}: exit {code}, the capture needs {want}. It printed:\n{out}")


def rel(path: Path) -> str:
    return str(path.relative_to(SOURCE))


def capture_exercises(week_dir: Path, base: str | None, tmp: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    clone = Clone(tmp / "exercises", base)
    labs: dict[str, list[tuple[Path, dict]]] = {}
    for ex, meta in exercises(week_dir):
        labs.setdefault(meta["lab"], []).append((ex, meta))
    for lab_id in sorted(labs, key=key):
        code, out = clone.sh(f"tr lab start {lab_id}")
        expect(code, 0, f"tr lab start {lab_id}", out)
        for ex, meta in labs[lab_id]:
            code, fail = clone.sh("tr lab verify")
            expect(code, 1, f"{meta['id']}: tr lab verify on the stub", fail)
            clone.apply_solution(ex)
            code, passed = clone.sh("tr lab verify")
            expect(code, 0, f"{meta['id']}: tr lab verify with solution.diff applied", passed)
            code, out = clone.sh("tr lab next")
            expect(code, 0, f"{meta['id']}: tr lab next", out)
            files[f"{rel(ex)}/expected_output/fail.txt"] = fail
            files[f"{rel(ex)}/expected_output/pass.txt"] = trim(passed, EXERCISE_LINES)
    return files


def load_session(week_dir: Path) -> dict | None:
    path = week_dir / "session" / "session.toml"
    if not path.is_file():
        return None
    session = tomllib.loads(path.read_text())
    outputs: set[str] = set()
    for part in session.get("part", []):
        for step in part.get("step", []):
            where = f"session.toml part {part.get('id')!r} step {step.get('title')!r}"
            if ("run" in step) == ("apply" in step) or step.get("apply", "solution") != "solution":
                raise CaptureError(f"{where}: needs exactly one of `run` or `apply = \"solution\"`")
            if "run" in step and "shown" not in step or not step.get("title") or not step.get("explain"):
                raise CaptureError(f"{where}: a step needs title and explain, and a `run` step needs shown")
            name = step.get("output")
            if name is not None and ("apply" in step or name in outputs or not re.fullmatch(r"\d\d-[a-z0-9-]+\.txt", name)):
                raise CaptureError(f"{where}: output {name!r} must be a new NN-name.txt on a run step")
            outputs.add(name)
    return session


def capture_session(week_dir: Path, base: str | None, tmp: Path) -> dict[str, str]:
    session = load_session(week_dir)
    if session is None:
        return {}
    files: dict[str, str] = {}
    for part in session["part"]:
        clone = Clone(tmp / f"session-{part['id']}", base)
        for step in part["step"]:
            if "apply" in step:
                clone.apply_solution(clone.current(week_dir))
                continue
            _, out = clone.sh(step["run"])
            if "output" in step:
                files[f"{rel(week_dir)}/session/{step['output']}"] = trim(out, SESSION_LINES)
    return files


def capture(week: str, keep: bool = False) -> dict[str, str]:
    """Every captured file of the week, repo-relative path -> text, from fresh scratch copies."""
    week_dir = SOURCE / "labs" / week
    base = tomllib.loads((week_dir / "lab.toml").read_text()).get("base")
    tmp = Path(tempfile.mkdtemp(prefix="labs-capture-"))
    try:
        return {**capture_exercises(week_dir, base, tmp), **capture_session(week_dir, base, tmp)}
    finally:
        if keep:
            print(f"scratch copies kept in {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def committed(week: str) -> list[str]:
    week_dir = SOURCE / "labs" / week
    found = [*week_dir.glob("exercises/*/expected_output/*.txt"), *week_dir.glob("session/*.txt")]
    return sorted(rel(p) for p in found)


def drift(week: str, files: dict[str, str]) -> list[tuple[str, str]]:
    """(path, what differs) for each captured file that differs from or is missing in the clone, and each stale one."""
    problems = []
    for path, text in sorted(files.items()):
        mine = SOURCE / path
        if not mine.is_file():
            problems.append((path, "missing (not committed)"))
        elif mine.read_text() != text:
            diff = difflib.unified_diff(mine.read_text().splitlines(), text.splitlines(), "committed", "captured",
                                        n=1, lineterm="")
            shown = list(diff)
            problems.append((path, "\n".join(shown[:12] + ([f"[... {len(shown) - 12} more diff lines]"]
                                                           if len(shown) > 12 else []))))
    problems += [(path, "committed but no longer captured") for path in committed(week) if path not in files]
    return problems


# ---------- what the site shows, for the leak check ----------


def collapse(line: str) -> str:
    return " ".join(line.split())


def long_lines(text: str) -> set[str]:
    return {c for c in map(collapse, text.splitlines()) if len(c) >= MIN_LINE}


def shown_tests(ex: Path, meta: dict) -> list[tuple[str, str]]:
    """The `show_tests` functions of the exercise's test file, from the first decorator to the last line."""
    test = next(ex.glob("test_*.py"))
    source = test.read_text()
    lines = source.splitlines()
    found = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    out = []
    for name in meta.get("show_tests", []):
        node = found.get(name)
        if node is None:
            raise CaptureError(f"{meta['id']}: show_tests names {name!r}, which is no module-level function of {test.name}")
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        out.append((name, "\n".join(lines[first - 1:node.end_lineno])))
    return out


def todo_line(text: str, ex_id: str) -> int | None:
    """1-based line of the TODO(<id>) comment (a `#` or `<!--` comment, not a message that mentions it)."""
    marker = re.compile(rf"(#|<!--)\s*TODO\({re.escape(ex_id)}\)")
    return next((n for n, line in enumerate(text.splitlines(), 1) if marker.search(line)), None)


def start_code(ex: Path, meta: dict, earlier: list[Path]) -> list[tuple[str, str]]:
    """The code around TODO(<id>) in the touched stub files (the enclosing top-level def or class of a .py file, else
    the marker line and 4 lines each side). An exercise without a stub works on the file an earlier stub installed."""
    out = []
    for path in meta["touches"]:
        stub = next((d / "stub" / path for d in [ex, *reversed(earlier)] if (d / "stub" / path).is_file()), None)
        text = stub.read_text() if stub else ""
        line = todo_line(text, meta["id"])
        if line is None:
            continue
        lines = text.splitlines()
        first, last = max(1, line - 4), min(len(lines), line + 4)
        if path.endswith(".py"):
            for node in ast.parse(text).body:
                top = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
                if top <= line <= node.end_lineno and isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    first, last = top, node.end_lineno
        out.append((path, "\n".join(lines[first - 1:last])))
    return out


def data_lines(ex: Path, meta: dict) -> list[tuple[str, str]]:
    return [(path, "\n".join((ex / "stub" / path).read_text().splitlines()[:2])) for path in meta.get("show_data", [])]


def hint_step_outputs(week_dir: Path, session: dict | None) -> list[str]:
    """The captured output of each session step that runs `tr lab hint` and prints a hint."""
    outs = []
    for part in (session or {}).get("part", []):
        for step in part["step"]:
            path = week_dir / "session" / step.get("output", "-")
            if re.search(r"\btr lab hint\b", step.get("run", "")) and path.is_file() and "hint 1 of" in path.read_text():
                outs.append(path.read_text())
    return outs


def leakcheck(week: str) -> list[str]:
    week_dir = SOURCE / "labs" / week
    labs = Labs(SOURCE)
    session = load_session(week_dir)
    hint_out = "\n".join(hint_step_outputs(week_dir, session))
    allowed_hint1 = long_lines(hint_out)
    exs = exercises(week_dir)
    blobs: list[tuple[str, int | None, str, str]] = []  # (label, index of the exercise or None, kind, text)
    hidden: list[tuple[set[str], set[str]]] = []  # per exercise: solution lines, hint lines
    for i, (ex, meta) in enumerate(exs):
        tests = shown_tests(ex, meta)
        # a solution line the stub or a shown test already holds (whole, or as part of a longer line) is no secret
        shown = collapse("\n".join([*(f.read_text() for f in (ex / "stub").rglob("*") if f.is_file()),
                                    *(code for _, code in tests)]))
        added = "\n".join(ln[1:] for ln in (ex / "solution.diff").read_text().splitlines()
                          if ln.startswith("+") and not ln.startswith("+++"))
        hints = _hints(labs.exercises[meta["id"]])
        hint_lines = set().union(*(long_lines(h) for h in hints[1:])) | (long_lines(hints[0]) - allowed_hint1 if hints else set())
        hidden.append(({line for line in long_lines(added) if line not in shown}, hint_lines))
        label = meta["id"]
        for field in ("goal", "what_tested"):
            blobs.append((f"{label} {field}", i, "text", meta.get(field, "")))
        blobs += [(f"{label} writes[{k}]", i, "text", w) for k, w in enumerate(meta.get("writes", []))]
        blobs += [(f"{label} test {name}", i, "test", code) for name, code in tests]
        blobs += [(f"{label} start code {path}", i, "start", code)
                  for path, code in start_code(ex, meta, [e for e, _ in exs[:i]])]
        blobs += [(f"{label} data {path}", i, "start", text) for path, text in data_lines(ex, meta)]
        for name in ("fail.txt", "pass.txt"):
            path = ex / "expected_output" / name
            blobs.append((f"{label} {name}", i, "output", path.read_text() if path.is_file() else ""))
    if session is not None:
        blobs.append(("session diagram", None, "text", session.get("diagram", "")))
        for part in session["part"]:
            blobs += [(f"session {part['id']} {k}", None, "text", str(part.get(k, ""))) for k in ("title", "intro")]
            for n, step in enumerate(part["step"], 1):
                for k in ("title", "shown", "explain"):
                    blobs.append((f"session {part['id']} step {n} {k}", None, "text", str(step.get(k, ""))))
                if "output" in step:
                    path = week_dir / "session" / step["output"]
                    blobs.append((f"session {step['output']}", None, "output", path.read_text() if path.is_file() else ""))
    findings = []
    for label, owner, kind, text in blobs:
        flat = collapse(text)
        for j, (solution, hint_lines) in enumerate(hidden):
            # a later exercise's stub is the reference state of the earlier ones: their solutions may show there
            for line in solution if not (kind == "start" and owner is not None and owner > j) else set():
                if line in flat:
                    findings.append(f"{label}: solution line of {exs[j][1]['id']}: {line[:70]!r}")
            findings += [f"{label}: hint line of {exs[j][1]['id']}: {line[:70]!r}" for line in hint_lines if line in flat]
    for ex, meta in exs:
        missing = [f for f in ("goal", "what_tested", "writes", "show_tests") if not meta.get(f)]
        if missing:
            findings.append(f"{meta['id']}: exercise.toml lacks {', '.join(missing)}")
        if not EXERCISE_ID.fullmatch(meta["id"]):
            findings.append(f"{meta['id']}: not an exercise id")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("week", help="the folder under labs/, e.g. w1")
    what = parser.add_mutually_exclusive_group()
    what.add_argument("--write", action="store_true", help="rewrite the committed files with the capture")
    what.add_argument("--out", type=Path, help="write the captured files under this folder instead")
    what.add_argument("--leakcheck", action="store_true", help="check the committed texts for solution and hint lines")
    parser.add_argument("--keep", action="store_true", help="leave the scratch copies for inspection")
    args = parser.parse_args()
    if not (SOURCE / "labs" / args.week / "lab.toml").is_file():
        parser.error(f"no labs/{args.week}/lab.toml")
    try:
        if args.leakcheck:
            findings = leakcheck(args.week)
            print(*findings, sep="\n")
            print(f"leak check {args.week}: {len(findings)} finding(s)")
            return 1 if findings else 0
        files = capture(args.week, args.keep)
    except CaptureError as err:
        print(f"capture failed: {err}", file=sys.stderr)
        return 2
    if args.write or args.out:
        root = args.out.resolve() if args.out else SOURCE
        if args.write:
            for path in committed(args.week):
                if path not in files:
                    (SOURCE / path).unlink()
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        print(f"wrote {len(files)} files under {root}")
        return 0
    problems = drift(args.week, files)
    for path, what_differs in problems:
        print(f"DRIFT {path}\n{what_differs}")
    print(f"captures {len(files) - sum(p in files for p, _ in problems)}/{len(files)} match")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

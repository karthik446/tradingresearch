"""Prove the week-1 labs: every stub red, every solution green, every known wrong fix red, earlier checks still green,
the end state equal to `week-1-end`, and the real `tr lab` runner driving one lab end to end.

    python labs/w1/tools/prove.py                 # from the root of a clean clone (code at week-1-start), after uv sync
    python labs/w1/tools/prove.py > labs/w1/PROOF.md

It never touches the clone it runs from: it copies the clone's files (tracked and untracked, not ignored) to a temp
folder twice, gives each copy a git repo of its own (one commit; a worktree's `.git` file would point back at the
source), runs the chain in one copy and the runner smoke in the other, then deletes both (`--keep` leaves them). Checks
run with this interpreter and PYTHONPATH=<copy>/src, so the copy's code is the code under test.

Chain, for each exercise in order (exercises build on each other):
  1. learner data: every non-.py file an earlier exercise touches gets a marker appended; after the stub is copied
     over the copy the marker must still be there (a stub that replaces a learner's notes is NOT PROVEN);
  2. stub: copy stub/ (if any), run `check`: exit 1 and `red_expect` in the first pytest `E` line;
  3. solution: `git apply solution.diff`, run `check`: exit 0;
  4. chain: re-run the check of every earlier exercise of the same lab: exit 0 (a later solution must not break an
     earlier one);
  5. wrong fixes: for each wrong/<name>.diff, `git apply` it on the solved state, run `check`: exit 1 and the diff's
     `expect:` header in the first `E` line, then `git apply -R`.
A wrong diff starts with header lines before its `---` line (git apply skips them):
    why: <what the fix gets wrong>    expect: <fragment of the first E line>    before: GREEN|RED (<who saw it>)
End state: after the last exercise, the six files week 1 ends with must equal the source clone's `week-1-end` tag
byte for byte.
Runner smoke: `tr lab` itself (start, a red verify, next refused, hint locked then unlocked, the solution applied,
verify, next) through lab w1l1, then `start w1l3 --assume-previous`, whose w1l3.1 stub overwrites the analyze.py lab
w1l1 committed (it must say so and back it up). Exits 1 if any row is NOT PROVEN.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
SOURCE = LAB.parents[1]
MARKER = b"\nprove.py learner-data marker\n"
END_STATE = ["src/tradingresearch/analyze.py", "src/tradingresearch/evals.py", "evals/labels.csv", "evals/taxonomy.md",
             "prompts/analyze-2.txt", "experiments/prompt-v2.toml"]
GIT_ENV = {"GIT_AUTHOR_NAME": "prove", "GIT_AUTHOR_EMAIL": "prove@localhost", "GIT_COMMITTER_NAME": "prove",
           "GIT_COMMITTER_EMAIL": "prove@localhost"}


def key(ident: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", ident))


class Copy:
    """A throwaway copy of the source clone."""

    def __init__(self, root: Path):
        self.root = root
        listed = subprocess.run(["git", "ls-files", "-z", "-co", "--exclude-standard"], cwd=SOURCE,
                                capture_output=True, check=True).stdout.decode()
        for rel in filter(None, listed.split("\0")):
            if (SOURCE / rel).is_file():  # a tracked file deleted in the source is skipped
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SOURCE / rel, root / rel)
        inherited = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        self.env = {**inherited, **GIT_ENV, "COLUMNS": "200", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(root / "src")}
        for argv in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                     ["git", "commit", "-qm", "prove: copy of the source clone"]):
            subprocess.run(argv, cwd=root, capture_output=True, check=True, env=self.env)

    def run(self, argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, cwd=self.root, capture_output=True, text=True, env=self.env)

    def check(self, command: str) -> tuple[int, str, str]:
        argv = shlex.split(command)
        argv[0] = sys.executable if argv[0] == "python" else argv[0]
        proc = self.run(argv)
        lines = (proc.stdout + proc.stderr).splitlines()
        first = next((line[1:].strip() for line in lines if line.startswith("E ")), "")
        summary = next((line.strip("= ") for line in reversed(lines) if " passed" in line or " failed" in line
                        or " error" in line), lines[-1] if lines else "")
        return proc.returncode, first, summary

    def apply(self, diff: Path, *flags: str) -> bool:
        return self.run(["git", "apply", "--whitespace=nowarn", *flags, str(diff)]).returncode == 0

    def tr(self, *args: str) -> subprocess.CompletedProcess:
        return self.run([sys.executable, "-c", "from tradingresearch.cli import main; main()", *args])


def exercises() -> list[tuple[Path, dict]]:
    found = [(p.parent, tomllib.loads(p.read_text())) for p in (LAB / "exercises").glob("*/exercise.toml")]
    return sorted(found, key=lambda e: key(e[1]["id"]))


def install_stub(copy: Copy, ex: Path, earlier: list[dict]) -> list[str]:
    """Copy stub/ over the copy; return the learner files (non-code files earlier exercises touch) it replaced."""
    paths = sorted({p for meta in earlier for p in meta["touches"] if not p.endswith(".py")})
    saved = {copy.root / p: (copy.root / p).read_bytes() for p in paths if (copy.root / p).exists()}
    for path, data in saved.items():
        path.write_bytes(data + MARKER)
    stub = ex / "stub"
    for f in sorted(stub.rglob("*")) if stub.is_dir() else []:
        if f.is_file():
            dest = copy.root / f.relative_to(stub)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
    replaced = [str(path.relative_to(copy.root)) for path in saved if not path.read_bytes().endswith(MARKER)]
    for path, data in saved.items():
        path.write_bytes(data)
    return replaced


def wrong_fixes(ex: Path) -> list[tuple[Path, dict[str, str]]]:
    cases = []
    for diff in sorted((ex / "wrong").glob("*.diff")):
        head = {}
        for line in diff.read_text().splitlines():
            if line.startswith("--- "):
                break
            name, _, value = line.partition(":")
            head[name.strip()] = value.strip()
        cases.append((diff, head))
    return cases


def chain(copy: Copy) -> tuple[list[tuple], dict[str, int]]:
    rows: list[tuple] = []
    n = {"stub": 0, "solution": 0, "wrong": 0, "chain": 0, "bad": 0}
    done: list[tuple[Path, dict]] = []

    def row(*cells: object, ok: bool, kind: str) -> None:
        rows.append(cells)
        n[kind] += ok
        n["bad"] += not ok

    for ex, meta in exercises():
        replaced = install_stub(copy, ex, [m for _, m in done])
        code, first, _ = copy.check(meta["check"])
        ok = code == 1 and meta["red_expect"] in first and not replaced
        note = f"stub overwrites learner file {', '.join(replaced)}" if replaced else ""
        row(meta["id"], "stub" if (ex / "stub").is_dir() else "no stub (learner's own files)",
            f"red: {meta['red_expect']}", code, first, "ok" if ok else f"**NOT PROVEN** {note}".strip(), ok=ok, kind="stub")
        applied = copy.apply(ex / "solution.diff")
        code, _, summary = copy.check(meta["check"]) if applied else (-1, "", "solution.diff does not apply")
        ok = applied and code == 0
        row(meta["id"], "solution.diff", "green", code, summary, "ok" if ok else "**NOT PROVEN**", ok=ok, kind="solution")
        for _, prev in [d for d in done if d[1]["lab"] == meta["lab"]]:
            code, first, summary = copy.check(prev["check"])
            ok = code == 0
            if not ok:
                print(f"CHAIN RED: {prev['id']} goes red after the solution of {meta['id']}: {first}", file=sys.stderr)
            row(meta["id"], f"chain: {prev['id']} still green", "green", code, summary if ok else first,
                "ok" if ok else "**NOT PROVEN**", ok=ok, kind="chain")
        for diff, head in wrong_fixes(ex):
            case = f"wrong/{diff.name}: {head.get('why', '')}"
            before = head.get("before", "?").split()[0]
            if not copy.apply(diff):
                row(meta["id"], case, f"red: {head.get('expect')}", -1, "does not apply", "**NOT PROVEN**", ok=False, kind="wrong")
                continue
            code, first, _ = copy.check(meta["check"])
            copy.apply(diff, "-R")
            ok = code == 1 and bool(head.get("expect")) and head["expect"] in first
            row(meta["id"], case, f"red: {head.get('expect')}", code, first,
                f"{before} → red" if ok else f"**NOT PROVEN** ({before} → {'red' if code else 'GREEN'})", ok=ok, kind="wrong")
        done.append((ex, meta))
    return rows, n


def end_state(copy: Copy) -> tuple[list[tuple], int]:
    if subprocess.run(["git", "rev-parse", "-q", "--verify", "week-1-end"], cwd=SOURCE, capture_output=True).returncode:
        return [("(all)", "skipped: no week-1-end tag in this clone")], 0
    rows, bad = [], 0
    for path in END_STATE:
        tagged = subprocess.run(["git", "show", f"week-1-end:{path}"], cwd=SOURCE, capture_output=True).stdout
        mine = (copy.root / path).read_bytes() if (copy.root / path).exists() else None
        ok = mine == tagged
        rows.append((path, "equal" if ok else "**NOT PROVEN**: differs from week-1-end"))
        bad += not ok
    return rows, bad


SMOKE_W1L1 = [
    # (tr lab arguments or a git command, expected exit code, text (or tuple of texts) the output must contain)
    (["list"], 0, "start here       w1l1.1"),
    (["start", "w1l2"], 2, "builds on w1l1, which is not finished"),
    (["start", "w1l1"], 0, "edit: src/tradingresearch/analyze.py (look for TODO(w1l1.1))"),
    (["verify"], 1, "FAIL w1l1.1 (try 1)"),
    (["next"], 2, "`next` stays here"),
    (["hint"], 2, "hint 1 unlocks after 2 failed runs"),
    (["verify"], 1, "hint 1 is unlocked"),
    (["hint"], 0, "hint 1 of 2 (w1l1.1)"),
    (["solution"], 2, "unlocks after 10 failed runs or when the check is green"),
    ("apply w1l1.1", 0, ""),
    (["verify"], 0, "PASS w1l1.1"),
    (["solution"], 0, "+++ b/src/tradingresearch/analyze.py"),
    (["next"], 0, "exercise w1l1.2"),
    (["verify", "w1l1.3"], 2, "not reached yet"),
    (["verify", "w1l1"], 1, "w1l1: 1 of 2 reached exercises green"),
    ("apply w1l1.2", 0, ""),
    (["next"], 0, "exercise w1l1.3"),
    ("apply w1l1.3", 0, ""),
    (["next"], 0, "exercise w1l1.4"),
    ("apply w1l1.4", 0, ""),
    (["next"], 0, "lab w1l1 finished; tr lab start w1l2"),
    (["verify", "w1l1"], 0, "w1l1: 4 of 4 reached exercises green"),
    ("git log", 0, "lab w1l1.4: green"),
    (["start", "w1l3", "--assume-previous"], 0, ("applied the reference solutions of w1l2.1..w1l2.4",
                                                 "w1l3.1 starts from the reference version of w1l1.4 in "
                                                 "src/tradingresearch/analyze.py; your version is in commit")),
    (["verify"], 1, "FAIL w1l3.1 (try 1)"),
    (["list"], 0, "done (reference) w1l2.4"),
]


def smoke(copy: Copy) -> tuple[list[tuple], int]:
    by_id = {meta["id"]: ex for ex, meta in exercises()}
    rows, bad = [], 0
    for step, want_code, want_text in SMOKE_W1L1:
        if isinstance(step, list):
            proc, label = copy.tr("lab", *step), "tr lab " + " ".join(step)
        elif step == "git log":
            proc, label = copy.run(["git", "log", "--format=%s", "-6"]), "git log"
        else:
            ex_id = step.split()[1]
            proc, label = copy.run(["git", "apply", str(by_id[ex_id] / "solution.diff")]), f"git apply {ex_id} solution.diff"
        out = proc.stdout + proc.stderr
        texts = want_text if isinstance(want_text, tuple) else (want_text,)
        ok = proc.returncode == want_code and all(t in out for t in texts)
        found = [next((ln.strip() for ln in out.splitlines() if t in ln), "") for t in texts if t]
        shown = " / ".join(found) if any(found) else out.strip().splitlines()[0] if out.strip() else ""
        shown = re.sub(r"-\d{8}-\d{6}/", "-<time>/", re.sub(r"commit [0-9a-f]{7,}", "commit <sha>", shown))
        rows.append((label, want_code, proc.returncode, shown, "ok" if ok else "**NOT PROVEN**"))
        bad += not ok
    return rows, bad


def cell(text: object, roots: list[Path]) -> str:
    out = str(text)
    for root in roots:
        out = out.replace(str(root), "<copy>")
    return out.replace("|", "\\|")


def table(head: list[str], rows: list[tuple], roots: list[Path]) -> None:
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in rows:
        print("| " + " | ".join(cell(c, roots) for c in r) + " |")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="leave the temp copies for inspection")
    args = parser.parse_args()
    started = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="labs-prove-"))
    try:
        chain_copy, smoke_copy = Copy(tmp / "chain"), Copy(tmp / "smoke")
        roots = [chain_copy.root, smoke_copy.root]
        rows, n = chain(chain_copy)
        end_rows, end_bad = end_state(chain_copy)
        smoke_rows, smoke_bad = smoke(smoke_copy)
    finally:
        if args.keep:
            print(f"copies kept in {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    bad = n["bad"] + end_bad + smoke_bad
    print("# Week-1 labs: proof\n")
    print(f"Generated by `python labs/w1/tools/prove.py > labs/w1/PROOF.md` on {time.strftime('%Y-%m-%d')}, "
          f"commit {head}{' plus uncommitted changes' if dirty else ''}, Python {platform.python_version()}, "
          f"{time.monotonic() - started:.0f} s. The tool's docstring says what each row checks.\n")
    print("## Exercises: stub, solution, chain, wrong fixes\n")
    table(["exercise", "case", "expected", "exit", "first pytest E line (green: summary)", "result"], rows, roots)
    print("## End state\n")
    print("After the last solution, the six files week 1 ends with, against the `week-1-end` tag:\n")
    table(["file", "result"], end_rows, roots)
    print("## Runner smoke\n")
    print("`tr lab` itself, driven step by step in a second copy:\n")
    table(["step", "expected exit", "exit", "output line", "result"], smoke_rows, roots)
    print(f"{n['stub']} stubs red, {n['solution']} solutions green, {n['wrong']} wrong fixes red, "
          f"chain: {n['chain']} earlier checks still green, end state {len(END_STATE) - end_bad}/{len(END_STATE)} equal, "
          f"runner smoke {len(smoke_rows) - smoke_bad}/{len(smoke_rows)} steps ok; {bad} NOT PROVEN")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

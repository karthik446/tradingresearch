"""Prove a week's labs: every stub red, every solution green, every known wrong fix red, earlier checks still green,
the end state equal to the week's end tag, and the real `tr lab` runner driving one lab end to end.

    python labs/tools/prove.py w1                 # from the root of a clean clone, after uv sync
    python labs/tools/prove.py w1 > labs/w1/PROOF.md

labs/<week>/lab.toml gives the week's `base` (the tag its labs start from, if any) and `[end]` (`tag`, `files`).

It never touches the clone it runs from: it copies the clone's files (tracked and untracked, not ignored) to a temp
folder twice, gives each copy a git repo of its own (one commit; a worktree's `.git` file would point back at the
source), runs the chain in one copy and the runner smoke in the other, then deletes both (`--keep` leaves them). Checks
run with this interpreter and PYTHONPATH=<copy>/src, so the copy's code is the code under test. For a week with a
base, both copies get the base tag; the chain copy has the base applied by the runner's own `Labs.apply_base` first,
the smoke copy by `tr lab start <first lab>`.

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
End state: after the last exercise, the `[end].files` must equal the source clone's `[end].tag` byte for byte.
Runner smoke: `tr lab` itself (start, a red verify, next refused, hint locked then unlocked, the solution applied,
verify, next) through the week's first lab, then `start <third lab> --assume-previous`; when its first stub overwrites
a file the first lab committed, it must say so and back it up.
Hint guard: a hint teaches the idea, not the code. No hints.md may hold a fenced block of more than one line, or any
added line of its exercise's solution.diff (stripped, 12 characters or more). A self-test plants the first such line
of a solution and a three-line fence in a hint; the guard must catch both. Exits 1 if any row is NOT PROVEN.
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

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / "src"))
from tradingresearch.lab import Lab, Labs, _edit_line, _hints  # noqa: E402  the runner's own reading of labs/

MARKER = b"\nprove.py learner-data marker\n"
GIT_ENV = {"GIT_AUTHOR_NAME": "prove", "GIT_AUTHOR_EMAIL": "prove@localhost", "GIT_COMMITTER_NAME": "prove",
           "GIT_COMMITTER_EMAIL": "prove@localhost"}


def key(ident: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", ident))


class Copy:
    """A throwaway copy of the source clone."""

    def __init__(self, root: Path, base: str | None):
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
        if base:
            subprocess.run(["git", "fetch", "-q", str(SOURCE), f"refs/tags/{base}:refs/tags/{base}"], cwd=root,
                           capture_output=True, check=True, env=self.env)

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
        return self.run([sys.executable, "-c", "from tradingresearch.labmain import main; main()", *args])


def exercises(lab: Path) -> list[tuple[Path, dict]]:
    found = [(p.parent, tomllib.loads(p.read_text())) for p in (lab / "exercises").glob("*/exercise.toml")]
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


def apply_base(copy: Copy, week: str, tag: str) -> tuple[list[tuple], int]:
    """The runner's own base step, run in the copy with the copy's code."""
    code = ("import sys; from pathlib import Path; from tradingresearch.lab import Labs; "
            "print(*Labs(Path.cwd()).apply_base(sys.argv[1]), sep='\\n')")
    proc = copy.run([sys.executable, "-c", code, week])
    ok = proc.returncode == 0
    return [(tag, " / ".join((proc.stdout + proc.stderr).strip().splitlines()), "ok" if ok else "**NOT PROVEN**")], not ok


def chain(copy: Copy, exs: list[tuple[Path, dict]]) -> tuple[list[tuple], dict[str, int]]:
    rows: list[tuple] = []
    n = {"stub": 0, "solution": 0, "wrong": 0, "chain": 0, "bad": 0}
    done: list[tuple[Path, dict]] = []

    def row(*cells: object, ok: bool, kind: str) -> None:
        rows.append(cells)
        n[kind] += ok
        n["bad"] += not ok

    for ex, meta in exs:
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


FENCE = re.compile(r"^(```|~~~)")


def solution_lines(ex: Path) -> list[str]:
    """The added lines of an exercise's solution.diff, stripped, 12 characters or more."""
    lines = [line[1:].strip() for line in (ex / "solution.diff").read_text().splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    return [line for line in lines if len(line) >= 12]


def hint_leaks(text: str, solution: list[str]) -> list[str]:
    """Why a hints.md shows code: each fenced block of more than one line, each solution line it contains."""
    leaks, fence = [], None
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.strip()):
            if fence is None:
                fence = [number, 0]
            else:
                if fence[1] > 1:
                    leaks.append(f"line {fence[0]}: fenced block of {fence[1]} lines")
                fence = None
        elif fence is not None:
            fence[1] += 1
    if fence is not None:
        leaks.append(f"line {fence[0]}: fenced block never closed")
    leaks += [f"solution line {line[:60]!r}" for line in solution if line in text]
    return leaks


def hint_guard(exs: list[tuple[Path, dict]]) -> tuple[list[tuple], int]:
    rows, bad = [], 0
    for ex, meta in exs:
        leaks = hint_leaks((ex / "hints.md").read_text(), solution_lines(ex))
        bad += bool(leaks)
        rows.append((meta["id"], "; ".join(leaks) or "no fence over 1 line, no solution line",
                     "**NOT PROVEN**" if leaks else "ok"))
    ex, meta = exs[0]
    planted = solution_lines(ex)[0]
    text = (ex / "hints.md").read_text() + f"\n{planted}\n\n```\na\nb\nc\n```\n"
    leaks = hint_leaks(text, solution_lines(ex))
    ok = any(leak.startswith("solution line") for leak in leaks) and any("fenced block" in leak for leak in leaks)
    bad += not ok
    rows.append((f"self-test ({meta['id']})", f"planted {planted[:60]!r} and a 3-line fence: {'; '.join(leaks)}",
                 "caught" if ok else "**NOT PROVEN**: the guard missed a planted solution"))
    return rows, bad


def end_state(copy: Copy, end: dict | None) -> tuple[list[tuple], int]:
    if not end:
        return [("(all)", "skipped: lab.toml has no [end]")], 0
    tag = end["tag"]
    if subprocess.run(["git", "rev-parse", "-q", "--verify", tag], cwd=SOURCE, capture_output=True).returncode:
        return [("(all)", f"skipped: no {tag} tag in this clone")], 0
    rows, bad = [], 0
    for path in end["files"]:
        tagged = subprocess.run(["git", "show", f"{tag}:{path}"], cwd=SOURCE, capture_output=True).stdout
        mine = (copy.root / path).read_bytes() if (copy.root / path).exists() else None
        ok = mine == tagged
        rows.append((path, "equal" if ok else f"**NOT PROVEN**: differs from {tag}"))
        bad += not ok
    return rows, bad


def patched(ex_dir: Path) -> list[str]:
    """The files a solution.diff changes."""
    return re.findall(r"^\+\+\+ b/(.+)$", (ex_dir / "solution.diff").read_text(), flags=re.M)


def smoke_steps(labs: Labs, week: str) -> list[tuple]:
    """The walk through the week's first lab, then the third lab with --assume-previous, from the week's lab ids.

    Each step: (tr lab arguments, "apply <exercise id>" or "git log"; expected exit code; text or tuple of texts the
    output must contain).
    """
    week_labs: list[Lab] = [lab for lab in labs.labs if lab.week == week]
    first, exs = week_labs[0], week_labs[0].exercises
    e1, base = exs[0], labs.bases.get(week)
    steps: list[tuple] = [(["list"], 0, f"start here       {e1.id}")]
    if len(week_labs) > 1:
        steps.append((["start", week_labs[1].id], 2, f"builds on {first.id}, which is not finished"))
    edit = _edit_line(labs, e1)
    started = (f"week {key(week)[0]} starts from the author's code at {base}", edit) if base else edit
    steps += [(["start", first.id], 0, started), (["verify"], 1, f"FAIL {e1.id} (try 1)"),
              (["next"], 2, "`next` stays here")]
    fails = 1
    if first.hint_after(1) > 1:
        steps.append((["hint"], 2, f"hint 1 unlocks after {first.hint_after(1)} failed runs"))
        for fails in range(2, first.hint_after(1) + 1):
            steps.append((["verify"], 1, "hint 1 is unlocked" if fails == first.hint_after(1) else f"FAIL {e1.id} (try {fails})"))
    if _hints(e1):
        steps.append((["hint"], 0, f"hint 1 of {len(_hints(e1))} ({e1.id})"))
    if first.solution > fails:
        steps.append((["solution"], 2, f"unlocks after {first.solution} failed runs or when the check is green"))
    steps += [(f"apply {e1.id}", 0, ""), (["verify"], 0, f"PASS {e1.id}"),
              (["solution"], 0, f"+++ b/{patched(e1.dir)[0]}")]
    finished = f"lab {first.id} finished" + (f"; tr lab start {week_labs[1].id}" if len(week_labs) > 1 else "")
    for i in range(1, len(exs) + 1):
        if i > 1:
            steps.append((f"apply {exs[i - 1].id}", 0, ""))
        steps.append((["next"], 0, f"exercise {exs[i].id}" if i < len(exs) else finished))
        if i == 1 and len(exs) > 1:
            if len(exs) > 2:
                steps.append((["verify", exs[2].id], 2, "not reached yet"))
            steps.append((["verify", first.id], 1, f"{first.id}: 1 of 2 reached exercises green"))
    steps += [(["verify", first.id], 0, f"{first.id}: {len(exs)} of {len(exs)} reached exercises green"),
              ("git log", 0, f"lab {exs[-1].id}: green")]
    if len(week_labs) > 2:
        skipped, third = week_labs[1].exercises, week_labs[2].exercises[0]
        texts = [f"applied the reference solutions of {skipped[0].id}..{skipped[-1].id}"]
        later = {rel for ex in skipped for rel in patched(ex.dir)}
        stubbed = sorted(str(f.relative_to(third.stub)) for f in third.stub.rglob("*") if f.is_file()) \
            if third.stub.is_dir() else []
        for rel in stubbed:
            mine = [ex.id for ex in exs if rel in patched(ex.dir)]
            if mine and rel not in later:
                texts.append(f"{third.id} starts from the reference version of {mine[-1]} in {rel}; "
                             "your version is in commit")
                break
        steps.append((["start", week_labs[2].id, "--assume-previous"], 0, tuple(texts)))
        if stubbed:
            steps.append((["verify"], 1, f"FAIL {third.id} (try 1)"))
        steps.append((["list"], 0, f"done (reference) {skipped[-1].id}"))
    return steps


def smoke(copy: Copy, steps: list[tuple], exs: list[tuple[Path, dict]]) -> tuple[list[tuple], int]:
    by_id = {meta["id"]: ex for ex, meta in exs}
    rows, bad = [], 0
    for step, want_code, want_text in steps:
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
    parser.add_argument("week", help="the folder under labs/, e.g. w1")
    parser.add_argument("--keep", action="store_true", help="leave the temp copies for inspection")
    args = parser.parse_args()
    lab = SOURCE / "labs" / args.week
    if not (lab / "lab.toml").is_file():
        parser.error(f"no {lab / 'lab.toml'}")
    config = tomllib.loads((lab / "lab.toml").read_text())
    base, end = config.get("base"), config.get("end")
    files = end["files"] if end else []
    exs = exercises(lab)
    started = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="labs-prove-"))
    try:
        chain_copy, smoke_copy = Copy(tmp / "chain", base), Copy(tmp / "smoke", base)
        roots = [chain_copy.root, smoke_copy.root]
        base_rows, base_bad = apply_base(chain_copy, args.week, base) if base else ([], 0)
        rows, n = chain(chain_copy, exs)
        end_rows, end_bad = end_state(chain_copy, end)
        smoke_rows, smoke_bad = smoke(smoke_copy, smoke_steps(Labs(SOURCE), args.week), exs)
        hint_rows, hint_bad = hint_guard(exs)
    finally:
        if args.keep:
            print(f"copies kept in {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    bad = base_bad + n["bad"] + end_bad + smoke_bad + hint_bad
    number = key(args.week)[0]
    print(f"# Week-{number} labs: proof\n")
    print(f"Generated by `python labs/tools/prove.py {args.week} > labs/{args.week}/PROOF.md` on "
          f"{time.strftime('%Y-%m-%d')}, commit {head}{' plus uncommitted changes' if dirty else ''}, "
          f"Python {platform.python_version()}, {time.monotonic() - started:.0f} s. The tool's docstring says what each "
          "row checks.\n")
    if base:
        print("## Base\n")
        print(f"The chain copy starts from `{base}`, applied by the runner's `Labs.apply_base`:\n")
        table(["tag", "runner output", "result"], base_rows, roots)
    print("## Exercises: stub, solution, chain, wrong fixes\n")
    table(["exercise", "case", "expected", "exit", "first pytest E line (green: summary)", "result"], rows, roots)
    print("## End state\n")
    if end:
        print(f"After the last solution, the {len(files)} files week {number} ends with, against the `{end['tag']}` tag:\n")
    table(["file", "result"], end_rows, roots)
    print("## Runner smoke\n")
    print("`tr lab` itself, driven step by step in a second copy:\n")
    table(["step", "expected exit", "exit", "output line", "result"], smoke_rows, roots)
    print("## Hint guard\n")
    print("Every hints.md against its own solution.diff, then a planted solution that must be caught:\n")
    table(["exercise", "finding", "result"], hint_rows, roots)
    print(f"{n['stub']} stubs red, {n['solution']} solutions green, {n['wrong']} wrong fixes red, "
          f"chain: {n['chain']} earlier checks still green, end state {len(files) - end_bad}/{len(files)} equal, "
          f"runner smoke {len(smoke_rows) - smoke_bad}/{len(smoke_rows)} steps ok, "
          f"hint guard {sum(r[2] == 'ok' for r in hint_rows[:-1])}/{len(hint_rows) - 1} hints clean "
          f"and self-test {'caught' if hint_rows[-1][2] == 'caught' else 'MISSED'}; {bad} NOT PROVEN")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""`tr lab`: the week labs, run and checked on your own machine. No keys, no model calls, no network.

A lab is a short run of exercises (labs/<week>/exercises/<id>-<slug>/). Each exercise ships a stub (the repo files with a
TODO cut out), a check (a pytest file), hints, a reference solution diff and an observe command. `tr lab` installs the
stub, runs the check, counts failed runs to unlock hints and the solution, and commits each green exercise on the branch
`lab`. State lives in .tr-lab/state.json (gitignored); edits it would overwrite are copied to .tr-lab/backup/ first.
How to use it: labs/README.md. The unlock numbers: labs/<week>/lab.toml.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

LAB_ID = re.compile(r"w(\d+)l(\d+)")
EXERCISE_ID = re.compile(r"w(\d+)l(\d+)\.(\d+)")
WIDTH = 100


class LabError(Exception):
    """Refusal or failure with a message for the learner; `tr lab` prints it and exits 2."""


@dataclass(frozen=True)
class Exercise:
    id: str
    lab: str
    title: str
    dir: Path
    touches: tuple[str, ...]
    check: str
    observe: str

    @property
    def stub(self) -> Path:
        return self.dir / "stub"


@dataclass(frozen=True)
class Lab:
    id: str
    title: str
    page: Path | None
    exercises: tuple[Exercise, ...]
    hints: tuple[int, ...]  # failed runs needed for hint 1, 2, ...; extra hints use the last number
    solution: int  # failed runs needed for the solution (green unlocks it at once)

    def hint_after(self, k: int) -> int:
        return self.hints[min(k, len(self.hints)) - 1]


@dataclass(frozen=True)
class Result:
    kind: str  # "pass", "fail" (the check ran and is red: counts as a try) or "error" (the check could not run)
    code: int
    output: str


class Labs:
    """Every lab under <repo>/labs/*/lab.toml, in order, plus the state file of this clone."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.state_file = repo / ".tr-lab" / "state.json"
        self.backup_dir = repo / ".tr-lab" / "backup"
        self.labs: list[Lab] = []
        weeks = sorted((repo / "labs").glob("*/lab.toml"), key=lambda p: _key(p.parent.name))
        for toml in weeks:
            config = tomllib.loads(toml.read_text())
            found: dict[str, list[Exercise]] = {}
            for meta_file in sorted((toml.parent / "exercises").glob("*/exercise.toml")):
                m = tomllib.loads(meta_file.read_text())
                ex = Exercise(m["id"], m["lab"], m["title"], meta_file.parent, tuple(m.get("touches", ())),
                              m["check"], m.get("observe", ""))
                found.setdefault(ex.lab, []).append(ex)
            for lab_id in sorted(found, key=_key):
                lab_config = config.get("labs", {}).get(lab_id, {})
                unlock = {**config.get("unlock", {}), **lab_config.get("unlock", {})}
                page = lab_config.get("page")
                self.labs.append(Lab(lab_id, lab_config.get("title", ""), toml.parent / page if page else None,
                                     tuple(sorted(found[lab_id], key=lambda e: _key(e.id))),
                                     tuple(unlock.get("hints", (2, 5))), int(unlock.get("solution", 10))))
        if not self.labs:
            raise LabError(f"no labs found under {repo / 'labs'}")
        self.exercises = {ex.id: ex for lab in self.labs for ex in lab.exercises}
        self.by_id = {lab.id: lab for lab in self.labs}

    # state ------------------------------------------------------------------------------------------------------

    def load(self) -> dict:
        if not self.state_file.exists():
            return {"lab": "", "current": "", "done": [], "assumed": [], "finished": [], "fails": {}}
        return json.loads(self.state_file.read_text())

    def save(self, st: dict) -> None:
        self.state_file.parent.mkdir(exist_ok=True)
        self.state_file.write_text(json.dumps(st, indent=1) + "\n")

    def current(self, st: dict) -> Exercise:
        if not st["current"]:
            if st["lab"]:
                raise LabError(f"lab {st['lab']} is finished; `tr lab list` shows what is next")
            raise LabError(f"no lab started yet: `tr lab start {self.labs[0].id}`")
        return self.exercises[st["current"]]

    # git and files ----------------------------------------------------------------------------------------------

    def git(self, *cmd: str) -> str:
        r = subprocess.run(["git", *cmd], cwd=self.repo, capture_output=True, text=True)
        if r.returncode:
            detail = (r.stderr.strip() or r.stdout.strip()).splitlines()
            why = " / ".join(detail[-3:]) if detail else "(a hook or config refused it, no message)"
            raise LabError(f"git {cmd[0]} failed (exit {r.returncode}): {why}; nothing advanced")
        return r.stdout

    def install_stub(self, ex: Exercise) -> list[str]:
        """Copy the exercise's stub over the repo. Returns the files backed up first: only ones you edited."""
        if not ex.stub.is_dir():
            return []
        stamp = time.strftime("%Y%m%d-%H%M%S")
        saved = []
        for src in sorted(p for p in ex.stub.rglob("*") if p.is_file()):
            rel = src.relative_to(ex.stub)
            dest = self.repo / rel
            if dest.exists() and not filecmp.cmp(src, dest, shallow=False) and self.git("status", "--porcelain", "--", str(rel)):
                backup = self.backup_dir / f"{ex.id}-{stamp}" / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
                saved.append(str(backup.relative_to(self.repo)))
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        return saved

    def apply_solution(self, ex: Exercise) -> list[str]:
        saved = self.install_stub(ex)
        self.git("apply", "--whitespace=nowarn", str(ex.dir / "solution.diff"))
        return saved

    def run(self, command: str) -> subprocess.CompletedProcess:
        argv = shlex.split(command)
        if argv and argv[0] == "python":
            argv[0] = sys.executable  # the interpreter `tr` runs in, so no `uv run` and no activated venv needed
        return subprocess.run(argv, cwd=self.repo, capture_output=True, text=True)

    def check(self, ex: Exercise) -> Result:
        r = self.run(ex.check)
        output = r.stdout + r.stderr
        # pytest: 0 green, 1 a test failed; 2-5 (interrupted, internal, usage, no tests) mean it never judged your code
        kind = "pass" if r.returncode == 0 else "fail" if r.returncode == 1 else "error"
        return Result(kind, r.returncode, output)


def _key(ident: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", ident))


def _say(*lines: str) -> None:
    for line in lines:
        print(line)


def _wrap(text: str, indent: str = "  ") -> str:
    return "\n".join(textwrap.fill(line, WIDTH, initial_indent=indent, subsequent_indent=indent) or indent
                     for line in text.splitlines())


def _teaching(output: str) -> list[str]:
    """The test's own message: the first E lines, without pytest's assert rewrite (which can echo the expected value)."""
    lines = []
    for raw in output.splitlines():
        if not raw.startswith("E "):
            if lines:
                break
            continue
        line = raw[1:].strip()
        if line.startswith(("assert ", "where ", "+  where", "+ ", "- ", "At index", "Full diff", "Use -v")):
            break
        lines.append(line.removeprefix("AssertionError: "))
        if len(lines) == 6:
            break
    return lines or [ln for ln in output.strip().splitlines()[-6:]]


def _tail(output: str) -> list[str]:
    e_lines = [ln[1:].strip() for ln in output.splitlines() if ln.startswith("E ")]
    rest = output.strip().splitlines()
    return (e_lines[:8] or rest[-8:]) + ([rest[-1]] if rest and e_lines else [])


def _unlocks(lab: Lab, fails: int, n_hints: int) -> str:
    parts = []
    for k in range(1, n_hints + 1):
        n = lab.hint_after(k)
        parts.append(f"hint {k} is unlocked (`tr lab hint`)" if fails >= n else f"hint {k} unlocks after {n} failed runs")
    parts.append("the solution is unlocked (`tr lab solution`)" if fails >= lab.solution
                 else f"the solution unlocks after {lab.solution} failed runs or when the check is green")
    return "; ".join(parts)


def _hints(ex: Exercise) -> list[str]:
    path = ex.dir / "hints.md"
    return [h.strip() for h in re.split(r"^## Hint \d+\n", path.read_text(), flags=re.M)[1:]] if path.exists() else []


def _edit_line(labs: Labs, ex: Exercise) -> str:
    if ex.stub.is_dir():
        return f"edit: {', '.join(ex.touches)} (look for TODO({ex.id}))"
    return f"edit: {', '.join(ex.touches)} (no stub for this one: you keep working on your own file)"


def _intro(labs: Labs, ex: Exercise) -> None:
    _say(f"exercise {ex.id}: {ex.title}", _edit_line(labs, ex), "then: tr lab verify")


def _backups(saved: list[str]) -> None:
    if saved:
        _say(f"your edits were saved first: {', '.join(saved)}")


# commands -------------------------------------------------------------------------------------------------------


def cmd_list(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    for lab in labs.labs:
        page = f"  ({lab.page.relative_to(labs.repo)})" if lab.page else ""
        mark = " finished" if lab.id in st["finished"] else ""
        _say(f"{lab.id}  {lab.title}{mark}{page}")
        for ex in lab.exercises:
            status = ("done (reference)" if ex.id in st["assumed"] else "done") if ex.id in st["done"] \
                else "current" if ex.id == st["current"] else "locked"
            _say(f"  {status:<16} {ex.id:<8} {ex.title}")
    if not st["lab"]:
        _say(f"start with: tr lab start {labs.labs[0].id}")
    return 0


def cmd_start(labs: Labs, args: argparse.Namespace) -> int:
    lab = labs.by_id.get(args.lab)
    if lab is None:
        raise LabError(f"unknown lab {args.lab!r}; `tr lab list` shows the labs")
    st = labs.load()
    if st["current"] and not args.force:
        raise LabError(f"lab {st['lab']} is in progress at {st['current']}; finish it with `tr lab next`, "
                       f"or pass --force to start {lab.id} anyway (your commits on `lab` stay)")
    index = labs.labs.index(lab)
    missing = [p for p in labs.labs[:index] if p.id not in st["finished"]]
    if missing and not args.assume_previous:
        raise LabError(f"lab {lab.id} builds on {missing[-1].id}, which is not finished. Finish it first "
                       f"(`tr lab start {missing[0].id}`), or pass --assume-previous to apply the reference solutions "
                       f"of every earlier exercise and start {lab.id} on top of them")
    branch = labs.git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch != "lab":
        if labs.git("branch", "--list", "lab").strip() and not args.force:
            raise LabError("a branch `lab` already exists and you are not on it; `git checkout lab` to continue there, "
                           "or pass --force to recreate it from your current commit")
        labs.git("checkout", "-q", "-B", "lab")
    saved: list[str] = []
    if missing:
        applied = [ex for p in missing for ex in p.exercises]
        for ex in applied:
            saved += labs.apply_solution(ex)
        labs.git("add", "-A")
        labs.git("commit", "-q", "--allow-empty", "-m", f"lab: reference solutions {applied[0].id}..{applied[-1].id} (--assume-previous)")
        st["done"] = [e for e in st["done"] if e not in {ex.id for ex in applied}] + [ex.id for ex in applied]
        st["assumed"] = sorted(set(st["assumed"]) | {ex.id for ex in applied}, key=_key)
        st["finished"] = sorted(set(st["finished"]) | {p.id for p in missing}, key=_key)
        _say(f"--assume-previous: applied the reference solutions of {applied[0].id}..{applied[-1].id} "
             f"and committed them on `lab`")
    first = lab.exercises[0]
    restart = {ex.id for ex in lab.exercises}
    st["done"] = [e for e in st["done"] if e not in restart]
    st["finished"] = [p for p in st["finished"] if p != lab.id]
    st["fails"] = {k: v for k, v in st["fails"].items() if k not in restart}
    st.pop("passed", None)
    st.update(lab=lab.id, current=first.id)
    saved += labs.install_stub(first)
    labs.save(st)
    page = f"; read {lab.page.relative_to(labs.repo)}" if lab.page else ""
    _say(f"started lab {lab.id} ({lab.title}) on branch `lab`{page}")
    _backups(saved)
    _intro(labs, first)
    return 0


def _verify_one(labs: Labs, st: dict, ex: Exercise, verbose: bool, counted: bool) -> int:
    lab = labs.by_id[ex.lab]
    res = labs.check(ex)
    if verbose:
        _say(res.output.rstrip())
    if res.kind == "error":
        if counted:
            st.pop("passed", None)
            labs.save(st)
        _say(f"ERROR {ex.id}: the check could not run (pytest exit {res.code}), so this is not counted as a try:",
             *(_wrap(ln) for ln in _tail(res.output)),
             "  a syntax or import error in the files you edited is the usual cause; `tr lab verify -v` shows everything")
        return 1
    if res.kind == "fail":
        if counted:
            fails = st["fails"].get(ex.id, 0) + 1
            st["fails"][ex.id] = fails
            st.pop("passed", None)
            labs.save(st)
            _say(f"FAIL {ex.id} (try {fails}): {ex.title}")
        else:
            _say(f"FAIL {ex.id} (an earlier exercise, not counted): {ex.title}")
        _say(*(_wrap(ln) for ln in _teaching(res.output)))
        if counted:
            _say(_wrap(_unlocks(lab, fails, len(_hints(ex)))))
        return 1
    if counted:
        st["passed"] = ex.id
        labs.save(st)
    _say(f"PASS {ex.id}: {ex.title}")
    if ex.observe:
        obs = labs.run(ex.observe)
        _say(f"observe: {ex.observe}", *(_wrap(ln, "  | ") for ln in (obs.stdout + obs.stderr).rstrip().splitlines()))
        if obs.returncode:
            _say(f"  (observe exited {obs.returncode}; it never decides the exercise)")
    if counted:
        _say("next: `tr lab next` commits it and moves on; `tr lab solution` shows the reference to compare")
    return 0


def cmd_verify(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    target = args.target
    if target is None:
        return _verify_one(labs, st, labs.current(st), args.verbose, counted=True)
    reached = set(st["done"]) | ({st["current"]} if st["current"] else set())
    if target in labs.exercises:
        if target not in reached:
            _say(f"{target} not reached yet (current: {st['current'] or 'none'}); `tr lab list` shows the order")
            return 2
        return _verify_one(labs, st, labs.exercises[target], args.verbose, counted=target == st["current"])
    if target in labs.by_id:
        todo = [ex for ex in labs.by_id[target].exercises if ex.id in reached]
        if not todo:
            _say(f"lab {target} not reached yet; `tr lab list` shows the order")
            return 2
        green = 0
        for ex in todo:
            res = labs.check(ex)
            if args.verbose:
                _say(res.output.rstrip())
            word = {"pass": "PASS ", "fail": "FAIL ", "error": "ERROR"}[res.kind]
            first = "" if res.kind == "pass" else ": " + (_teaching(res.output) if res.kind == "fail" else _tail(res.output))[0]
            line = f"{word} {ex.id:<8} {ex.title}{first}"
            _say(line if len(line) <= WIDTH + 20 else line[:WIDTH + 16] + " ...")
            green += res.kind == "pass"
        _say(f"{target}: {green} of {len(todo)} reached exercises green"
             + ("" if green == len(todo) else "; `tr lab verify <id>` shows one in full"))
        return 0 if green == len(todo) else 1
    raise LabError(f"unknown exercise or lab {target!r}; `tr lab list` shows them")


def cmd_next(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    ex = labs.current(st)
    res = labs.check(ex)
    if res.kind != "pass":
        st.pop("passed", None)
        labs.save(st)
        why = "is red" if res.kind == "fail" else f"could not run (pytest exit {res.code})"
        raise LabError(f"the check of {ex.id} {why} on your current files, so `next` stays here; `tr lab verify` shows why")
    lab = labs.by_id[ex.lab]
    last = ex is lab.exercises[-1]
    if last:
        suite = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=labs.repo,
                               capture_output=True, text=True)
        if suite.returncode:
            lines = (suite.stdout + suite.stderr).strip().splitlines()
            failing = [ln for ln in lines if ln.startswith(("FAILED", "ERROR"))][:8]
            raise LabError("\n".join([f"{ex.id} is green, but the repo's own tests are red, and a lab ends with them green:",
                                      *("  " + ln for ln in failing + lines[-1:]),
                                      "  `python -m pytest -q` shows them; fix them, then `tr lab next` again"]))
    labs.git("add", "-A")
    labs.git("commit", "-q", "--allow-empty", "-m", f"lab {ex.id}: green")
    st["done"].append(ex.id)
    st.pop("passed", None)
    if last:
        st["current"] = ""
        st["finished"].append(lab.id)
        labs.save(st)
        after = labs.labs.index(lab) + 1
        _say(f"committed `lab {ex.id}: green`",
             f"lab {lab.id} finished; tr lab start {labs.labs[after].id}" if after < len(labs.labs)
             else f"lab {lab.id} finished; that was the last lab")
        return 0
    nxt = lab.exercises[lab.exercises.index(ex) + 1]
    st["current"] = nxt.id
    labs.save(st)
    saved = labs.install_stub(nxt)
    _say(f"committed `lab {ex.id}: green`")
    _backups(saved)
    _intro(labs, nxt)
    return 0


def cmd_hint(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    ex = labs.current(st)
    lab = labs.by_id[ex.lab]
    fails = st["fails"].get(ex.id, 0)
    hints = _hints(ex)
    open_ = [h for k, h in enumerate(hints, 1) if fails >= lab.hint_after(k)]
    if not hints:
        raise LabError(f"{ex.id} has no hints")
    if not open_:
        raise LabError(f"hint 1 unlocks after {lab.hint_after(1)} failed runs of `tr lab verify` (you have {fails}); "
                       "read the FAIL message once more first")
    for k, h in enumerate(open_, 1):
        _say(f"hint {k} of {len(hints)} ({ex.id}):", textwrap.indent(h, "  "), "")
    if len(open_) < len(hints):
        k = len(open_) + 1
        _say(f"hint {k} unlocks after {lab.hint_after(k)} failed runs (you have {fails})")
    return 0


def cmd_solution(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    ex = labs.current(st)
    lab = labs.by_id[ex.lab]
    fails = st["fails"].get(ex.id, 0)
    if st.get("passed") != ex.id and fails < lab.solution:
        raise LabError(f"the solution of {ex.id} unlocks after {lab.solution} failed runs or when the check is green "
                       f"(you have {fails} failed runs)")
    if not args.apply:
        _say((ex.dir / "solution.diff").read_text().rstrip(),
             "", "`tr lab solution --apply` puts it in your files (your edits are backed up first)")
        return 0
    try:
        saved = labs.apply_solution(ex)
    except LabError as err:
        raise LabError(f"{err}. The reference diff did not fit your files"
                       + ("" if ex.stub.is_dir() else " (this exercise has no stub: the diff expects the reference "
                          "versions of the earlier exercises' files)")) from None
    _backups(saved)
    _say(f"applied the reference solution of {ex.id}; run `tr lab verify`")
    return 0


def cmd_reset(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    ex = labs.current(st)
    saved = labs.install_stub(ex)
    st["fails"][ex.id] = 0
    st.pop("passed", None)
    labs.save(st)
    if ex.stub.is_dir():
        _say(f"reset {ex.id}: stub restored, failed runs back to 0")
    else:
        _say(f"{ex.id} has no stub (you work on your own {', '.join(ex.touches)}); nothing restored, failed runs back to 0")
    _backups(saved)
    return 0


def cmd_status(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    _say(json.dumps({k: st.get(k) for k in ("lab", "current", "done", "assumed", "finished", "fails", "passed")}))
    return 0


COMMANDS = {"list": cmd_list, "start": cmd_start, "verify": cmd_verify, "next": cmd_next, "hint": cmd_hint,
            "solution": cmd_solution, "reset": cmd_reset, "status": cmd_status}


HELP = "the week labs, checked locally (no keys, no model calls); see labs/README.md"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tr lab", description=HELP)
    cmds = p.add_subparsers(dest="lab_command", required=True)
    cmds.add_parser("list", help="every lab and exercise: done, current or locked")
    q = cmds.add_parser("start", help="begin a lab on branch `lab` and install its first stub")
    q.add_argument("lab", help="lab id, e.g. w1l1")
    q.add_argument("--force", action="store_true", help="start even though another lab is in progress")
    q.add_argument("--assume-previous", action="store_true",
                   help="apply the reference solutions of the earlier, unfinished labs first")
    q = cmds.add_parser("verify", help="run a check: the current exercise, one exercise id, or a lab id")
    q.add_argument("target", nargs="?", help="exercise id (w1l1.2) or lab id (w1l1); default: the current exercise")
    q.add_argument("-v", "--verbose", action="store_true", help="also print pytest's full output")
    cmds.add_parser("next", help="re-check, commit the green exercise, install the next stub")
    cmds.add_parser("hint", help="the hints unlocked so far")
    q = cmds.add_parser("solution", help="the reference diff, once unlocked")
    q.add_argument("--apply", action="store_true", help="put the reference into your files")
    cmds.add_parser("reset", help="restore the current stub and zero its failed runs")
    cmds.add_parser("status", help="the state as one JSON line")
    return p


def main(argv: list[str]) -> int:
    """`tr lab <argv>`. Imports nothing a lab stub overwrites, so it runs while your edits are broken."""
    args = parser().parse_args(argv)
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode:
            raise LabError("not inside a git repository: run `tr lab` from your tradingresearch clone")
        labs = Labs(Path(top.stdout.strip()))
        return COMMANDS[args.lab_command](labs, args)
    except LabError as err:
        print(err, file=sys.stderr)
        return 2

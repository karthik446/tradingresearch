"""`tr lab`: the week labs, run and checked on your own machine. No keys, no model calls, no network.

A lab is a short run of exercises (labs/<week>/exercises/<id>-<slug>/). Each exercise ships a stub (the repo files with a
TODO cut out), a check (a pytest file), hints, a reference solution diff and an observe command. `tr lab` installs the
stub, runs the check, counts failed runs to unlock hints and the solution, and commits each green exercise on the branch
`lab`. State lives in .tr-lab/state.json (gitignored). A stub is the reference state of the earlier exercises plus one
TODO, not your own file: before it overwrites a file that holds your work (uncommitted edits, or the version a
`lab <id>: green` commit holds) the file is copied to .tr-lab/backup/, and a committed version also stays in git.
A week whose lab.toml names a `base` (a tag, e.g. week-2-start) starts from the author's code there: the first `start` of
that week makes the tree equal to the tag's, except the runner's own paths, and commits it on `lab`.
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
LAB_COMMIT = re.compile(r"lab (w\d+l\d+\.\d+): green")
WIDTH = 100
# paths the runner owns: a week's base never replaces or deletes them
RUNNER_DIRS = ("labs/", ".tr-lab/")
RUNNER_FILES = frozenset({"src/tradingresearch/lab.py", "src/tradingresearch/labmain.py", "tests/test_lab.py"})
# the runner's lines in pyproject.toml and .gitignore, re-applied to a week's base
AUTHOR_SCRIPT = 'tr = "tradingresearch.cli:main"'
LAB_SCRIPT = 'tr = "tradingresearch.labmain:main"'
AUTHOR_ADDOPTS = "addopts = \"-m 'not live'\""
LAB_ADDOPTS = "addopts = \"-m 'not live and not lab'\""
TESTPATHS = 'testpaths = ["tests"]'
LAB_MARKER = '    "lab: a lab exercise check under labs/ (run by `tr lab verify`, which passes -m lab)",'
LAB_IGNORE = ("# the labs ship their recorded runs (labs/<week>/data/); `tr lab` keeps its state out of git",
              "!labs/**/data/", ".tr-lab/")


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
    observe_ok_exit: tuple[int, ...] = (0,)  # observe exit codes that are no news (`git diff --no-index` exits 1)

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
    week: str  # the folder under labs/, e.g. "w1"
    deselect: tuple[str, ...] = ()  # pytest node ids the repo-suite gate at the end of this lab leaves out

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
        self.bases: dict[str, str] = {}  # week -> the tag its labs start from
        weeks = sorted((repo / "labs").glob("*/lab.toml"), key=lambda p: _key(p.parent.name))
        for toml in weeks:
            config = tomllib.loads(toml.read_text())
            if "base" in config:
                self.bases[toml.parent.name] = str(config["base"])
            found: dict[str, list[Exercise]] = {}
            for meta_file in sorted((toml.parent / "exercises").glob("*/exercise.toml")):
                m = tomllib.loads(meta_file.read_text())
                ex = Exercise(m["id"], m["lab"], m["title"], meta_file.parent, tuple(m.get("touches", ())),
                              m["check"], m.get("observe", ""), tuple(m.get("observe_ok_exit", (0,))))
                found.setdefault(ex.lab, []).append(ex)
            for lab_id in sorted(found, key=_key):
                lab_config = config.get("labs", {}).get(lab_id, {})
                unlock = {**config.get("unlock", {}), **lab_config.get("unlock", {})}
                page = lab_config.get("page")
                self.labs.append(Lab(lab_id, lab_config.get("title", ""), toml.parent / page if page else None,
                                     tuple(sorted(found[lab_id], key=lambda e: _key(e.id))),
                                     tuple(unlock.get("hints", (2, 5))), int(unlock.get("solution", 10)),
                                     toml.parent.name,
                                     tuple(config.get("suite", {}).get("deselect", ()))
                                     + tuple(lab_config.get("suite", {}).get("deselect", ()))))
        if not self.labs:
            raise LabError(f"no labs found under {repo / 'labs'}")
        self.exercises = {ex.id: ex for lab in self.labs for ex in lab.exercises}
        self.by_id = {lab.id: lab for lab in self.labs}

    def builds_on(self, lab: Lab) -> list[Lab]:
        """The earlier labs `lab` needs: every one before it, back to the first lab of the latest week with a base."""
        week = _key(lab.week)[0]
        start = max((_key(w)[0] for w in self.bases if _key(w)[0] <= week), default=0)
        return [p for p in self.labs[:self.labs.index(lab)] if _key(p.week)[0] >= start]

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

    def show(self, ref: str, path: str) -> str | None:
        r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=self.repo, capture_output=True, text=True)
        return None if r.returncode else r.stdout

    def uncommitted(self) -> list[str]:
        """Changed and untracked paths outside .tr-lab/."""
        lines = self.git("status", "--porcelain", "--untracked-files=normal").splitlines()
        return [ln[3:] for ln in lines if not ln[3:].strip('"').startswith(".tr-lab/")]

    def apply_base(self, week: str) -> list[str]:
        """Make the tree equal to the week's base, runner paths excepted, and commit it. Returns the lines to print.

        The base's pyproject.toml and .gitignore get the runner's lines back (checked before any file changes). Files
        tracked now and absent from the base are removed; untracked and ignored files are left alone.
        """
        tag, n = self.bases[week], _key(week)[0]
        if subprocess.run(["git", "rev-parse", "-q", "--verify", f"{tag}^{{commit}}"], cwd=self.repo,
                          capture_output=True).returncode:
            raise LabError(f"week {n} starts from the tag {tag}, which this clone does not have; "
                           "`git fetch --tags` gets it")
        pyproject = self.show(tag, "pyproject.toml")
        if pyproject is None:
            raise LabError(f"pyproject.toml is missing at {tag}; `tr lab` re-applies its lines there, so nothing changed")
        pyproject = _lab_pyproject(pyproject, tag)
        gitignore = _lab_gitignore(self.show(tag, ".gitignore") or "")
        theirs = [p for p in self.git("ls-tree", "-r", "-z", "--name-only", tag).split("\0") if p and not _runner(p)]
        keep = set(theirs)
        gone = [p for p in self.git("ls-files", "-z").split("\0") if p and not _runner(p) and p not in keep]
        if theirs:
            self.git("checkout", tag, "--", *(f":(literal){p}" for p in theirs))
        if gone:
            self.git("rm", "-q", "--", *(f":(literal){p}" for p in gone))
        (self.repo / "pyproject.toml").write_text(pyproject)
        (self.repo / ".gitignore").write_text(gitignore)
        self.git("add", "--", "pyproject.toml", ".gitignore")
        changed = [p for p in self.git("diff", "--cached", "--name-only", "-z", "HEAD").split("\0") if p]
        subject = f"lab: week {n} base ({tag})"
        self.git("commit", "-q", "--allow-empty", "-m", subject)
        lines = [f"week {n} starts from the author's code at {tag}: {len(changed)} files changed, committed as "
                 f"`{subject}`", "your earlier commits stay in the history of `lab`"]
        if {"pyproject.toml", "uv.lock"} & set(changed):
            lines.append("pyproject.toml or uv.lock changed: run `uv sync` now")
        return lines

    def install_stub(self, ex: Exercise, current: Exercise | None, written: set[str] | None = None) -> list[str]:
        """Copy the exercise's stub over the repo. Returns one line per file copied to .tr-lab/backup/ first.

        A file is backed up when it differs from the new stub and holds your work: uncommitted edits, or the version a
        `lab <id>: green` commit holds. Not backed up: a file byte-equal to `current`'s stub (the runner put it there)
        or one this same command already wrote (`written`, e.g. the reference solutions of --assume-previous).
        """
        if not ex.stub.is_dir():
            return []
        folder = self.backup_dir / f"{ex.id}-{time.strftime('%Y%m%d-%H%M%S')}"
        said = []
        for src in sorted(p for p in ex.stub.rglob("*") if p.is_file()):
            rel = src.relative_to(ex.stub)
            dest = self.repo / rel
            ours = written is not None and str(rel) in written or current is not None and _same(current.stub / rel, dest)
            if dest.exists() and not _same(src, dest) and not ours:
                line = self._yours(ex, str(rel), folder / rel)
                if line:
                    (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, folder / rel)
                    said.append(line)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            if written is not None:
                written.add(str(rel))
        return said

    def _yours(self, ex: Exercise, rel: str, backup: Path) -> str | None:
        """What the learner would lose if the stub of `ex` overwrote `rel`, or None when it is not their work."""
        where = backup.relative_to(self.repo)
        if self.git("status", "--porcelain", "--", rel):
            return f"saved your uncommitted edits to {rel} in {where} before {ex.id} replaced it"
        sha, _, subject = self.git("log", "-1", "--format=%h %s", "--", rel).strip().partition(" ")
        done = LAB_COMMIT.fullmatch(subject)
        if done is None:  # the file as the repo shipped it, or a reference solution from --assume-previous
            return None
        return (f"{ex.id} starts from the reference version of {done[1]} in {rel}; your version is in commit {sha} "
                f"(`{subject}`) and in {where}")

    def apply_solution(self, ex: Exercise, current: Exercise | None, written: set[str] | None = None) -> list[str]:
        said = self.install_stub(ex, current, written)
        diff = ex.dir / "solution.diff"
        self.git("apply", "--whitespace=nowarn", str(diff))
        if written is not None:
            written.update(re.findall(r"^\+\+\+ b/(\S+)", diff.read_text(), flags=re.M))
        return said

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


def _same(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)


def _runner(path: str) -> bool:
    return path.startswith(RUNNER_DIRS) or path in RUNNER_FILES


def _lab_pyproject(text: str, tag: str) -> str:
    """A base's pyproject.toml with the runner's lines: `tr` through labmain, the `lab` marker deselected. Idempotent."""
    lines = text.splitlines()

    def need(found: bool, what: str) -> None:
        if not found:
            raise LabError(f"pyproject.toml at {tag} has no {what}; `tr lab` re-applies its own lines there and "
                           "cannot, so nothing changed")

    if LAB_SCRIPT not in lines:
        need(AUTHOR_SCRIPT in lines, f"line `{AUTHOR_SCRIPT}`")
        lines[lines.index(AUTHOR_SCRIPT)] = LAB_SCRIPT
    need("[tool.pytest.ini_options]" in lines, "table [tool.pytest.ini_options]")
    start = lines.index("[tool.pytest.ini_options]") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    section = lines[start:end]
    if LAB_ADDOPTS not in section:
        need(AUTHOR_ADDOPTS in section, f"line `{AUTHOR_ADDOPTS}` in [tool.pytest.ini_options]")
        lines[start + section.index(AUTHOR_ADDOPTS)] = LAB_ADDOPTS
    testpaths = [ln for ln in section if ln.startswith("testpaths")]
    need(testpaths in ([], [TESTPATHS]), f"other testpaths than `{TESTPATHS}`")
    need("markers = [" in section, "line `markers = [` in [tool.pytest.ini_options]")
    opened = start + section.index("markers = [")
    closed = next((i for i in range(opened + 1, end) if lines[i].strip() == "]"), None)
    need(closed is not None, "closing `]` of its markers list")
    if not any(ln.strip().startswith('"lab:') for ln in lines[opened + 1:closed]):
        lines.insert(closed, LAB_MARKER)
    if not testpaths:
        lines.insert(start, TESTPATHS)
    return "\n".join(lines) + "\n"


def _lab_gitignore(text: str) -> str:
    lines = text.splitlines()
    missing = [ln for ln in LAB_IGNORE[1:] if ln not in lines]
    if not missing:
        return text
    return "\n".join([*lines, *([""] if lines and lines[-1] else []), LAB_IGNORE[0], *missing]) + "\n"


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


def _committed(labs: Labs, ex: Exercise) -> list[str]:
    """The files the `lab <id>: green` commit at HEAD holds, and a note on changed files outside the exercise's."""
    changes = [ln.split("\t") for ln in labs.git("show", "--name-status", "--format=", "HEAD").splitlines() if ln]
    lines = [f"committed `lab {ex.id}: green`: {', '.join(c[-1] for c in changes) or 'no file changes'}"]
    outside = [c[-1] for c in changes if c[0] != "A" and c[-1] not in ex.touches]
    if outside:
        lines.append(f"note: {', '.join(outside)} changed too, outside {ex.id}'s files ({', '.join(ex.touches)}); "
                     "`tr lab next` commits every change, `git show --stat HEAD` shows this commit")
    return lines


# commands -------------------------------------------------------------------------------------------------------


def cmd_list(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    up_next = None if st["current"] else next((lab for lab in labs.labs if lab.id not in st["finished"]), None)
    week = None

    def open_lab(lab: Lab) -> bool:  # unfinished, and everything it builds on is finished (a week with a base starts afresh)
        return not st["current"] and lab.id not in st["finished"] and all(p.id in st["finished"] for p in labs.builds_on(lab))

    for lab in labs.labs:
        if lab.week != week:
            week, base = lab.week, labs.bases.get(lab.week)
            _say(f"week {_key(week)[0]}" + (f" (starts from {base})" if base else ""))
        page = f"  ({lab.page.relative_to(labs.repo)})" if lab.page else ""
        mark = ": finished" if lab.id in st["finished"] else ""
        _say(f"{lab.id}  {lab.title}{mark}{page}")
        for ex in lab.exercises:
            status = ("done (reference)" if ex.id in st["assumed"] else "done") if ex.id in st["done"] \
                else "current" if ex.id == st["current"] \
                else "start here" if open_lab(lab) and ex is lab.exercises[0] else "locked"
            _say(f"  {status:<16} {ex.id:<8} {ex.title}")
    if up_next is not None:
        _say(f"start with: tr lab start {up_next.id}")
    return 0


def cmd_start(labs: Labs, args: argparse.Namespace) -> int:
    lab = labs.by_id.get(args.lab)
    if lab is None:
        raise LabError(f"unknown lab {args.lab!r}; `tr lab list` shows the labs")
    st = labs.load()
    if st["current"] and not args.force:
        raise LabError(f"lab {st['lab']} is in progress at {st['current']}; finish it with `tr lab next`, "
                       f"or pass --force to start {lab.id} anyway (your commits on `lab` stay)")
    missing = [p for p in labs.builds_on(lab) if p.id not in st["finished"]]
    if missing and not args.assume_previous:
        raise LabError(f"lab {lab.id} builds on {missing[-1].id}, which is not finished. Finish it first "
                       f"(`tr lab start {missing[0].id}`), or pass --assume-previous to apply the reference solutions "
                       f"of the earlier exercises it builds on and start {lab.id} on top of them")
    branch = labs.git("rev-parse", "--abbrev-ref", "HEAD").strip()
    fresh = branch != "lab"
    if fresh and labs.git("branch", "--list", "lab").strip() and not args.force:
        raise LabError("a branch `lab` already exists and you are not on it; `git checkout lab` to continue there, "
                       "or pass --force to recreate it from your current commit")
    bases = [] if fresh else st.get("bases", [])  # a base is applied once per `lab` branch
    base = labs.bases.get(lab.week) if lab.week not in bases else None
    if base:
        dirty = labs.uncommitted()
        if dirty:
            raise LabError(f"you have uncommitted changes ({', '.join(dirty[:5])}{', ...' if len(dirty) > 5 else ''}): "
                           f"commit or stash first; week {_key(lab.week)[0]} starts from the author's code at {base} "
                           "and replaces files")
    if fresh:
        labs.git("checkout", "-q", "-B", "lab")
    st["bases"] = bases
    if base:
        _say(*labs.apply_base(lab.week))
        st["bases"] = [*bases, lab.week]
        labs.save(st)
    said: list[str] = []
    current = labs.exercises.get(st["current"])
    written: set[str] = set()
    if missing:
        applied = [ex for p in missing for ex in p.exercises]
        for ex in applied:
            said += labs.apply_solution(ex, current, written)
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
    st["assumed"] = [e for e in st["assumed"] if e not in restart]
    st.pop("passed", None)
    st.update(lab=lab.id, current=first.id)
    said += labs.install_stub(first, current, written)
    labs.save(st)
    page = f"; read {lab.page.relative_to(labs.repo)}" if lab.page else ""
    _say(f"started lab {lab.id} ({lab.title}) on branch `lab`{page}")
    _say(*said)
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
        hint = ("  pytest collected no tests: check the exercise's check command" if res.code == 5 else
                "  a syntax or import error in the files you edited is the usual cause; `tr lab verify -v` shows everything")
        _say(f"ERROR {ex.id}: the check could not run (pytest exit {res.code}), so this is not counted as a try:",
             *(_wrap(ln) for ln in _tail(res.output)), hint)
        return 3
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
        if obs.returncode not in ex.observe_ok_exit:
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
        skip = [arg for node in lab.deselect for arg in ("--deselect", node)]
        suite = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *skip], cwd=labs.repo,
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
        _say(*_committed(labs, ex),
             f"lab {lab.id} finished; tr lab start {labs.labs[after].id}" if after < len(labs.labs)
             else f"lab {lab.id} finished; that was the last lab")
        return 0
    nxt = lab.exercises[lab.exercises.index(ex) + 1]
    st["current"] = nxt.id
    labs.save(st)
    said = labs.install_stub(nxt, ex)
    _say(*_committed(labs, ex), *said)
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
                       "until then, the FAIL message is the hint: it names what the check expected and what it got")
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
        said = labs.apply_solution(ex, ex)
    except LabError as err:
        raise LabError(f"{err}. The reference diff did not fit your files"
                       + ("" if ex.stub.is_dir() else " (this exercise has no stub: the diff expects the reference "
                          "versions of the earlier exercises' files)")) from None
    _say(*said)
    _say(f"applied the reference solution of {ex.id}; run `tr lab verify`")
    return 0


def cmd_reset(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    ex = labs.current(st)
    said = labs.install_stub(ex, ex)
    st["fails"][ex.id] = 0
    st.pop("passed", None)
    labs.save(st)
    if ex.stub.is_dir():
        _say(f"reset {ex.id}: stub restored, failed runs back to 0")
    else:
        _say(f"{ex.id} has no stub (you work on your own {', '.join(ex.touches)}); nothing restored, failed runs back to 0")
    _say(*said)
    return 0


def cmd_status(labs: Labs, args: argparse.Namespace) -> int:
    st = labs.load()
    lab = labs.by_id.get(st["lab"])
    shown = {k: st.get(k) for k in ("lab", "current", "done", "assumed", "finished", "fails", "passed")}
    _say(json.dumps({**shown, "base": labs.bases.get(lab.week) if lab else None, "bases": st.get("bases", [])}))
    return 0


COMMANDS = {"list": cmd_list, "start": cmd_start, "verify": cmd_verify, "next": cmd_next, "hint": cmd_hint,
            "solution": cmd_solution, "reset": cmd_reset, "status": cmd_status}


HELP = "the week labs, checked locally (no keys, no model calls); see labs/README.md"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tr lab", description=HELP)
    cmds = p.add_subparsers(dest="lab_command", required=True)
    cmds.add_parser("list", help="every lab and exercise: done, current, start here or locked")
    q = cmds.add_parser("start", help="begin a lab on branch `lab` and install its first stub (a week with a base "
                                      "first brings in the author's code at that week's tag)")
    q.add_argument("lab", help="lab id, e.g. w1l1")
    q.add_argument("--force", action="store_true", help="start even though another lab is in progress")
    q.add_argument("--assume-previous", action="store_true",
                   help="apply the reference solutions of the earlier, unfinished labs first (within the week when "
                        "the week has a base)")
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

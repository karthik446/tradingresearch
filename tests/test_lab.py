"""`tr lab` on a fake repo: the state machine, refusals, unlocks, backups, verify targets, --assume-previous, week bases."""

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tradingresearch import lab
from tradingresearch.labmain import main

REAL_CONFTEST = Path(__file__).resolve().parents[1] / "labs" / "w1" / "conftest.py"
CHECK = """\
import sys
from pathlib import Path

path, want = Path(sys.argv[1]), sys.argv[2]
got = (path.read_text().splitlines() or [""])[0] if path.exists() else None
if got != want:
    print(f"E   AssertionError: {path} holds {got!r}, which is not the answer")
    sys.exit(1)
"""


def diff(path: str, old: list[str], new: list[str]) -> str:
    body = [f"-{x}" for x in old if x not in new] + [f"{' ' if x in old else '+'}{x}" for x in new]
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,{len(old)} +1,{len(new)} @@\n" + "\n".join(body) + "\n"


def exercise(root: Path, name: str, toml: str, files: dict[str, str], week: str = "w1") -> None:
    ex = root / "labs" / week / "exercises" / name
    for rel, text in {"exercise.toml": textwrap.dedent(toml), **files}.items():
        (ex / rel).parent.mkdir(parents=True, exist_ok=True)
        (ex / rel).write_text(text)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    """w1l1 = w1l1.1 (stub, script check, 3 hints) + w1l1.2 (no stub, a real pytest check); w1l2 = w1l2.1 (stub)."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / ".gitignore").write_text(".tr-lab/\n")
    (root / "pyproject.toml").write_text(textwrap.dedent("""\
        [tool.pytest.ini_options]
        testpaths = ["tests"]
        markers = ["lab: a lab check"]
        addopts = "-m 'not lab'"
        """))
    (root / "tests" / "test_suite.py").write_text(
        "from pathlib import Path\n\ndef test_suite():\n    assert not Path('suite_red').exists()\n")
    (root / "answer.txt").write_text("start\n")
    (root / "labs" / "w1").mkdir(parents=True)
    (root / "labs" / "w1" / "conftest.py").write_text(REAL_CONFTEST.read_text())
    (root / "labs" / "w1" / "check.py").write_text(CHECK)
    (root / "labs" / "w1" / "lab.toml").write_text(textwrap.dedent("""\
        [unlock]
        hints = [2, 5]
        solution = 10

        [labs.w1l1]
        title = "first"

        [labs.w1l2]
        title = "second"
        """))
    hints = "# Hints\n\n## Hint 1\n\nfirst hint\n\n## Hint 2\n\nsecond hint\n\n## Hint 3\n\nthird hint\n"
    exercise(root, "w1l1.1-one", """\
        id = "w1l1.1"
        title = "write the answer"
        lab = "w1l1"
        touches = ["answer.txt"]
        check = "python labs/w1/check.py answer.txt 42"
        observe = "python -c \\"print('observed it')\\""
        """, {"stub/answer.txt": "TODO(w1l1.1)\n", "hints.md": hints,
              "solution.diff": diff("answer.txt", ["TODO(w1l1.1)"], ["42"])})
    exercise(root, "w1l1.2-own", """\
        id = "w1l1.2"
        title = "add a second line"
        lab = "w1l1"
        touches = ["answer.txt"]
        check = "python -m pytest -q -x -p no:cacheprovider -m lab labs/w1/exercises/w1l1.2-own/test_w1l1_2.py"
        observe = ""
        """, {"test_w1l1_2.py": "from pathlib import Path\n\ndef test_second_line():\n"
                                "    assert Path('answer.txt').read_text() == '42\\n43\\n', 'answer.txt needs 43 below 42'\n",
              "hints.md": hints, "solution.diff": diff("answer.txt", ["42"], ["42", "43"])})
    exercise(root, "w1l2.1-two", """\
        id = "w1l2.1"
        title = "the second file"
        lab = "w1l2"
        touches = ["second.txt"]
        check = "python labs/w1/check.py second.txt 7"
        """, {"stub/second.txt": "TODO(w1l2.1)\n", "hints.md": hints,
              "solution.diff": diff("second.txt", ["TODO(w1l2.1)"], ["7"])})
    for name, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(name, value)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "start")
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def tr(capsys):
    def run(*args: str) -> tuple[int, str]:
        with pytest.raises(SystemExit) as exit_:
            main(["lab", *args])
        out = capsys.readouterr()
        return exit_.value.code, out.out + out.err
    return run


def state(repo: Path) -> dict:
    return json.loads((repo / ".tr-lab" / "state.json").read_text())


def set_state(repo: Path, **changes) -> None:
    (repo / ".tr-lab" / "state.json").write_text(json.dumps({**state(repo), **changes}))


def solve(repo: Path, ex: str) -> None:
    folder = next((repo / "labs" / ex.split("l")[0] / "exercises").glob(f"{ex}-*"))
    git(repo, "apply", str(folder / "solution.diff"))


def test_start_verify_next_walks_the_lab_and_commits_each_green_exercise(repo, tr):
    code, out = tr("list")
    assert code == 0 and "start here       w1l1.1" in out and "tr lab start w1l1" in out
    code, out = tr("start", "w1l1")
    assert code == 0 and "edit: answer.txt (look for TODO(w1l1.1))" in out
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "lab"
    assert (repo / "answer.txt").read_text() == "TODO(w1l1.1)\n"
    code, out = tr("verify")
    assert code == 1 and "FAIL w1l1.1 (try 1)" in out and "which is not the answer" in out
    solve(repo, "w1l1.1")
    code, out = tr("verify")
    assert code == 0 and "PASS w1l1.1" in out and "observed it" in out and "tr lab solution" in out
    code, out = tr("next")
    assert code == 0 and "exercise w1l1.2" in out and "no stub" in out
    assert git(repo, "log", "-1", "--format=%s").strip() == "lab w1l1.1: green"
    assert "committed `lab w1l1.1: green`: answer.txt" in out and "note:" not in out
    assert state(repo)["current"] == "w1l1.2" and state(repo)["done"] == ["w1l1.1"]
    code, out = tr("list")
    assert "done             w1l1.1" in out and "current          w1l1.2" in out and "locked           w1l2.1" in out


def test_next_refuses_on_red_and_clears_a_stale_pass(repo, tr):
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    assert tr("verify")[0] == 0 and state(repo)["passed"] == "w1l1.1"
    (repo / "answer.txt").write_text("41\n")
    code, out = tr("next")
    assert code == 2 and "stays here" in out
    assert "passed" not in state(repo) and state(repo)["current"] == "w1l1.1"
    assert git(repo, "log", "-1", "--format=%s").strip() == "start"


@pytest.mark.parametrize(("hook", "shown"), [("exit 1", "a hook or config refused it, no message"),
                                              ("echo 'commit blocked by policy' >&2; exit 1", "commit blocked by policy")])
def test_next_stops_on_a_failing_commit_hook_with_the_state_unchanged(repo, tr, hook, shown):
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    hook_file = repo / ".git" / "hooks" / "pre-commit"
    hook_file.write_text(f"#!/bin/sh\n{hook}\n")
    hook_file.chmod(0o755)
    before = state(repo)
    code, out = tr("next")
    assert code == 2 and "git commit failed" in out and shown in out and "nothing advanced" in out
    assert state(repo) == before
    assert (repo / "answer.txt").read_text() == "42\n"


def test_hints_unlock_at_2_and_5_failed_runs_and_the_solution_at_10_or_on_green(repo, tr):
    tr("start", "w1l1")
    code, out = tr("verify")
    assert "hint 1 unlocks after 2 failed runs" in out and "solution unlocks after 10 failed runs" in out
    code, out = tr("hint")
    assert code == 2 and "hint 1 unlocks after 2 failed runs" in out and "first hint" not in out
    set_state(repo, fails={"w1l1.1": 2})
    code, out = tr("hint")
    assert code == 0 and "first hint" in out and "second hint" not in out and "hint 2 unlocks after 5" in out
    set_state(repo, fails={"w1l1.1": 5})
    code, out = tr("hint")
    assert "second hint" in out and "third hint" in out  # hints past the list unlock at its last number
    set_state(repo, fails={"w1l1.1": 9})
    code, out = tr("solution")
    assert code == 2 and "unlocks after 10 failed runs" in out
    set_state(repo, fails={"w1l1.1": 10})
    code, out = tr("solution")
    assert code == 0 and "+42" in out
    set_state(repo, fails={"w1l1.1": 0})
    solve(repo, "w1l1.1")
    tr("verify")
    code, out = tr("solution")
    assert code == 0 and "+42" in out


def test_lab_toml_sets_the_unlock_numbers_and_a_lab_can_override_them(repo, tr):
    toml = repo / "labs" / "w1" / "lab.toml"
    toml.write_text(toml.read_text().replace("hints = [2, 5]", "hints = [1, 3]")
                    + "\n[labs.w1l1.unlock]\nsolution = 4\n")
    tr("start", "w1l1")
    code, out = tr("verify")
    assert "hint 1 is unlocked" in out and "hint 2 unlocks after 3 failed runs" in out
    assert "solution unlocks after 4 failed runs" in out
    assert "first hint" in tr("hint")[1]
    set_state(repo, fails={"w1l1.1": 4})
    assert tr("solution")[0] == 0


def test_reset_backs_up_only_files_you_edited(repo, tr):
    tr("start", "w1l1")
    code, out = tr("reset")
    assert code == 0 and "saved" not in out and not (repo / ".tr-lab" / "backup").exists()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "stub")
    code, out = tr("reset")
    assert "saved" not in out and not (repo / ".tr-lab" / "backup").exists()
    (repo / "answer.txt").write_text("my attempt\n")
    set_state(repo, fails={"w1l1.1": 3})
    code, out = tr("reset")
    assert code == 0 and "saved your uncommitted edits to answer.txt in .tr-lab/backup/w1l1.1-" in out
    [backup] = (repo / ".tr-lab" / "backup").rglob("answer.txt")
    assert backup.read_text() == "my attempt\n"
    assert (repo / "answer.txt").read_text() == "TODO(w1l1.1)\n"
    assert state(repo)["fails"]["w1l1.1"] == 0


def test_the_no_stub_exercise_keeps_your_file_and_the_lab_ends_with_the_repo_suite(repo, tr):
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    tr("next")
    code, out = tr("reset")
    assert code == 0 and "has no stub" in out and (repo / "answer.txt").read_text() == "42\n"
    solve(repo, "w1l1.2")
    (repo / "suite_red").write_text("")
    code, out = tr("next")
    assert code == 2 and "the repo's own tests are red" in out and "test_suite" in out
    assert state(repo)["current"] == "w1l1.2"
    (repo / "suite_red").unlink()
    code, out = tr("next")
    assert code == 0 and "lab w1l1 finished; tr lab start w1l2" in out
    assert state(repo)["current"] == "" and state(repo)["finished"] == ["w1l1"]
    code, out = tr("list")
    assert "w1l1  first: finished" in out and "start here       w1l2.1" in out and "start with: tr lab start w1l2" in out


def test_verify_takes_no_argument_an_exercise_or_a_lab(repo, tr):
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    tr("next")
    code, out = tr("verify", "w1l2.1")
    assert code == 2 and "w1l2.1 not reached yet" in out
    code, out = tr("verify", "w1l2")
    assert code == 2 and "not reached yet" in out
    code, out = tr("verify", "w1l1")
    assert code == 1 and "PASS  w1l1.1" in out and "FAIL  w1l1.2" in out and "1 of 2 reached exercises green" in out
    assert state(repo)["fails"] == {}  # a lab-range verify counts nothing
    (repo / "answer.txt").write_text("41\n")
    code, out = tr("verify", "w1l1.1")
    assert code == 1 and "an earlier exercise, not counted" in out and state(repo)["fails"] == {}
    code, out = tr("verify", "w1l1.2")
    assert code == 1 and "FAIL w1l1.2 (try 1)" in out and "answer.txt needs 43 below 42" in out
    code, out = tr("verify")
    assert "FAIL w1l1.2 (try 2)" in out
    code, out = tr("verify", "nope")
    assert code == 2 and "unknown exercise or lab" in out


def test_a_check_that_cannot_run_is_reported_and_not_counted(repo, tr):
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    tr("next")
    test = next((repo / "labs" / "w1" / "exercises").glob("w1l1.2-*")) / "test_w1l1_2.py"
    test.write_text("def broken(:\n")
    code, out = tr("verify")
    assert code == 3 and "ERROR w1l1.2: the check could not run" in out and "not counted as a try" in out
    assert "SyntaxError" in out
    assert state(repo)["fails"].get("w1l1.2", 0) == 0
    code, out = tr("verify", "-v")
    assert "short test summary info" in out or "errors" in out
    test.write_text("x = 1\n")
    code, out = tr("verify")
    assert code == 3 and "pytest collected no tests: check the exercise's check command" in out


def test_start_refuses_out_of_order_or_over_a_lab_in_progress(repo, tr):
    code, out = tr("start", "w1l9")
    assert code == 2 and "unknown lab" in out
    code, out = tr("start", "w1l2")
    assert code == 2 and "builds on w1l1, which is not finished" in out and "--assume-previous" in out
    assert not (repo / ".tr-lab").exists()
    tr("start", "w1l1")
    code, out = tr("start", "w1l1")
    assert code == 2 and "in progress at w1l1.1" in out
    set_state(repo, fails={"w1l1.1": 4})
    code, out = tr("start", "w1l1", "--force")
    assert code == 0 and state(repo)["fails"] == {}
    assert "saved" not in out and not (repo / ".tr-lab" / "backup").exists()  # the file is the runner's own stub
    git(repo, "checkout", "-q", "main")
    set_state(repo, current="")
    code, out = tr("start", "w1l1")
    assert code == 2 and "a branch `lab` already exists" in out


def test_assume_previous_applies_and_commits_the_earlier_reference_solutions(repo, tr):
    code, out = tr("start", "w1l2", "--assume-previous")
    assert code == 0 and "applied the reference solutions of w1l1.1..w1l1.2" in out
    assert (repo / "answer.txt").read_text() == "42\n43\n"
    assert (repo / "second.txt").read_text() == "TODO(w1l2.1)\n"
    assert "(--assume-previous)" in git(repo, "log", "-1", "--format=%s")
    st = state(repo)
    assert st["current"] == "w1l2.1" and st["done"] == st["assumed"] == ["w1l1.1", "w1l1.2"]
    assert st["finished"] == ["w1l1"]
    assert "done (reference) w1l1.1" in tr("list")[1]
    assert tr("verify", "w1l1")[0] == 0


def test_tr_lab_runs_without_an_env_file_while_a_learner_module_is_broken(repo):
    """A stub can leave analyze.py (or anything cli.py imports) unimportable; `tr lab` must still work without importing
    cli at all, and every other command fails exactly as before."""
    broken = "import sys; sys.modules['tradingresearch.analyze'] = None; "  # None in sys.modules: import fails
    run = "from tradingresearch.labmain import main; main()"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo), "TR_ENV_FILE": str(repo / "missing.env")}
    no_cli = broken + "sys.modules['tradingresearch.cli'] = None; " + run
    lab_ = subprocess.run([sys.executable, "-c", no_cli, "lab", "status"], cwd=repo, capture_output=True, text=True, env=env)
    assert lab_.returncode == 0 and '"current": ""' in lab_.stdout
    for args in (["sessions"], ["-h"]):
        other = subprocess.run([sys.executable, "-c", broken + run, *args], cwd=repo, capture_output=True, text=True,
                               env=env)
        assert other.returncode != 0 and "import of tradingresearch.analyze halted" in other.stderr


def test_next_backs_up_your_committed_version_before_the_next_stub_replaces_it(repo, tr):
    stub = next((repo / "labs" / "w1" / "exercises").glob("w1l1.2-*")) / "stub" / "answer.txt"
    stub.parent.mkdir()
    stub.write_text("42\nTODO(w1l1.2)\n")
    code, out = tr("start", "w1l1")
    assert "saved" not in out and "starts from" not in out  # answer.txt as the repo shipped it is nobody's work
    (repo / "answer.txt").write_text("42\nmy own second line\n")
    code, out = tr("next")
    sha = git(repo, "log", "-1", "--format=%h").strip()
    assert code == 0 and (f"w1l1.2 starts from the reference version of w1l1.1 in answer.txt; your version is in commit "
                          f"{sha} (`lab w1l1.1: green`) and in .tr-lab/backup/w1l1.2-") in out
    [backup] = (repo / ".tr-lab" / "backup").rglob("answer.txt")
    assert backup.read_text() == "42\nmy own second line\n"
    assert (repo / "answer.txt").read_text() == "42\nTODO(w1l1.2)\n"
    assert git(repo, "show", "HEAD:answer.txt") == "42\nmy own second line\n"


def test_restarting_a_lab_clears_its_reference_marks_and_backs_up_only_your_edits(repo, tr):
    tr("start", "w1l1")
    (repo / "answer.txt").write_text("my attempt\n")
    code, out = tr("start", "w1l1", "--force")
    assert code == 0 and "saved your uncommitted edits to answer.txt" in out
    code, out = tr("start", "w1l2", "--assume-previous", "--force")
    assert code == 0 and "saved" not in out and state(repo)["assumed"] == ["w1l1.1", "w1l1.2"]
    code, out = tr("start", "w1l1", "--force")
    assert code == 0 and "saved" not in out and "starts from" not in out  # a reference solution is nobody's work
    assert state(repo)["assumed"] == [] and state(repo)["done"] == []
    assert "done (reference) w1l1.1" not in tr("list")[1]


def test_next_lists_the_commit_and_flags_a_changed_file_outside_the_exercise(repo, tr):
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    suite = repo / "tests" / "test_suite.py"
    suite.write_text(suite.read_text() + "# a stray edit\n")
    (repo / "notes.txt").write_text("a new file\n")
    code, out = tr("next")
    assert code == 0 and "committed `lab w1l1.1: green`: answer.txt, notes.txt, tests/test_suite.py" in out
    assert "note: tests/test_suite.py changed too, outside w1l1.1's files (answer.txt)" in out
    assert "notes.txt changed" not in out


def test_observe_exit_codes_in_observe_ok_exit_are_not_reported(repo, tr):
    toml = next((repo / "labs" / "w1" / "exercises").glob("w1l1.1-*")) / "exercise.toml"
    exits_1 = 'observe = "python -c \\"import sys; sys.exit(1)\\""'
    toml.write_text(re.sub(r"^observe = .*$", lambda _: exits_1, toml.read_text(), flags=re.M))
    tr("start", "w1l1")
    solve(repo, "w1l1.1")
    code, out = tr("verify")
    assert code == 0 and "(observe exited 1; it never decides the exercise)" in out
    toml.write_text(toml.read_text() + "observe_ok_exit = [0, 1]\n")
    code, out = tr("verify")
    assert code == 0 and "observe exited" not in out


AUTHOR_PYPROJECT = """\
[project.scripts]
tr = "tradingresearch.cli:main"

[tool.pytest.ini_options]
markers = [
    "live: calls a real API",
]
addopts = "-m 'not live'"
"""
RUNNER_FILES = {"src/tradingresearch/lab.py": "the runner\n", "src/tradingresearch/labmain.py": "the dispatcher\n",
                "tests/test_lab.py": "# the runner's tests\n"}


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


@pytest.fixture
def weeks(repo) -> Path:
    """`repo` plus week 2. Tag week-2-start (the author's tree): changed.txt changed, gone.txt deleted, new.txt added,
    the author's pyproject.toml, .gitignore, cli.py and tests/test_lab.py, and no labs/, lab.py or labmain.py. Tag
    week-2-bad: the same without the addopts line. w2l1 = w2l1.1 (stub changed.txt), w2l2 = w2l2.1 (stub third.txt)."""
    write(repo, {**RUNNER_FILES, "src/tradingresearch/cli.py": "week 1 cli\n", "changed.txt": "week 1\n",
                 "gone.txt": "only in week 1\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "week 1 files")
    git(repo, "checkout", "-q", "-b", "author")
    git(repo, "rm", "-rq", "labs", "src/tradingresearch/lab.py", "src/tradingresearch/labmain.py", "gone.txt")
    write(repo, {"changed.txt": "week 2\n", "new.txt": "new in week 2\n", "src/tradingresearch/cli.py": "week 2 cli\n",
                 "tests/test_lab.py": "# the author's own file\n", "pyproject.toml": AUTHOR_PYPROJECT,
                 ".gitignore": "data/\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "week 2")
    git(repo, "tag", "week-2-start")
    write(repo, {"pyproject.toml": AUTHOR_PYPROJECT.replace("addopts = \"-m 'not live'\"\n", "")})
    git(repo, "commit", "-qam", "no addopts")
    git(repo, "tag", "week-2-bad")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "-qD", "author")
    write(repo, {"labs/w2/lab.toml": 'base = "week-2-start"\n\n[labs.w2l1]\ntitle = "third"\n\n[labs.w2l2]\ntitle = "fourth"\n'})
    hints = "# Hints\n\n## Hint 1\n\nlook again\n"
    exercise(repo, "w2l1.1-changed", """\
        id = "w2l1.1"
        title = "fix changed.txt"
        lab = "w2l1"
        touches = ["changed.txt"]
        check = "python labs/w1/check.py changed.txt 5"
        """, {"stub/changed.txt": "TODO(w2l1.1)\n", "hints.md": hints,
              "solution.diff": diff("changed.txt", ["TODO(w2l1.1)"], ["5"])}, week="w2")
    exercise(repo, "w2l2.1-third", """\
        id = "w2l2.1"
        title = "the third file"
        lab = "w2l2"
        touches = ["third.txt"]
        check = "python labs/w1/check.py third.txt 8"
        """, {"stub/third.txt": "TODO(w2l2.1)\n", "hints.md": hints,
              "solution.diff": diff("third.txt", ["TODO(w2l2.1)"], ["8"])}, week="w2")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "week 2 labs")
    return repo


def test_a_week_base_is_applied_once_committed_and_leaves_the_runner_and_labs_alone(weeks, tr):
    labs_tree = git(weeks, "rev-parse", "HEAD:labs")
    code, out = tr("start", "w2l1")  # week 1 is not finished: week 2 needs nothing from it
    assert code == 0 and "week 2 starts from the author's code at week-2-start: 6 files changed" in out
    assert "your earlier commits stay in the history of `lab`" in out and "run `uv sync` now" in out
    assert git(weeks, "log", "-1", "--format=%s").strip() == "lab: week 2 base (week-2-start)"
    assert git(weeks, "rev-parse", "HEAD:labs") == labs_tree
    assert all((weeks / rel).read_text() == text for rel, text in RUNNER_FILES.items())
    assert git(weeks, "show", "HEAD:changed.txt") == "week 2\n" and (weeks / "changed.txt").read_text() == "TODO(w2l1.1)\n"
    assert not (weeks / "gone.txt").exists() and (weeks / "new.txt").read_text() == "new in week 2\n"
    assert (weeks / "src" / "tradingresearch" / "cli.py").read_text() == "week 2 cli\n"
    pyproject = (weeks / "pyproject.toml").read_text()
    assert lab.LAB_SCRIPT in pyproject and lab.LAB_ADDOPTS in pyproject and lab.LAB_MARKER in pyproject
    assert lab.TESTPATHS in pyproject and lab.AUTHOR_SCRIPT not in pyproject and lab.AUTHOR_ADDOPTS not in pyproject
    assert lab._lab_pyproject(pyproject, "x") == pyproject == lab._lab_pyproject(lab._lab_pyproject(AUTHOR_PYPROJECT, "x"), "x")
    gitignore = (weeks / ".gitignore").read_text().splitlines()
    assert gitignore[0] == "data/" and ".tr-lab/" in gitignore and lab._lab_gitignore("\n".join(gitignore)) == "\n".join(gitignore)
    assert git(weeks, "status", "--porcelain", "--", ".tr-lab") == "" and state(weeks)["bases"] == ["w2"]
    commits = git(weeks, "rev-list", "--count", "HEAD")
    code, out = tr("start", "w2l1", "--force")
    assert code == 0 and "week 2 starts" not in out and git(weeks, "rev-list", "--count", "HEAD") == commits
    code, out = tr("status")
    assert '"base": "week-2-start"' in out and '"bases": ["w2"]' in out
    code, out = tr("list")
    assert "week 1\nw1l1  first" in out and "week 2 (starts from week-2-start)\nw2l1  third" in out
    git(weeks, "checkout", "-qf", "main")  # recreating `lab` with --force starts the bases again
    code, out = tr("start", "w2l1", "--force")
    assert code == 0 and "week 2 starts from the author's code at week-2-start" in out and state(weeks)["bases"] == ["w2"]


def test_a_week_base_refuses_a_dirty_tree(weeks, tr):
    (weeks / "notes.txt").write_text("mine\n")
    code, out = tr("start", "w2l1")
    assert code == 2 and "uncommitted changes (notes.txt): commit or stash first; week 2 starts from" in out
    assert git(weeks, "branch", "--show-current").strip() == "main" and not (weeks / ".tr-lab").exists()
    (weeks / "notes.txt").unlink()
    (weeks / "changed.txt").write_text("edited\n")
    code, out = tr("start", "w2l1")
    assert code == 2 and "uncommitted changes (changed.txt)" in out and (weeks / "changed.txt").read_text() == "edited\n"


def test_assume_previous_in_a_week_with_a_base_applies_only_that_weeks_earlier_labs(weeks, tr):
    code, out = tr("start", "w2l2")
    assert code == 2 and "builds on w2l1, which is not finished" in out and "w1l" not in out
    code, out = tr("start", "w2l2", "--assume-previous")
    assert code == 0 and "applied the reference solutions of w2l1.1..w2l1.1" in out and "saved" not in out
    st = state(weeks)
    assert st["assumed"] == ["w2l1.1"] and st["finished"] == ["w2l1"] and st["current"] == "w2l2.1"
    assert (weeks / "changed.txt").read_text() == "5\n" and (weeks / "answer.txt").read_text() == "start\n"
    assert git(weeks, "log", "-3", "--format=%s").splitlines() == [
        "lab: reference solutions w2l1.1..w2l1.1 (--assume-previous)", "lab: week 2 base (week-2-start)", "week 2 labs"]
    assert (weeks / "third.txt").read_text() == "TODO(w2l2.1)\n"


@pytest.mark.parametrize(("tag", "said"), [
    ("week-2-bad", "pyproject.toml at week-2-bad has no line `addopts = \"-m 'not live'\"` in [tool.pytest.ini_options]"),
    ("week-2-nope", "week 2 starts from the tag week-2-nope, which this clone does not have")])
def test_a_base_that_cannot_be_applied_errors_by_name_and_changes_nothing(weeks, tr, tag, said):
    toml = weeks / "labs" / "w2" / "lab.toml"
    toml.write_text(toml.read_text().replace("week-2-start", tag))
    git(weeks, "commit", "-qam", "another base")
    head = git(weeks, "rev-parse", "HEAD")
    code, out = tr("start", "w2l1")
    assert code == 2 and said in out
    assert git(weeks, "status", "--porcelain") == "" and git(weeks, "rev-parse", "HEAD") == head
    assert not (weeks / ".tr-lab" / "state.json").exists()

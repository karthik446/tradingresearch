# Labs

Labs are optional hands-on practice for the [AI engineering track](https://scout.edgelab.one/learn/ai-engineering/). The chapters stand alone: you can read a week without doing its labs. Each week's labs are short exercises on this repo. An exercise is a change to one or two files, checked by pytest on your machine. It costs $0: no key, no model call, no network. `tr lab` runs the loop: it installs the exercise's starting file, runs the check, unlocks hints, and commits each green exercise.

| Week | Labs | Pages |
|---|---|---|
| 1 | w1l1 claim checks (4 exercises), w1l2 open and axial coding (4), w1l3 a code grader (6), w1l4 a paired experiment (5) | [labs/w1/pages/index.md](w1/pages/index.md) |

Week 1 is here; the labs for weeks 2-9 are added week by week.

## Start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/); the [setup page](https://scout.edgelab.one/learn/ai-engineering/setup/) covers the rest of the setup. No key is needed for the labs.

```bash
git clone https://github.com/karthik446/tradingresearch.git && cd tradingresearch
git checkout labs
uv sync
.venv/bin/tr lab list          # every lab and exercise: done, current, start here or locked
.venv/bin/tr lab start w1l1    # switch to branch `lab`, install the first exercise's stub
```

Bare `tr` can resolve to another program on some systems (macOS and Linux ship a `tr` text tool). Use `.venv/bin/tr`, or activate the virtualenv (`source .venv/bin/activate`) so that `tr` is this repo's; the rest of this page writes `tr lab ...` for short.

The `labs` branch starts at the tag `week-1-start` and adds `tr lab` and this folder. `master` is the author's working branch; the tags `week-N-start` and `week-N-end` mark where each chapter starts and ends, and `week-1-end` holds the reference answer for week 1.

Then, for each exercise:

1. Read the exercise on its lab page. `start` and `next` print the file to edit and its `TODO(<id>)` tag.
2. `tr lab verify` runs the check. Red prints the teaching message from the failing test; edit and run it again.
3. Green prints PASS and runs the exercise's observe command, which shows a number move (regrading the author's recorded runs with your code).
4. `tr lab next` re-checks, commits your work as `lab <id>: green` and installs the next stub. At the last exercise of a lab it also runs the repo's own test suite, then says which lab to start next.

## Commands

| Command | Does | Exit |
|---|---|---|
| `tr lab list` | every lab and exercise: done, done (reference), current, start here (the first exercise of the lab to start next) or locked | 0 |
| `tr lab start <lab>` | switch to branch `lab` (`git checkout -B lab`) and install the lab's first stub; the first start in a week with a base brings in that week's code first ([Weeks](#weeks)). Refuses while another lab is in progress (`--force` restarts), while an earlier lab is unfinished (`--assume-previous`, below), or when a branch `lab` exists and you are not on it (`--force` recreates it from your current commit) | 0, 2 refused |
| `tr lab verify` | run the current exercise's check; counts a failed run | 0 green, 1 red, 2 refused, 3 the check could not run |
| `tr lab verify <exercise>` | run one exercise you have reached, e.g. `w1l1.2`; counts only if it is the current one | 0, 1, 2 not reached, 3 |
| `tr lab verify <lab>` | run every reached exercise of a lab, one line each; counts nothing | 0 all green, 1 any red or ERROR line |
| `tr lab verify -v` | also print pytest's full output | |
| `tr lab hint` | print the hints unlocked so far, and when the next one unlocks | 0, 2 while locked |
| `tr lab solution [--apply]` | print the reference `solution.diff` once unlocked; `--apply` installs the stub (after a backup) and applies the diff | 0, 2 while locked |
| `tr lab reset` | put the current stub back (after a backup) and zero its failed runs | 0 |
| `tr lab next` | re-run the check; on green commit, print the files the commit holds, and install the next stub | 0, 2 if red or git refused |
| `tr lab status` | the state as one JSON line | 0 |

`--assume-previous` on `start` (for example `tr lab start w1l3 --assume-previous`) applies the reference solutions of every exercise in the earlier, unfinished labs (of the same week, when the week has a base), commits them as `lab: reference solutions <first>..<last> (--assume-previous)`, and marks those exercises "done (reference)". Use it to enter the week at a later lab; the later labs read files the earlier ones produce.

What `verify` runs is the `check` line of the exercise's `exercise.toml`, a plain pytest command such as `python -m pytest -q -x -p no:cacheprovider -m lab labs/w1/exercises/w1l1.1-unknown-source/test_w1l1_1.py`. Each exercise on the lab pages shows it, so you can run it by hand. The lab tests carry the `lab` marker; the repo's `pyproject.toml` deselects them (`addopts = "-m 'not live and not lab'"`, `testpaths = ["tests"]`), so plain `pytest -q` runs only the repo's own suite.

## Weeks

Week 1 starts from the code on this branch. Each later week starts from the author's code at its tag: its `labs/<week>/lab.toml` says `base = "week-N-start"`. The first `tr lab start` of such a week makes the repo's files equal to the tag's, except `labs/` and `tr lab`'s own files, puts `tr lab`'s lines back into `pyproject.toml` and `.gitignore`, and commits that as `lab: week N base (<tag>)`; your earlier commits stay in the history of `lab`. It refuses while you have uncommitted changes (commit or stash first), asks for `git fetch --tags` when the tag is missing, and says when `pyproject.toml` or `uv.lock` changed: run `uv sync` then. A week's labs build only on the earlier labs of the same week, so you can start week 2 without finishing week 1. `tr lab list` shows each week and its tag.

## Hints and the solution

A failed run is a red `tr lab verify` of the current exercise. A check that cannot run at all (pytest stops with a collection error, for example) prints ERROR, exits 3 and does not count.

| Unlocks | Default |
|---|---|
| hint 1 | after 2 failed runs |
| hint 2 | after 5 failed runs |
| further hints, if an exercise has more | at the last hint number (5) |
| the solution | after 10 failed runs, or at once when the check is green (to compare) |

The numbers live in one place, the week's `lab.toml` ([labs/w1/lab.toml](w1/lab.toml)): `[unlock] hints = [2, 5]` and `solution = 10`. A lab can override them with its own `[labs.<lab>.unlock]` table. `tr lab reset` zeroes the count of the current exercise.

The last exercise of a lab also runs the repo's own suite and wants it green. A week whose chapter leaves tests red until later (week 2's `tests/test_week2.py` covers all of §2-§3) lists the pytest node ids the gate leaves out: `[suite] deselect = [...]` for the whole week and `[labs.<lab>.suite] deselect = [...]` for one lab, passed as `--deselect`. Only the end-of-lab gate uses them; `python -m pytest -q` still shows everything.

The labs are an honor system: they are for you. They run on your machine against files you can edit, and `tr lab` does not verify that the tests, the exercise metadata or the recorded data under `labs/` are the ones the course shipped: a rewritten test or a `check` of `python -c pass` will turn an exercise green. A green only means something if you leave those files alone. `tr lab next` lists files outside the exercise's `touches`, and `git diff` against the branch you started from shows any change to course files. The solution diffs are in the repo for the same reason: opening them early costs you the exercise, not anyone else.

## Your work and git

- `start` works on a branch `lab`, so the branch you started from (`labs`) is untouched.
- `next` commits every change in the repo (`git add -A`) as `lab <id>: green` and prints the files that commit holds. A changed file outside the exercise's `touches` (a stray edit) gets a `note:` line that names it; new files are listed but not flagged. `git show --stat HEAD` shows the commit.
- A stub is the reference state of the earlier exercises plus one new TODO, not your own file. Before `start`, `next`, `reset` or `solution --apply` overwrite a file that holds your work, they copy it to `.tr-lab/backup/<exercise>-<time>/` and print one line per file:
  - a version a `lab <id>: green` commit holds: ``w1l3.4 starts from the reference version of w1l3.3 in src/tradingresearch/evals.py; your version is in commit <sha> (`lab w1l3.3: green`) and in .tr-lab/backup/...``. `start w1l3` prints this for `analyze.py`, which lab w1l1 committed and the w1l3.1 stub replaces.
  - uncommitted edits: `saved your uncommitted edits to <file> in .tr-lab/backup/... before <id> replaced it`.

  Not copied: a file equal to the new stub or to the current exercise's stub (the runner put it there), a file as the repo shipped it, and the reference solutions `--assume-previous` committed.
- State is in `.tr-lab/state.json` at the repo root; `.tr-lab/` is in `.gitignore`. Restarting a lab (`start --force`) clears that lab's done marks, failed runs and "done (reference)" marks.
- `tr lab` imports nothing a stub overwrites, so it still runs when your edit leaves `analyze.py` or `evals.py` broken: the `tr` entry point (`src/tradingresearch/labmain.py`) sends `tr lab` to the runner before anything imports the rest of `tr`. The other `tr` commands, `tr -h` included, show that import error.

## When something goes wrong

| What happens | What `tr lab` does |
|---|---|
| You edit the wrong file | The check stays red with the same message. The message names the file and function; `start` and `next` print the file and its `TODO(<id>)` tag. |
| You break the repo's own tests | `verify` runs only the exercise's check, so it can be green. At a lab's last exercise `next` runs the repo suite (`python -m pytest -q`) and refuses (exit 2), listing the failing tests. During lab w1l1 the suite is red by design until w1l1.4 is green (4, 3, 2, 1 failing tests on the four stubs); the gate runs after w1l1.4. |
| You pass, then change the file (or reset) and run `next` | `next` re-runs the check on the current files and refuses on red (exit 2). Any red counted run clears the saved pass. |
| `git commit` fails (hook, identity, lock) | `next` stops (exit 2) with git's message, or "a hook or config refused it, no message"; the state is unchanged and nothing advances. `tests/test_lab.py` proves this with a failing pre-commit hook. |
| The check cannot run (syntax error in a test, a missing module, pytest exits with a code other than 0 or 1) | ERROR with the last lines of pytest's output, exit 3; not counted as a failed run. When pytest collected no tests (exit 5) it says so: the exercise's check command points at no test. |
| Your edit breaks an import `tr` needs | `tr lab` still runs (see above). |
| An exercise has no stub (w1l2.4 back-fills your own `labels.csv`) | `next` installs nothing, `reset` keeps your file, `solution --apply` explains that the diff expects the reference files. |
| You start a later lab first | `start` refuses and names the unfinished lab; `--assume-previous` applies its reference solutions. |
| A lab page and its tests disagree | `python labs/tools/prove.py w1` re-proves every exercise of a week (stub red, solution green, earlier checks still green, each known wrong fix red with its message, the end state equal to the week's end tag, and a `tr lab` smoke run) and writes [labs/w1/PROOF.md](w1/PROOF.md) when redirected there. |

## For authors

The layout of a week and how to re-run the proof: [labs/w1/README.md](w1/README.md); the proof tool is `labs/tools/prove.py <week>`. `tr lab`'s own tests: `tests/test_lab.py` (plain `pytest`, no network). The runner: `src/tradingresearch/lab.py`, reached through `src/tradingresearch/labmain.py`.

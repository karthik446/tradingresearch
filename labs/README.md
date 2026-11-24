# Labs

Labs spike v3, not published. Each week of the AI engineering track comes as labs of short exercises on this repo. An exercise is a change to one or two files, checked by pytest on your machine. No key, no model call, no network. `tr lab` runs the loop: it installs the exercise's starting file, runs the check, unlocks hints, and commits each green exercise.

| Week | Labs | Pages |
|---|---|---|
| 1 | w1l1 claim checks (4 exercises), w1l2 open and axial coding (4), w1l3 a code grader (6), w1l4 a paired experiment (5) | [labs/w1/pages/index.md](w1/pages/index.md) |

## Start

From the root of your clone at `week-1-start`, after `uv sync`:

```bash
uv run tr lab list          # every lab and exercise: done, current or locked
uv run tr lab start w1l1    # switch to branch `lab`, install the first exercise's stub
```

With the virtualenv active (`source .venv/bin/activate`), `tr lab ...` is enough; the rest of this page drops the `uv run`. Then, for each exercise:

1. Read the exercise on its lab page. `start` and `next` print the file to edit and its `TODO(<id>)` tag.
2. `tr lab verify` runs the check. Red prints the teaching message from the failing test; edit and run it again.
3. Green prints PASS and runs the exercise's observe command, which shows a number move (regrading the author's recorded runs with your code).
4. `tr lab next` re-checks, commits your work as `lab <id>: green` and installs the next stub. At the last exercise of a lab it also runs the repo's own test suite, then says which lab to start next.

## Commands

| Command | Does | Exit |
|---|---|---|
| `tr lab list` | every lab and exercise: done, done (reference), current or locked | 0 |
| `tr lab start <lab>` | switch to branch `lab` (`git checkout -B lab`) and install the lab's first stub. Refuses while another lab is in progress (`--force` restarts), while an earlier lab is unfinished (`--assume-previous`, below), or when a branch `lab` exists and you are not on it (`--force` recreates it from your current commit) | 0, 2 refused |
| `tr lab verify` | run the current exercise's check; counts a failed run | 0 green, 1 red, 2 refused |
| `tr lab verify <exercise>` | run one exercise you have reached, e.g. `w1l1.2`; counts only if it is the current one | 0, 1, 2 not reached |
| `tr lab verify <lab>` | run every reached exercise of a lab, one line each; counts nothing | 0 all green, 1 |
| `tr lab verify -v` | also print pytest's full output | |
| `tr lab hint` | print the hints unlocked so far, and when the next one unlocks | 0, 2 while locked |
| `tr lab solution [--apply]` | print the reference `solution.diff` once unlocked; `--apply` installs the stub (after a backup) and applies the diff | 0, 2 while locked |
| `tr lab reset` | put the current stub back (after a backup) and zero its failed runs | 0 |
| `tr lab next` | re-run the check; on green commit and install the next stub | 0, 2 if red or git refused |
| `tr lab status` | the state as one JSON line | 0 |

`--assume-previous` on `start` (for example `tr lab start w1l3 --assume-previous`) applies the reference solutions of every exercise in the earlier, unfinished labs, commits them as `lab: reference solutions <first>..<last> (--assume-previous)`, and marks those exercises "done (reference)". Use it to enter the week at a later lab; the later labs read files the earlier ones produce.

What `verify` runs is the `check` line of the exercise's `exercise.toml`, a plain pytest command such as `python -m pytest -q -x -p no:cacheprovider -m lab labs/w1/exercises/w1l1.1-unknown-source/test_w1l1_1.py`. Each exercise on the lab pages shows it, so you can run it by hand. The lab tests carry the `lab` marker; the repo's `pyproject.toml` deselects them (`addopts = "-m 'not live and not lab'"`, `testpaths = ["tests"]`), so plain `pytest -q` runs only the repo's own suite.

## Hints and the solution

A failed run is a red `tr lab verify` of the current exercise. A check that cannot run at all (pytest stops with a collection error, for example) prints ERROR and does not count.

| Unlocks | Default |
|---|---|
| hint 1 | after 2 failed runs |
| hint 2 | after 5 failed runs |
| further hints, if an exercise has more | at the last hint number (5) |
| the solution | after 10 failed runs, or at once when the check is green (to compare) |

The numbers live in one place, the week's `lab.toml` ([labs/w1/lab.toml](w1/lab.toml)): `[unlock] hints = [2, 5]` and `solution = 10`. A lab can override them with its own `[labs.<lab>.unlock]` table. `tr lab reset` zeroes the count of the current exercise.

## Your work and git

- `start` works on a branch `lab`, so your `main` is untouched. `next` commits everything (`git add -A`) on that branch.
- State is in `.tr-lab/state.json` at the repo root; `.tr-lab/` is in `.gitignore`.
- `reset` and `solution --apply` overwrite the files the exercise touches. Before they do, every touched file that differs from the stub and has uncommitted changes is copied to `.tr-lab/backup/<exercise>-<time>/`, and the command lists the copies. Committed or untouched files are not copied.
- `tr lab` imports nothing a stub overwrites, so it still runs when your edit leaves `analyze.py` or `evals.py` broken. The other `tr` commands show that import error.

## When something goes wrong

| What happens | What `tr lab` does |
|---|---|
| You edit the wrong file | The check stays red with the same message. The message names the file and function; `start` and `next` print the file and its `TODO(<id>)` tag. |
| You break the repo's own tests | `verify` runs only the exercise's check, so it can be green. At a lab's last exercise `next` runs the repo suite (`python -m pytest -q`) and refuses (exit 2), listing the failing tests. During lab w1l1 the suite is red by design until w1l1.4 is green (4, 3, 2, 1 failing tests on the four stubs); the gate runs after w1l1.4. |
| You pass, then change the file (or reset) and run `next` | `next` re-runs the check on the current files and refuses on red (exit 2). Any red counted run clears the saved pass. |
| `git commit` fails (hook, identity, lock) | `next` stops (exit 2) with git's message, or "a hook or config refused it, no message"; the state is unchanged and nothing advances. `tests/test_lab.py` proves this with a failing pre-commit hook. |
| The check cannot run (syntax error in a test, a missing module, pytest exits with a code other than 0 or 1) | ERROR with the last lines of pytest's output; not counted as a failed run. |
| Your edit breaks an import `tr` needs | `tr lab` still runs (see above). |
| An exercise has no stub (w1l2.4 back-fills your own `labels.csv`) | `next` installs nothing, `reset` keeps your file, `solution --apply` explains that the diff expects the reference files. |
| You start a later lab first | `start` refuses and names the unfinished lab; `--assume-previous` applies its reference solutions. |
| A lab page and its tests disagree | `python labs/w1/tools/prove.py` re-proves every exercise (stub red, solution green, earlier checks still green, each known wrong fix red with its message, the end state equal to `week-1-end`, and a `tr lab` smoke run) and writes [labs/w1/PROOF.md](w1/PROOF.md). |

## For authors

The layout of a week, the old-to-new id mapping and how to re-run the proof: [labs/w1/README.md](w1/README.md). `tr lab`'s own tests: `tests/test_lab.py` (plain `pytest`, no network). The runner: `src/tradingresearch/lab.py`.

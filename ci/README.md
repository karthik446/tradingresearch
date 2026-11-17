# CI gate

A free gate: no network, no model call, no key. It blocks two regressions.

- **Reconcile:** every synthetic case in `tests/fixtures/reconcile/bars.json` (long and short, plus the missing-bar and partial-session variants in `CASES`) is settled by `reconcile.settle` and compared with `tests/gate/golden/reconcile.json` (events, outcome grade and notes as sorted JSON). A rule or cost change that moves a result fails with a diff. To accept it, bump `RULES_VERSION` in `src/tradingresearch/records.py`, then run `uv run python ci/gate.py --accept-reconcile`; without the bump it refuses. A new case with no moved results needs no bump.
- **Prompts:** every file in `prompts/` has an entry in `ci/prompt-hashes.json` (sha256 and the experiment that justifies it). It fails when a recorded prompt's bytes change or the file is gone, when a prompt has no entry, and when an entry's experiment does not justify it: an `experiments/<experiment>.toml` arm must name the prompt, or the experiment is `baseline` and the file is a `*-1` prompt. To change a prompt, write a new file (`analyze-3.txt`), name it in an experiment arm, then run `uv run python ci/gate.py --record-prompts` (it prints what it records) and commit the hash.

## Run locally

```
uv run python ci/gate.py      # both checks; exit 0 = pass
uv run pytest tests/gate -q   # the same checks as tests, plus the negative cases
```

## Remote CI

The repo has no remote, so there is no workflow file. A remote job would check out the repo, run `uv sync`, then `uv run python ci/gate.py` and `uv run pytest -q` (live tests are excluded by default), and fail the merge on a non-zero exit.

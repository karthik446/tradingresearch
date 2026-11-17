# tradingresearch

Educational equity research on live market data. Not investment advice; it places no orders.

```
uv sync
mkdir -p ~/.config/tradingresearch   # keys go in verify.env there; tr reads it itself
uv run tr --help
uv run pytest -q
```

Each chapter of the build guide starts at a tag (`week-1-start`) and ends at one (`week-1-end`):
`git checkout week-1-start`, `git log --oneline week-1-start..week-1-end`.

- `prompts/<version>.txt`: the system prompts. A new prompt is a new file, never an edit.
- `experiments/*.toml`: experiments as config (`uv run tr exp run experiments/observe.toml`).
- `evals/`: your labels, taxonomy and eval specs. `src/tradingresearch/evals.py` is the grader registry.
- `data/` (or `$TR_DATA_DIR`): journal, bars, EDGAR cache, traces, run files. Never committed.
- `src/tradingresearch/retry.py`: the one retry policy every HTTP call uses (runbook, "Retries").

The desk's daily loop, one command each (`uv run tr <command> --help` has the flags):

| Command | What it does |
|---|---|
| `tr screen` | ranks the universe by §5 triggers and stores the shortlist |
| `tr analyze` / `tr thesis` / `tr open` | claims for a ticker, then 0-3 theses (or a no-trade); `--arm teacher --teacher <model>` pins a DeepInfra route |
| `tr reconcile` | settles PROPOSED and OPEN theses from bars after 16:15 ET (rules in `reconcile.py`, goldens in `tests/gate/`) |
| `tr grade` | shadow baseline for each filled champion/challenger thesis, then one Grade (r_net score, P2-P4) once thesis and shadow are CLOSED; `--judge` adds the P1 judge (one model call per graded thesis, `--judge-max-usd`), nothing else calls a model |
| `tr label list` / `show` / `add` / `agree` | blind P1 labels of graded theses (`show` never prints a judge verdict), then Cohen's kappa against stored judge verdicts; thresholds shown as PROPOSED; no model call |
| `tr daily` | screen, analyze the shortlist, thesis each, reconcile; reruns skip what is done; `--max-usd` caps spend; `--teachers` adds the bake-off teachers on the drawn names (`--teacher-max-usd` caps them) |
| `tr report` | one scorecard per arm and horizon (never pooled): Wilson win rate, mean r_net and real − shadow with a session-cluster bootstrap, MFE/MAE, MDE, P1 2x2, cost per run |
| `tr slo` | the after-close SLOs from the first live session, 2026-11-17 (finished by 17:30 ET, zero missed sessions, fresh bars); exit 1 on a breach |
| `tr usage` | cost per call, run, arm or day from the trace |
| `tr bakeoff draw` / `report` | the date-seeded 4-name draw and the per-teacher report for the teacher bake-off |

`uv run python ci/gate.py` is the free CI gate (reconcile goldens and prompt hashes). `tests/test_week2.py` fails by design at `week-2-start`: it is your week-2 acceptance test.

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

The desk's daily loop, one command each (`uv run tr <command> --help` has the flags):

| Command | What it does |
|---|---|
| `tr screen` | ranks the universe by §5 triggers and stores the shortlist |
| `tr analyze` / `tr thesis` / `tr open` | claims for a ticker, then 0-3 theses (or a no-trade); `--arm teacher --teacher <model>` pins a DeepInfra route |
| `tr reconcile` | settles PROPOSED and OPEN theses from bars after 16:15 ET (rules in `reconcile.py`, goldens in `tests/gate/`) |
| `tr grade` | shadow baseline for each filled champion/challenger thesis, then one Grade (r_net score, P2-P4) once thesis and shadow are CLOSED; no model call |
| `tr daily` | screen, analyze the shortlist, thesis each, reconcile; reruns skip what is done; `--max-usd` caps spend; `--teachers` adds the bake-off teachers on the drawn names (`--teacher-max-usd` caps them) |
| `tr usage` | cost per call, run, arm or day from the trace |
| `tr bakeoff draw` / `report` | the date-seeded 4-name draw and the per-teacher report for the teacher bake-off |

`uv run python ci/gate.py` is the free CI gate (reconcile goldens and prompt hashes). `tests/test_week2.py` fails by design at `week-2-start`: it is your week-2 acceptance test.

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

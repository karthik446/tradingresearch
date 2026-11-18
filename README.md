# tradingresearch

Educational equity research on live market data. Not investment advice; it places no orders.

```
uv sync
cp .env.example .env   # then fill in the keys; tr reads .env itself (Prerequisites, below)
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
| `tr daily` | screen, analyze the shortlist, thesis each, reconcile; reruns skip what is done; `--max-usd` caps spend; while a rule change is pending the challenger answers each analysis under `rules.CHALLENGER_RULES[diff_ref]` (`--no-challenger` skips it); `--teachers` adds the bake-off teachers on the drawn names (`--teacher-max-usd` caps them) |
| `tr report` | one scorecard per arm and horizon (never pooled): Wilson win rate, mean r_net and real − shadow with a session-cluster bootstrap, MFE/MAE, MDE, P1 2x2, cost per run |
| `tr learn` | the playbook per horizon and setup type (thin cells flagged, never hidden); `--status` lists pre-registered rule changes with their paired sessions, the §8.3 rule and the MDE; `--decide CHANGE_ID` writes only a final decision; no model call |
| `tr slo` | the after-close SLOs from the first live session, 2026-11-17 (finished by 17:30 ET, zero missed sessions, fresh bars); exit 1 on a breach |
| `tr usage` | cost per call, run, arm or day from the trace |
| `tr bakeoff draw` / `report` | the date-seeded 4-name draw and the per-teacher report for the teacher bake-off |

`uv run python ci/gate.py` is the free CI gate (reconcile goldens and prompt hashes). `tests/test_week2.py` fails by design at `week-2-start`: it is your week-2 acceptance test. Likewise `tests/test_week4.py` is the week-4 acceptance test (tools, the tool loop, ADR-005, the first rule change; runbook "Week 4 acceptance"), `tests/test_week5.py` the week-5 one (per-section grounding, the context ablation, ADR-007, ADR-008; runbook "Week 5 acceptance"), and `tests/test_week6.py` the week-6 one (retrieval scoping, 30 labelled queries, the `citation_accuracy` grader, the retrieval experiment, ADR-009; runbook "Week 6 contract").

`tests/test_week7.py` is the week-7 acceptance test: your guardrail rules, the `injection_resisted` grader and its spec, 30 injections, the guards-off vs guards-on experiment, and ADR-010 (runbook "Week 7 contract"). Tags `week-7-start` and `week-7-end` mark the contract and the reference. Keys are scrubbed from the repo-written trace path (`redact.py`, ADR-004 Gaps). `uv run tr guards scan --dir DIR` exits 1 if any file under DIR holds a key.

`tests/test_week8.py` is the week-8 acceptance test: your `experiments/routing.toml` (a baseline arm, a routed arm and a cached arm) and ADR-011 with its pre-registration and result tables (runbook "Week 8: routing, caching and the batch judge"). It fails by design with `learner part missing:` until you write them.

Week 4 as measured (ADR-005, `experiments/tools-vs-fixed.toml`, 20 ticker-days): tools mode left `all_claims_valid` unchanged (0.100 → 0.100, 95% interval −0.200 to +0.200) at $0.026932 per analysis against $0.016968 fixed, so analyze keeps the fixed context; 12 of 20 tool loops were served by more than one provider (`openrouter:mixed(...)`).

Week 5 as measured (ADR-007, `experiments/context-ablation.toml`, 20 ticker-days, analyze-3): dropping headlines moved `claims_valid` +0.005 (95% interval −0.027 to +0.042) and dropping EDGAR +0.023 (−0.014 to +0.068), `parsed` 1.000 in every arm, so by the pre-registered rule both sections "go"; that is no measured loss, not a shown non-inferiority, and analyze's default (analyze-1) does not change. Headlines are 4.69% of the input tokens (139 of 2,963.7), EDGAR 17.96% (532.2); dropping EDGAR costs $0.015394 per analysis against $0.017192 full.

Week 6 as measured (ADR-009, `experiments/retrieval.toml`, 20 ticker-days, analyze-3 on Anthropic's API): adding the top 5 hybrid passages (BM25 and BAAI's bge-small-en-v1.5 by reciprocal rank fusion) moved `claims_valid` −0.038 (95% interval −0.081 to +0.008, whose lower bound misses the pre-registered −0.05 non-inferiority margin), and only 3 of 20 analyses cited a passage (`citation_accuracy` 1.000 on those 3), so the retrieval default stays `none`; a measured negative for this prompt, not evidence that passages hurt. Passages add 2,201.3 input tokens per analysis (74.3%) and cost $0.024861 per analysis against $0.017127 without.

Week 7 as measured (ADR-010, `experiments/injection.toml`, 30 blind injections, pipeline arms on Anthropic's API): attack success was 0.800 with the guards off and 0.767 with them on, a difference of 0.033 against the pre-registered 0.20, so the guards did not pass and the live `guards` setting stays empty. A clean rerun alone changed 0.500 of the theses, so the noise floor is large; false rejection was 0 of 10 clean items. The first attempt stopped on its budget pre-flight after $1.03 with no result; ADR-010 Amendment 1 raised the arm cap from $1.50 to $2.50.

Week 8 as measured (ADR-011, `experiments/routing.toml`, 60 ticker-days per arm, pipeline arms on Anthropic's API): routing the analyze step to Haiku 5.5 cut its cost by 92% and the cost per ticker-day by 41% ($0.0385 to $0.0225). `all_claims_valid` went from 0.767 to 0.800 with a 95% interval of -0.100 to +0.167, so the registered rule (lower bound at least -0.15) passes, but the interval is wide and 20 of 60 items disagreed between the arms, above the 0.22 the pre-registration had planned for, so the live loop stays on Sonnet 5.5. The prompt cache worked (12.7% off the analysis, 17.7% off the thesis); the fallback model was never used. The run spent $5.61.

## Prerequisites

All settings live in one file, `.env` at the repo root (git-ignored), copied from `.env.example`, which names every
variable and holds no value. `tr` reads it itself, so never `source` it; keys are read from the file only, never from
the shell. `TR_ENV_FILE=<path>` reads another file instead (the LaunchAgent uses `~/.config/tradingresearch/verify.env`).

| Variable | Needed for |
|---|---|
| `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | Alpaca bars and news (a paper account is enough) |
| `TR_SEC_USER_AGENT` | EDGAR: `"Your Name you@example.com"` |
| `TR_PROVIDER` | who serves the model calls: `openrouter` (default) or `anthropic` (runbook, "Providers") |
| `OPENROUTER_API_KEY` | model calls when `TR_PROVIDER=openrouter`, and the teachers whatever the provider |
| `ANTHROPIC_API_KEY` | model calls when `TR_PROVIDER=anthropic` |
| `TR_FEED` | `sip` (default) or `iex` |

Only the chosen provider's key is needed; a missing one stops the command with one line naming it.

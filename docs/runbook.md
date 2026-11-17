# Runbook

How the daily loop runs, how to check it, and what to do when it fails. Live stream day 1 is 2026-11-17.

## Schedule

`tr daily` runs from the LaunchAgent `com.tradingresearch.daily` (`~/Library/LaunchAgents/com.tradingresearch.daily.plist`):

| Setting | Value |
|---|---|
| When | Monday–Friday 14:30 and 19:00, Mac time zone America/Denver (16:30 and 21:00 New York). 19:00 is a catch-up |
| Program | `/Users/kar/.local/bin/uv run tr daily --teachers` (uv by absolute path; `--teachers` runs the bake-off) |
| WorkingDirectory | `/Users/kar/Developer/projects/tradingresearch-live` (the pinned worktree, below) |
| TR_DATA_DIR | `/Users/kar/Developer/projects/tradingresearch/data` (the live journal) |
| PATH | `/Users/kar/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin` |
| Log | `data/logs/daily.log` (stdout and stderr) |
| Keys | `tr` reads `~/.config/tradingresearch/verify.env` itself, including `TR_SEC_USER_AGENT`. No key goes in the plist |

launchd reads Hour/Minute in the Mac's time zone. If the Mac changes zone, or New York and Denver switch daylight
saving on different dates, the times must be converted again. `ops/daily.launchd.plist.example` is the template
(written for a Mac on New York time: 16:30 and a 21:00 catch-up); the installed agent has the same shape in Denver time.

The LaunchAgent owns live runs. To look at what a live run would do, use `--dry-run`.

## Pinned code, live data

The journal is append-only and the bake-off is pre-registered, so the code that writes the live journal must not
change under the stream. Two rules follow, and they are separate on purpose.

1. **The agent runs pinned code.** Its WorkingDirectory is the git worktree `~/Developer/projects/tradingresearch-live`,
   detached at a verified commit, with `TR_DATA_DIR=/Users/kar/Developer/projects/tradingresearch/data`. Editing
   or committing on master does not change what runs at 14:30.
2. **Dev never writes the live journal.** `<repo>/data/journal.db` is live evidence. Nothing writes to it except the
   agent: no `daily`, `analyze`, `thesis`, `reconcile`, `label`, `grade` (without `--dry-run`), `exp run` or
   `learn --decide`. Tests, experiments and packet runs use `TR_DATA_DIR=<repo>/data-dev` (git-ignored). Read-only
   commands (`report`, `usage`, `slo`, `--dry-run`) may read the live data.

Moving the pin, only to a commit whose tests and `ci/gate.py` pass, and never between 14:15 and 14:45 or between
18:45 and 19:15 America/Denver (the two run windows):

```sh
git -C ~/Developer/projects/tradingresearch-live checkout --detach <sha>
(cd ~/Developer/projects/tradingresearch-live && uv sync -q)
(cd ~/Developer/projects/tradingresearch-live && TR_DATA_DIR=/Users/kar/Developer/projects/tradingresearch/data uv run tr daily --teachers --dry-run)
```

Schema changes must be backward-safe for the pinned code (`CREATE TABLE IF NOT EXISTS`, new columns with defaults), or
land together with a pin move. A dev command that opens the live journal with newer code adds empty tables; the pinned
code ignores them. Code a change needs in a live run (for example the challenger arm, `rules.py`) does not run until
the pin moves past it: re-pin before registering a real rule change.

## What one run does

`tr daily` settles the latest completed session (after 16:15 ET) in five steps: screen the universe, analyze the
shortlist (`--top`, default 10), write one thesis-step decision per analysis, then reconcile and grade. Options:
`--session`, `--top`, `--max-usd` (default 1.00), `--dry-run` (free steps only, writes nothing), `--no-model`,
`--no-challenger`, `--teachers`, `--teacher-max-usd` (default 0.40).

- **Reruns are free.** Finished work prints `already done` and makes no model call, so the 19:00 catch-up only does
  what 14:30 missed. A holiday works the same way: the default session is the last completed one, already done.
- **Budget.** Each paid step is estimated before it runs (`daily.py`: $0.02 per analyze, $0.03 per thesis). If the
  estimate would take the run past `--max-usd`, the step gets a `stopped` row. 2026-11-16 measured $0.085262 for
  5 analyze calls and $0.104072 for 5 thesis calls.
- **Late.** Once the next entry window has opened (09:30 ET the next session), analyze and thesis are skipped with
  `late: the entry window after <session> opened at ... UTC`. A thesis written after its window opens would be
  hindsight.
- **Missed sessions** (no `daily_run` row in the last 10 trading days) get a `missed` row and are never backfilled.
- **Grade** (`tr grade`, no model call) builds each filled champion/challenger thesis's shadow and, once thesis and
  shadow are CLOSED, one Grade (r_net score, P2-P4). Its `daily_run` row is a `reconcile` row whose reason starts `grade: `.
- **P1 judge** (`tr grade --judge`, one model call per graded champion/challenger thesis without a verdict; never in
  `tr daily`). `openai/gpt-6-sol` (ADR-003), cap `--judge-max-usd` (default 0.25) for the whole run, cost counted
  from each call's run file even when the reply has no verdict (that thesis stays unjudged and is retried next run).
  `--dry-run --judge` lists what it would judge and makes no call. Verdict and reason are stored with the Score.
- The `events`, `thesis` and `daily_run` tables are append-only (triggers); nothing is corrected in place.
- **Challenger** (only while a rule change is pending and its `registered_at` is before the session's open; see
  "Playbook and rule changes"). Right after each champion thesis step, the challenger writes its own thesis-step
  decision on the same analysis under the change's rule (`rules.CHALLENGER_RULES[diff_ref]`: a post-filter or a
  prompt variant), at most one live thesis per arm and horizon. It runs only where the champion made a decision.
  Rows are `thesis` rows whose reason starts `challenger <change_id> (<analysis_id>): `; the step ends with
  `challenger <change_id> (<diff_ref>) <session>: ... answered ...`. Its cost is inside the run's total and
  `--max-usd` and is shown separately on that line; `--dry-run` adds it to the estimate. A challenger failure is a
  row and never changes the exit code; a rerun retries only analyses it has not answered. An unknown diff_ref fails
  every challenger row with `refused: ...` before any call. `--no-challenger`, `--no-model`, `late` and a budget stop
  leave `skipped`/`stopped` rows, and adopt.py leaves those sessions out (below). `tr thesis --arm challenger` does
  the same for one ticker by hand, but writes no `daily_run` row.
- **Teachers** (`--teachers`, off by default). After the evening's summary line, each of the 3 pinned teachers
  analyzes the session's 4 drawn names (`tr bakeoff draw`) and writes a thesis-step decision from its own analysis.
  Rows read `analyze <T> ... teacher <model>: ...` and the step ends with `teachers <session>: ...`. A teacher's first
  analysis of a name is never redone; reruns retry only failed or missing calls. Before each call, its worst case
  must fit what is left of `--teacher-max-usd` for the session (earlier runs count), or the step stops. A teacher
  failure is a row and never changes the exit code. There is no `late` skip: the teacher arm is never traded.

## Check that it ran

```
tail -20 data/logs/daily.log        # "daily <session>: N ok, ..." or "already done, no model call"; then "teachers ..."
launchctl list | grep tradingresearch   # second column is the last exit status
uv run tr usage --by day            # spend per New York day, then the key's lifetime spend
uv run tr slo                       # the SLOs for the latest live session tr daily ran for; exit 1 on a breach
uv run tr report                    # per-horizon scorecards from 2026-11-17; --horizon / --arm pick one
```

- **Live stream.** Live sessions start at `sessions.FIRST_SESSION` (2026-11-17). Earlier `tr daily` runs, theses and
  costs (the 2026-11-16 first run) are dev runs: `tr slo` and `tr report` leave them out unless asked.
- **SLOs** (`tr slo`, or `uv run python -m tradingresearch.slo_check`; reads the journal only). One line per SLO,
  then `slo <session>: k/3 met`. `finished`: the first run that reached reconcile ended by 17:30 ET on the session
  date, timed by its last non-teacher `daily_run` row (the teacher arm is not on the deadline). `missed`: 0 sessions
  with a `missed` row or no row at all in the last `--window` sessions (default 10), counted from the first run and
  from 2026-11-17. `fresh`: the session has a screen result, and every screened ticker has that session's daily bars
  on `TR_FEED`. `--inject-delay-minutes M` adds M minutes to the measured finish, to check the breach path without
  waiting. With no live run yet, `tr slo` prints `slo: no live session yet ...` and exits 0, until a live session's
  17:30 ET deadline passes with no run (then `BREACH missed`, exit 1). `--session D` checks another session; a
  session before 2026-11-17 gets a `pre-live:` first line. `--session 2026-11-16` breaches `finished`: that dev run
  ended at 23:21 ET.
- **Scorecards** (`tr report`, no model call). Header `report: live stream from 2026-11-17`, then one line counting
  and naming the earlier theses and `tr daily` runs it leaves out (`--include-pre-live` counts them too). One block
  per arm and horizon, never pooled: last-state counts,
  fill rate (filled ÷ (filled + expired)), abstention (no-trades ÷ main-analysis decisions for the horizon), and,
  over graded trades only, the Wilson win rate, mean r_net and real − shadow with a cluster bootstrap over entry
  sessions (`insufficient (n sessions < 10)` under 10 sessions), median MFE/MAE, the MDE line, and the P1 2x2 once
  P1 results exist. The last line is the cost per `tr daily` run from `daily_run.cost_usd`. Teacher theses never
  appear. With no graded trade, a card prints `no closed trades yet`.

## When something fails

| Symptom in the log | Meaning | Action |
|---|---|---|
| `screen - failed ...`, exit 1 | The screen step raised (the message after `failed` says why, e.g. a bars or EDGAR fetch); the only failure that ends the run | Fix the cause, then let the 19:00 catch-up run it |
| `journal failed: ...` | The database refused a write; everything stops | Do not edit `data/journal.db` by hand; read the error, fix the code or the disk, rerun |
| `analyze <T> failed` / `thesis <T> failed` | One model call failed; the rest of the run continues | Nothing; the cost is still recorded. Repeated failures: check `tr usage --by call` |
| `stopped budget: ...` | `--max-usd` reached | Expected on a long shortlist; raise `--max-usd` only on purpose |
| `failed teacher <model>: ...` | One teacher call failed (e.g. `model call failed: http_400`); exit code unchanged | Nothing; the next `--teachers` run retries it. Repeated: check the slug against OpenRouter |
| `stopped teacher <model>: budget: ...` | The next teacher call's worst case would pass `--teacher-max-usd` for the session | Nothing; raise `--teacher-max-usd` only on purpose, then rerun |
| `teachers <session>: stopped: ...` | The teacher step itself broke (e.g. the journal); the evening's rows are already stored | Read the error; rerun with `--teachers` |
| `late: the entry window ...` | The run came after 09:30 ET next session | Nothing; that session has no theses |
| `missed: <session>` | No run for a completed session | Nothing; it is not backfilled |

### Retries

Every HTTP call (Alpaca bars and news, EDGAR, OpenRouter calls, prices and key reads) goes through one policy,
`retry.DEFAULT`: up to 4 tries, a full-jitter wait of `uniform(0, min(30, 2**retry))` seconds, or the server's
`Retry-After` (seconds or a date) capped at 30 s, and never more than 300 s in all. Only 429, 5xx and connection or
timeout errors are retried; a 400, 401, 403 or 404, and any reply that arrived and parsed, fails at once. An error
after retries ends with `(gave up after N tries)` (or `; a Xs wait would pass the 300s budget`). A model call that
was retried records `retry_count` and `last_error_class` on its trace call, and its cost includes any cost a failed
try reported; a call that gives up names that amount in its error. Repeated `gave up` lines: check the provider's
status page before rerunning.

## Teacher bake-off

`tr daily --teachers` runs it. Session 1 is the first session on or after 2026-11-17 with a stored teacher analysis
(`sessions.FIRST_SESSION`, `experiments/bakeoff-prereg.toml`); earlier teacher analyses are tests and the report
ignores them. By hand, for one session D:

```
uv run tr bakeoff draw --session D       # the 4 names, seeded by the date
uv run tr analyze TICKER --session D --arm teacher --teacher MODEL
uv run tr thesis TICKER --session D --arm teacher --teacher MODEL
uv run tr bakeoff report                 # inputs to the pick rule; the operator picks
```

Measured teacher cost so far: `deepseek/deepseek-v4-pro`, one analyze call $0.004119 (run_7d0a596b94a44095) and one
thesis call $0.003016 (G6c's fixture capture, 2026-11-17).

## Experiment arms: `mode`

An arm may set `mode = "fixed"` (the default: the context goes in the prompt) or `mode = "tools"` (the model asks for
context with tool calls, week 4). Any other value fails `tr exp run` at config load. A `tools` arm is accepted but
`tr exp run` stops with `NotImplementedError: mode=tools: week 4 learner work` before the first model call, until the
tool loop exists. OpenRouter already carries the tools (fixture `tests/fixtures/tools/`).

## Labels (P1, blind)

Label after `tr grade` has graded a thesis; teacher theses are never labelled. ADR-003 asks for 30 labels before
agreement is read, spread across horizons where possible.

```
uv run tr label list                          # graded champion/challenger theses without a label
uv run tr label show TH_ID                    # thesis, cited claims, post-trade summary (reads Alpaca daily bars)
uv run tr label add TH_ID met|not_met|unknown --note "why"
uv run tr label add TH_ID not_met --relabel   # a new label pointing at the old one; the latest wins
uv run tr label agree                         # kappa vs stored judge verdicts once 2 pairs exist
```

Decide from `show` alone (rubric `evals/rubrics/p1_thesis_quality.md`); `show` never prints a judge verdict or an
earlier label. `agree` leaves out `unknown` labels and judge `unknown:` abstains and counts them. Its kappa
thresholds are PROPOSED (ADR-003, decision Q1) and nothing it prints sets `validated`.

## Playbook and rule changes (`tr learn`)

No model call. Only `--decide` writes, and only a final decision.

```
uv run tr learn                     # champion playbook as of the last completed session; --session D, --arm challenger
uv run tr learn --status            # rule changes, paired sessions so far, the decision rule, the MDE line
uv run tr learn --decide CHANGE_ID  # applies SPIKE §8.3; writes adopted/rejected/insufficient, else prints pending
```

- **Playbook.** One row per (horizon, setup_type) over graded theses of one arm whose CLOSED event is on or before
  the session: n, Wilson win rate, mean r_net with the session-cluster bootstrap (`insufficient (n sessions < 10)`),
  real − shadow, P1 met rate (unknown left out), median MFE/MAE. Rows with n < 5 say `THIN`. Teacher theses never
  enter.
- **Registering a change.** `rules.register(conn, RuleChange(..., diff_ref=..., prereg=journal.rule_prereg(horizon,
  hypothesis, registered_at), decided="pending"))`. `diff_ref` must be a key of `rules.CHALLENGER_RULES` (code
  reviewed; the two `example-` entries are examples, not proposals), else it is refused before anything is stored.
  The store refuses a Prereg that is not the §8.2 one (metric `session_r_net_delta:<horizon>`, pass rule
  `delta_ci_lower > 0`, guard `p1_met_rate`, margin 0.10, 20 pairs), a second pending change, and a `registered_at`
  that is not after the last decision or not before the first challenger thesis since it. Prereg fields never
  change; a decision is made once (SQLite triggers back this up).
- **Pairs.** From the first session that opens after `registered_at`: each main-analysis session on the change's
  horizon is one pair (summed r_net per arm, 0 with no trade). Pairs stop at the first session with a thesis that is
  not graded, expired or cancelled. The first 20 decide. Day 60 is 2027-01-15 (`adopt.DAY_60`); fewer than 20
  pairs by then is `insufficient`.
- **Sessions the challenger did not answer** (its `tr daily` row is failed, stopped or skipped, or it has none while
  the champion's are there) are no pair. Until the next entry window opens the session is the waiting one and the
  pairs stop there (rerun `tr daily` to retry); after that it is left out for good, the list goes on past it, and
  `--status` prints `left out N, the challenger never answered: <dates>`.

## Week 3 acceptance

`uv run pytest tests/test_week3.py -q` is the week-3 contract: it passes when the P1 judge, `tr grade --judge`,
`docs/adr/ADR-004-trace-policy.md`, `docs/slo-review.md` and `docs/measured-costs.md` exist and match it.

## CI

`uv run python ci/gate.py` is the free gate (no model call).

## Demo: free commands, 2026-11-17 04:46 UTC

Session 2026-11-16 was already run. None of these makes a model call or writes to the journal.

```
$ uv run tr screen --top 5
screen 2026-11-16  universe 10  regime bull-high  code screen-1+indicators-1  stored run, 10 rows (a re-run adds nothing)
rank ticker points triggers
   1 HD          3 level hvn 349.18 (-0.19 ATR); nr7; rel_volume 1.58
   2 JPM         2 level hvn 335.11 (+0.42 ATR); congestion 5d
   3 KO          2 level high_20 99.30 (+0.10 ATR); breakout high 99.30
   4 AMZN        1 level pivot_high 259.49 (-0.19 ATR)
   5 XOM         1 level hvn 168.75 (-0.44 ATR)
filtered 2 (atr_pct_high 2)
zero points 3

$ uv run tr reconcile --dry-run
AAPL swing PROPOSED unchanged  (th_d7359e73ebb947a4, champion)
  note: waiting: the entry window opens on 2026-11-17
...(HD swing, JPM short, JPM swing, XOM short, XOM swing: the same)
reconcile 2026-11-16: 6 subjects, 0 changed, 0 events, 0 teacher outcomes (dry run: nothing written)

$ uv run tr daily --dry-run          # exit 0
screen    -      ok      10 rows, shortlist 5  HD,JPM,KO,AMZN,XOM
analyze   HD     skipped already done (an_e733c04063e34b41)
...(JPM, KO, AMZN, XOM analyze and all six thesis steps: skipped already done)
reconcile -      ok      reconcile 2026-11-16: 6 subjects, 0 changed, 0 events, 0 teacher outcomes (dry run: nothing written)
daily 2026-11-16 (dry run): would analyze 0, thesis 0, estimated $0.00 (≈$0.02 per analyze, $0.03 per thesis); nothing written to daily_run

$ uv run tr usage --by day
day         calls  tokens in  tokens out       cost  mean latency
2026-11-16     78     206988       94054  $1.333396       9084 ms
total          78     206988       94054  $1.333396       9084 ms
openrouter key usage $61.997785
trace total $1.333396 vs key lifetime $61.997785 (the key also paid for runs outside data/runs, so the key is ≥ the trace total)

$ uv run tr bakeoff draw
bake-off draw 2026-11-16: AMZN HD KO XOM  (4 of a shortlist of 5, seeded by sha256 of 2026-11-16)
```

2026-11-16 is before bake-off session 1; the draw is shown only as an example.

# Runbook

How the daily loop runs, how to check it, and what to do when it fails. Live stream day 1 is 2026-11-17.

## Schedule

`tr daily` runs from the LaunchAgent `com.tradingresearch.daily` (`~/Library/LaunchAgents/com.tradingresearch.daily.plist`):

| Setting | Value |
|---|---|
| When | Monday–Friday 14:30 and 19:00, Mac time zone America/Denver (16:30 and 21:00 New York). 19:00 is a catch-up |
| Program | `/Users/kar/.local/bin/uv run tr daily` (uv by absolute path). With the bake-off: `... tr daily --teachers` |
| WorkingDirectory | `/Users/kar/Developer/projects/tradingresearch` |
| PATH | `/Users/kar/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin` |
| Log | `data/logs/daily.log` (stdout and stderr) |
| Keys | `tr` reads `~/.config/tradingresearch/verify.env` itself, including `TR_SEC_USER_AGENT`. No key goes in the plist |

launchd reads Hour/Minute in the Mac's time zone. If the Mac changes zone, or New York and Denver switch daylight
saving on different dates, the times must be converted again. `ops/daily.launchd.plist.example` is the template
(written for a Mac on New York time: 16:30 and a 21:00 catch-up); the installed agent has the same shape in Denver time.

The LaunchAgent owns live runs. To look at what a live run would do, use `--dry-run`.

## What one run does

`tr daily` settles the latest completed session (after 16:15 ET) in five steps: screen the universe, analyze the
shortlist (`--top`, default 10), write one thesis-step decision per analysis, then reconcile and grade. Options:
`--session`, `--top`, `--max-usd` (default 1.00), `--dry-run` (free steps only, writes nothing), `--no-model`, `--teachers`,
`--teacher-max-usd` (default 0.40).

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
- The `events`, `thesis` and `daily_run` tables are append-only (triggers); nothing is corrected in place.
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
uv run tr slo                       # the SLOs for the latest session tr daily ran for; exit 1 on a breach
uv run tr report                    # per-horizon scorecards; --horizon / --arm pick one
```

- **SLOs** (`tr slo`, or `uv run python -m tradingresearch.slo_check`; reads the journal only). One line per SLO,
  then `slo <session>: k/3 met`. `finished`: the first run that reached reconcile ended by 17:30 ET on the session
  date, timed by its last non-teacher `daily_run` row (the teacher arm is not on the deadline). `missed`: 0 sessions
  with a `missed` row or no row at all in the last `--window` sessions (default 10), counted from the first run.
  `fresh`: the session has a screen result, and every screened ticker has that session's daily bars on `TR_FEED`.
  `--inject-delay-minutes M` adds M minutes to the measured finish, to check the breach path without waiting.
  `--session D` checks another session. 2026-11-16 breaches `finished`: its first run ended at 23:21 ET.
- **Scorecards** (`tr report`, no model call). One block per arm and horizon, never pooled: last-state counts,
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

## Teacher bake-off

`tr daily --teachers` runs it. Session 1 is the first session on or after 2026-11-17 with a stored teacher analysis
(`bakeoff.FIRST_SESSION`, `experiments/bakeoff-prereg.toml`); earlier teacher analyses are tests and the report
ignores them. By hand, for one session D:

```
uv run tr bakeoff draw --session D       # the 4 names, seeded by the date
uv run tr analyze TICKER --session D --arm teacher --teacher MODEL
uv run tr thesis TICKER --session D --arm teacher --teacher MODEL
uv run tr bakeoff report                 # inputs to the pick rule; the operator picks
```

Measured teacher cost so far: `deepseek/deepseek-v4-pro`, one analyze call $0.004119 (run_7d0a596b94a44095) and one
thesis call $0.003016 (G6c's fixture capture, 2026-11-17).

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

# Runbook

How the daily loop runs, how to check it, and what to do when it fails. Live stream day 1 is 2026-11-17.

## Schedule

`tr daily` runs from the LaunchAgent `com.tradingresearch.daily` (`~/Library/LaunchAgents/com.tradingresearch.daily.plist`):

| Setting | Value |
|---|---|
| When | Monday–Friday 14:30 and 19:00, Mac time zone America/Denver (16:30 and 21:00 New York). 19:00 is a catch-up |
| Program | `/Users/kar/.local/bin/uv run tr daily` (uv by absolute path) |
| WorkingDirectory | `/Users/kar/Developer/projects/tradingresearch` |
| PATH | `/Users/kar/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin` |
| Log | `data/logs/daily.log` (stdout and stderr) |
| Keys | `tr` reads `~/.config/tradingresearch/verify.env` itself, including `TR_SEC_USER_AGENT`. No key goes in the plist |

launchd reads Hour/Minute in the Mac's time zone. If the Mac changes zone, or New York and Denver switch daylight
saving on different dates, the times must be converted again. `ops/daily.launchd.plist.example` is the template
(written for a Mac on New York time: 16:30 and a 21:00 catch-up); the installed agent has the same shape in Denver time.

The LaunchAgent owns live runs. To look at what a live run would do, use `--dry-run`.

## What one run does

`tr daily` settles the latest completed session (after 16:15 ET) in four steps: screen the universe, analyze the
shortlist (`--top`, default 10), write one thesis-step decision per analysis, then reconcile. Options: `--session`,
`--top`, `--max-usd` (default 1.00), `--dry-run` (free steps only, writes nothing), `--no-model`.

- **Reruns are free.** Finished work prints `already done` and makes no model call, so the 19:00 catch-up only does
  what 14:30 missed. A holiday works the same way: the default session is the last completed one, already done.
- **Budget.** Each paid step is estimated before it runs (`daily.py`: $0.02 per analyze, $0.03 per thesis). If the
  estimate would take the run past `--max-usd`, the step gets a `stopped` row. 2026-11-16 measured $0.085262 for
  5 analyze calls and $0.104072 for 5 thesis calls.
- **Late.** Once the next entry window has opened (09:30 ET the next session), analyze and thesis are skipped with
  `late: the entry window after <session> opened at ... UTC`. A thesis written after its window opens would be
  hindsight.
- **Missed sessions** (no `daily_run` row in the last 10 trading days) get a `missed` row and are never backfilled.
- The `events`, `thesis` and `daily_run` tables are append-only (triggers); nothing is corrected in place.

## Check that it ran

```
tail -20 data/logs/daily.log        # last line: "daily <session>: N ok, ..." or "already done, no model call"
launchctl list | grep tradingresearch   # second column is the last exit status
uv run tr usage --by day            # spend per New York day, then the key's lifetime spend
```

## When something fails

| Symptom in the log | Meaning | Action |
|---|---|---|
| `screen - failed ...`, exit 1 | The screen step raised (the message after `failed` says why, e.g. a bars or EDGAR fetch); the only failure that ends the run | Fix the cause, then let the 19:00 catch-up run it |
| `journal failed: ...` | The database refused a write; everything stops | Do not edit `data/journal.db` by hand; read the error, fix the code or the disk, rerun |
| `analyze <T> failed` / `thesis <T> failed` | One model call failed; the rest of the run continues | Nothing; the cost is still recorded. Repeated failures: check `tr usage --by call` |
| `stopped budget: ...` | `--max-usd` reached | Expected on a long shortlist; raise `--max-usd` only on purpose |
| `late: the entry window ...` | The run came after 09:30 ET next session | Nothing; that session has no theses |
| `missed: <session>` | No run for a completed session | Nothing; it is not backfilled |

## Teacher bake-off (by hand)

`tr daily` has no teacher step yet. For each bake-off session D (session 1 is the first on or after 2026-11-17 with a
stored teacher analysis; `experiments/bakeoff-prereg.toml`):

```
uv run tr bakeoff draw --session D       # the 4 names, seeded by the date
uv run tr analyze TICKER --session D --arm teacher --teacher MODEL
uv run tr thesis TICKER --session D --arm teacher --teacher MODEL
uv run tr bakeoff report                 # inputs to the pick rule; the operator picks
```

Measured teacher cost so far: one `deepseek/deepseek-v4-pro` analyze call, $0.004119 (run_7d0a596b94a44095).

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

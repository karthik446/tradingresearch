# SLO review (week 3)

An *SLI* is a number you measure; an *SLO* is the target you hold it to
(https://sre.google/sre-book/service-level-objectives/). The after-close loop has five: four from PLAN-60 week 3 and
`cost` from COST-6 (2026-11-18, addendum below). Four are checked by `tr slo` (`src/tradingresearch/slo_check.py`,
which reads the journal only: no model, no network); the fifth is that `tr slo` itself catches a late run.

Reviewed 2026-11-17 at about 01:20 ET, before the first live session closes. The live stream starts at
`sessions.FIRST_SESSION`, 2026-11-17, so **no live session exists yet** and every live number below is `awaiting
sessions`. The only run in the journal, 2026-11-16, is the pre-launch dev run; its numbers are shown as a labelled
example, not as a live measurement.

## The five SLOs

| SLO | Target | Measured on the live stream | Command | Earliest date |
|---|---|---|---|---|
| `finished` | the first `tr daily` run that reached reconcile ends by **17:30 ET** on the session date (timed by its last non-teacher `daily_run` row) | awaiting sessions | `uv run tr slo` | 2026-11-17 after 17:30 ET (the LaunchAgent runs `tr daily` at 16:30 ET, catch-up 21:00 ET) |
| `missed` | 0 missed sessions in the last 10 (`MISSED_WINDOW`): a `missed` row or no run at all, counted from 2026-11-17 | awaiting sessions | `uv run tr slo` (`--window N` to change 10) | first count 2026-11-17 after 17:30 ET; a full 10-session window on 2026-12-01 |
| `fresh` | the session has a screen result and every screened ticker has that session's daily bars on `TR_FEED` (`sip`) | awaiting sessions | `uv run tr slo` | 2026-11-17 after the 16:30 ET run |
| `cost` | the session's first `tr daily` run that paid for a step spent at most **$0.60** (`COST_BUDGET_USD`) on champion and challenger steps, summed from its `daily_run.cost_usd` rows, failed calls included; teacher steps are shown but not counted | awaiting sessions (this review predates the first live run; see the addendum) | `uv run tr slo` (`--budget-usd X` to change 0.60) | 2026-11-17 after the 16:30 ET run |
| injected-delay alert | adding a delay to a finish that met the deadline turns `finished` into `BREACH ... (+M min injected)` and exit 1 | awaiting sessions (the path is shown firing below, on the dev run) | `uv run tr slo --inject-delay-minutes 60` | the first live run that meets 17:30 ET, 2026-11-17 at the earliest |

The ten sessions of the first full `missed` window, from `uv run tr sessions --session 2026-12-01 --count 10`
(exit 0; open and close in UTC): 2026-11-17, -18, -19, -20, -23, -24, -25, -27 (half day, close 18:00Z), -30,
2026-12-01. 2026-11-26 is a holiday.

## Measured today

`tr slo` and `tr slo --inject-delay-minutes 60` on the live journal (`data/journal.db`), 2026-11-17 01:22 ET:

```
$ uv run tr slo
slo: no live session yet: the live stream starts 2026-11-17; the latest tr daily run (2026-11-16) predates it and is not checked
exit 0

$ uv run tr slo --inject-delay-minutes 60
slo: no live session yet: the live stream starts 2026-11-17; the latest tr daily run (2026-11-16) predates it and is not checked
exit 0
```

With no live run, `tr slo` exits 0 until a live session's 17:30 ET deadline passes with no run; then it prints
`BREACH missed` and exits 1 (`no_live_run` in `slo_check.py`). So the injected delay has nothing to act on yet.

The pre-live dev run, named with `--session` (the first line labels it):

```
$ uv run tr slo --session 2026-11-16
pre-live: 2026-11-16 predates the live stream (from 2026-11-17); a dev run, checked because --session named it
BREACH finished dy_4c43ee70dec141a7 finished 2026-11-16 23:21 ET  (target: by 17:30 ET on 2026-11-16)
ok     missed   0 of the last 1 sessions since 2026-11-16  (target: 0 in the last 10 sessions)
ok     fresh    10 of 10 screened tickers have 2026-11-16 bars  (target: a screen result for 2026-11-16 and sip daily bars for every screened ticker)
slo 2026-11-16: 2/3 met
exit 1

$ uv run tr slo --session 2026-11-16 --inject-delay-minutes 60
pre-live: 2026-11-16 predates the live stream (from 2026-11-17); a dev run, checked because --session named it
BREACH finished dy_4c43ee70dec141a7 finished 2026-11-17 00:21 ET (+60 min injected)  (target: by 17:30 ET on 2026-11-16)
ok     missed   0 of the last 1 sessions since 2026-11-16  (target: 0 in the last 10 sessions)
ok     fresh    10 of 10 screened tickers have 2026-11-16 bars  (target: a screen result for 2026-11-16 and sip daily bars for every screened ticker)
slo 2026-11-16: 2/3 met
exit 1
```

The injected line shows the alert path end to end: the delay is added to the measured finish, the line says how
much was injected, and the exit code is 1. Here the run had already breached, so the injection only moves a breach
later; that a delay turns a *met* finish into a breach is shown by `tests/test_slo.py`, and on the live stream
it waits for the first run that meets 17:30 ET.

## The 2026-11-16 breach: the pre-launch dev run

The breach is real: run `dy_4c43ee70dec141a7` reached reconcile at 23:21 ET, 5 h 51 min after 17:30. It is the
pre-launch dev run, not a live session, for a reason the repo records:

- `tr daily` did not exist until 23:19:48 ET on 2026-11-16: it was added by commit `febe6b9` ("G4a: tr daily
  (screen, analyze, thesis, reconcile; daily_run table; budget cap)"), dated 2026-11-16 21:19:48 -0700.
- The run's first `daily_run` row (screen) is stamped 2026-11-17T04:19:55Z, 23:19:55 ET, 7 seconds after that
  commit; its last (reconcile) is 04:21:39Z, 23:21:39 ET. The run took 1 min 44 s for screen, 5 analyze calls,
  5 thesis calls and reconcile:

  ```
  $ sqlite3 -readonly data/journal.db "SELECT daily_id, min(created_at), max(created_at), count(*), round(sum(cost_usd),6) FROM daily_run GROUP BY daily_id ORDER BY min(created_at);"
  dy_4c43ee70dec141a7|2026-11-17T04:19:55.466680+00:00|2026-11-17T04:21:39.918058+00:00|13|0.189334
  dy_c5823f6f31ea47b6|2026-11-17T04:43:40.708537+00:00|2026-11-17T04:43:40.714187+00:00|13|0.0
  exit 0
  ```

- Neither time is a LaunchAgent time (16:30 and 21:00 ET, `docs/runbook.md`), so it was started by hand, as the
  end-to-end check of the newly built loop. A second run, `dy_c5823f6f31ea47b6`, at 23:43:40 ET, found every step
  `already done` and cost $0. `data/logs/daily.log` holds that second run's output only, so the first run's own
  output is not in the log.

The 17:30 deadline could not be met on 2026-11-16 because the command was built after it. The run's length is no
warning sign: at 1 min 44 s, a run started by the LaunchAgent at 16:30 ET would end about 16:32 ET, 58 min inside
the target. That is arithmetic on one dev run, not a measurement; the first live measurement is after 17:30 ET on
2026-11-17.

## What the SLOs do not cover

- The alert is the exit code and the `BREACH` line of a command someone runs. The LaunchAgent runs `tr daily`, not
  `tr slo` (`docs/runbook.md`), so nothing runs the check on a schedule or notifies anyone. This holds for `cost`
  too: an overspent day is a `BREACH cost` line the next time someone types `tr slo`, not a message.
- `finished` times the first run that reached reconcile. A 16:30 ET run that fails before reconcile, rescued by the
  21:00 ET catch-up, is timed by the catch-up and breaches.
- `fresh` checks that bars exist for the session, not that their values are right.
- `cost` reads one run per session. What a catch-up or a rerun spent on the same session is not in the reading
  (`tr report` and `tr usage --by step` show it), and account burn across projects is not an SLI at all: that
  number lives on the provider's side (`GET /credits`, COST-3b) and needs the network, which `tr slo` never uses.

## Addendum, 2026-11-18 (COST-6): the `cost` SLO

The cost spike (COST-SPIKE A2) asked for a fourth checked SLI so that a day's spend is a met/breach reading and not
a number someone has to go and look up. `tr slo` now prints a `cost` line after `fresh`.

**What it measures.** The `daily_run` rows of the session's first run that recorded a paid step (`cost_usd > 0`),
in `seq` order. Champion and challenger rows are summed; teacher rows (reason starting `teacher `) are summed
separately and shown as `teacher steps $x more`, because `tr daily` pays them under `--teacher-max-usd`, not
`--max-usd`, and `finished` already leaves them out. Failed calls that were billed count: `cost_usd` is what the run
files say was paid. A later rerun or catch-up does not change the reading, whatever it cost. A session with no paid
row (no run, or only `$0` rows such as a `--no-model` rehearsal or a run refused before its first call) reads
`n/a    cost     no data: ...`; it is not counted in the `N/M met` total, which then ends `; no data: cost`, and it
does not set exit 1. `met` needs a paid run.

**Where the budget comes from.** There is no named daily budget in the product. The only per-run cap the code
enforces is `tr daily --max-usd`, an argparse literal `default=1.00` in `src/tradingresearch/commands/daily.py`,
and the LaunchAgent passes no `--max-usd` (`ops/daily.launchd.plist.example`), so live runs stop at $1.00. That is
a stop, not a promise, the way 17:30 ET is a promise that nothing enforces. The SLO target is the spike's $0.60
(COST-SPIKE 2.3: analyze $0.27 + thesis $0.36 per session at shortlist 10, from the measured per-call means with
headroom), kept as `COST_BUDGET_USD` in `slo_check.py` and overridable with `--budget-usd`. Two things to know
when tuning it: the spike's two parts add to $0.63, rounded to $0.60, and the challenger (`rc_1`, `docs/runbook.md`)
answers every analysis under the same `--max-usd` and was not in that arithmetic. The first live sessions will say
whether $0.60 holds; change the constant with a measured reason, not the first breach.

**What the lines would read [derived from recorded numbers, not rerun].** The pre-live dev run above
(`dy_4c43ee70dec141a7`) recorded $0.189334 over 5 analyze and 5 thesis calls and no teacher step, so
`tr slo --session 2026-11-16` now prints `ok     cost     dy_4c43ee70dec141a7 spent $0.189334 of $0.60 (teacher
steps $0.000000 more)` and its total `slo 2026-11-16: 3/4 met`. The first live run, 2026-11-17 16:30 ET, paid for
8 analyses (about $0.017 each) and one thesis with its challenger answer (about $0.021 and $0.022) before the
provider refused the other 7 theses on a low balance (COST-SPIKE 14:50 addendum); its `cost` line therefore reads
`met` at roughly $0.18 although 7 of its 8 theses failed. That is the point of separate verdicts: a cheap day is
not a good day, and `cost` says nothing about why a run stopped. Exact `met`, `BREACH` and `no data` output is
pinned by `tests/test_slo.py`.

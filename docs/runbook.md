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
| Log | `/Users/kar/Developer/projects/tradingresearch/data/logs/daily.log` (stdout and stderr) |
| Keys | `tr` reads `~/.config/tradingresearch/verify.env` itself, including `TR_SEC_USER_AGENT`. No key goes in the plist |

launchd reads Hour/Minute in the Mac's time zone. If the Mac changes zone, the times must be converted again.
`ops/daily.launchd.plist.example` is the template
(written for a Mac on New York time: 16:30 and a 21:00 catch-up); the installed agent has the same shape in Denver time.

The LaunchAgent owns live runs. To look at what a live run would do, use `--dry-run`.

## Pinned code, live data

The journal is append-only and the bake-off is pre-registered, so the code that writes the live journal must not
change under the stream. Two rules follow, and they are separate on purpose.

1. **The agent runs pinned code.** Its WorkingDirectory is the git worktree `~/Developer/projects/tradingresearch-live`,
   detached at a verified commit, with `TR_DATA_DIR=/Users/kar/Developer/projects/tradingresearch/data`. Editing
   or committing on master does not change what runs at 14:30.
2. **Dev never writes the live journal.** `<repo>/data/journal.db` is live evidence. Nothing writes rows to it except the
   agent: no `daily`, `analyze`, `thesis`, `reconcile`, `label`, `grade` (without `--dry-run`), `exp run` or
   `learn --decide`. Tests, experiments and packet runs use `TR_DATA_DIR=<repo>/data-dev` (git-ignored). Read-only
   commands (`report`, `usage`, `slo`, `--dry-run`) may read the live data.

   Who may write the live journal, and what (operator ruling 2026-11-17): the agent writes the daily rows. Two more
   writes are sanctioned and logged (what, when, spend), run by the coordinator from the pinned worktree with
   `TR_DATA_DIR=<repo>/data`: registering a rule change, once per change, and `grade --judge`. `tr split register` is
   the operator's decision (the cutoff): the coordinator registers it from the pinned worktree only on the operator's
   go through Main, once per split. **`label add` is human only** (so is `label --claims add`): the operator's labels
   are the ground truth the judge's kappa is measured against, and a label written by a model or a worker would make
   kappa model against model. `learn --decide` runs only after the operator's go (the decision is an ADR, at
   `n_planned`). Everything else stays on `data-dev`.

Moving the pin, only to a commit whose tests and `ci/gate.py` pass, and never between 14:15 and 14:45 or between
18:45 and 19:15 America/Denver (the two run windows):

```sh
git -C ~/Developer/projects/tradingresearch-live checkout --detach <sha> && (cd ~/Developer/projects/tradingresearch-live && uv sync -q)
(cd ~/Developer/projects/tradingresearch-live && TR_DATA_DIR=/Users/kar/Developer/projects/tradingresearch/data uv run tr daily --teachers --dry-run)
```

Schema changes must be new tables (`CREATE TABLE IF NOT EXISTS`), which the pinned code ignores. A change that adds,
alters or drops a column lands together with a pin move. A dev command that opens the live journal with newer code adds
its empty tables. Code a change needs in a live run (for example the challenger arm, `rules.py`) does not run until
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
context with tool calls, week 4). Any other value fails `tr exp run` at config load.

**Tools mode.** The user turn holds only the ticker and session; the model asks for rows with `get_indicators`,
`get_levels` and `get_fundamentals` (`src/tradingresearch/tools.py`, offline, over the same Context rows the fixed
table shows). A bad call comes back to the model as `{"error": ...}`, never as a crash. The loop stops at the first
reply without tool calls, or after `analyze.MAX_TOOL_TURNS` (5) calls with a failed sample (`max_tool_turns`), so
nothing is stored for that item. The budget is planned on each item's first request and every later call is reserved;
a refused reservation ends `tr exp run` with `BudgetExceeded`, as a fixed arm's does, and the trace keeps the items
done so far. A tools arm takes code graders only (a model grader is refused before the first call). The trace
(`data/traces/<run_id>.jsonl`) holds one `model_call` span per call, one `tool_call` span per tool call and the trial
span last; `tool_calls_ok` scores 0 for a tool error, a repeated call or more than 6 calls, and 1.0 for an arm with no
tool calls. `tr exp run` has no dry run; this prints a config's arms and graders with no call:

```
uv run python -c "from pathlib import Path; from tradingresearch import experiment as e; print(e.load(Path('experiments/tools-vs-fixed.toml')))"
```

## Experiment arms: `drop`

A fixed-mode arm may set `drop = ["edgar"]` (any of `indicators`, `levels`, `edgar`, the same split as the week-4
tools, and `headlines` under analyze-3) to hide those SOURCES rows from the model; the default `drop = []` sends the
prompt byte for byte as before. `tr exp run` refuses at config load a value that is not a list of section names, an
unknown section, `headlines` on a prompt that renders none, a section named twice, a list that names every section the
prompt shows, and `drop` on a tools arm.
Both arms share one dataset (the items keep the full prompt); `masking.Masked` removes the rows from each user turn
before the call, and a drop arm runs on the in-repo loop (as a tools arm does), so the trace's `request_sha256`,
`last_turn` and `Sample.input` hold the masked request. A drop arm takes code graders only. A stored analysis adds
the sorted drop list to its `input_hash` (unchanged when `drop` is empty), and a claim citing a dropped row is rejected
as `dropped_source`, so any inference derived from it falls too. `tr check` on a drop arm's analysis reads the rows
the call never showed from the run's `Sample.input` (in the item's table, absent from the masked user turn), names
them in a `drop arm: N SOURCES rows not shown to the model (<sections>)` line, marks each dropped `src:` line, and
gives the same `dropped_source` verdicts the store wrote.

## Headlines in the analyze prompt

`analyze-3` (the only prompt in `analyze.HEADLINE_PROMPTS`) is analyze-2 plus news rules: its SOURCES table ends with
the latest 5 stored headlines of the session's news window (previous session's close to this close, the look-ahead
guard of `tr news`), oldest first, one row each: `src_<digest> | headline 2026-11-13 15:05Z benzinga | "<text>" | -`.
The text has newlines, control and bidi/zero-width characters, variation selectors and tag characters turned into
spaces, `|` and `"` replaced, and a cap of 200 characters. Rows are read from `data/news/<TICKER>/`, never fetched:
run `tr news TICKER --session DATE` first; `tr exp run` with a headline arm refuses before the dataset and any call
when a ticker-day's news window was not fetched, listing those `tr news` commands. A claim about a headline is a fact
citing its source_id with `value: null` (a number is `unsourced_number`, digits in the text `number_in_text`); the
headline SourceRefs join the analysis's `input_hash` and are stored with it. analyze-1, analyze-2 and `tr daily` never
read the store, so their prompts and hashes are unchanged. Fixed arms of one experiment share a dataset, so they all
use a headline prompt or none, and no tool serves headlines, so a tools arm is refused next to a headline prompt (both
at load).
A thesis on an analyze-3 analysis shows, after the computed rows, the headline rows its claims cite (rendered by
analyze, same ids), read from the news store; a cited headline missing from the store refuses the thesis before the
call. Other analyses read nothing and their thesis prompts are unchanged. thesis-1 and thesis-2 have no rule telling
the model that a headline row is untrusted (prompts are immutable; a later thesis prompt adds it).
`experiments/headlines.toml` only records the prompt for `ci/gate.py`; the learner's ablation is its own file. The
headlines are untrusted text and analyze-3 says so, but nothing here stops an instruction phrased as a headline, a false
headline or a homoglyph: those are week 7 (`guards.py`, the injection set).

## Context ablation

`experiments/context-ablation.toml` (ADR-007) runs three fixed analyze-3 arms on one dataset: `full`, `no-headlines`
(`drop = ["headlines"]`) and `no-edgar` (`drop = ["edgar"]`), over AAPL, MSFT, NVDA, AMZN, JPM, XOM, UNH, HD, KO
and CAT on 2026-11-12 and 2026-11-13, clustered by ticker, graded by `parsed`, `claims_valid`, `all_claims_valid`
and the four `<section>_grounded` graders (`evals/specs/section_grounding.md`). Its header pre-registers the primary
metric (`claims_valid`), the guard (`parsed`) and the keep/drop rule. First fetch the news for all 20 ticker-days,
`tr news TICKER --session 2026-11-12` and `--session 2026-11-13` for each ticker (Alpaca, free); `tr exp run`
refuses before the dataset and any call while a window is missing and lists the commands. Days with no headline
are fine (on the 2026-11-17 fetch: UNH on both days, HD and CAT on 2026-11-12): those items send the same request in
`full` and `no-headlines`. Then `tr exp run experiments/context-ablation.toml`; it compares each drop arm with `full`
at the end, and `tr exp compare RUN_A RUN_B [--graders a,b]` prints the same block again from the stored runs ($0).
A drop arm never cites its dropped section, and two arms can cite one section on disjoint items; each such grader is
printed as `skipped <grader>: not scored in both arms (n=6 vs 0)` or `no item scored in both arms (n=1 vs 2)` and
the others are compared (`n=` on a metric line is the items it paired); only with no grader left is the compare
refused.
Cost: one recorded analyze-3 call (`tests/fixtures/week5/analyze3.reply.json`) was 2,714 prompt and 1,062 completion
tokens, $0.016048, so about 20 × $0.016 ≈ $0.32 per arm and about $1 for the three (an estimate; the drop arms send
fewer tokens), inside each arm's `CallBudget` of `max_usd_per_arm = 1.00`. Fill ADR-007's table from `compare`, with
the run ids.

## Provenance: the route

`provider_route` on an analysis or thesis says which upstream served the call; the teacher terms filter and the
fine-tuning set depend on it. `OpenRouter` logs the route of every call (`served`) under the exchange's first user
turn, so all turns of a tool loop count: one route as is (`openrouter:DeepInfra`), turns from different routes
`openrouter:mixed(Azure+Google)`, any turn with no provider `openrouter:unknown`. Each `routed()` arm keeps its own
log. A `trainable` (teacher) record with an unknown or mixed route is refused (`records.clean_route`); a teacher run
pinned to one host never hits this, so a refusal means the pin or the reply changed: look at the run's replies before
rerunning.

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

## Training split and claim labels

No model call. The training split (TRAINING-SPIKE §7.2 row 4) holds out a later period for the student-vs-teacher
gate (§7.3); register it before its cutoff session opens. Which cutoff to use is the operator's choice (TRAINING-SPIKE
§10 Q8).

```
uv run tr split register --cutoff YYYY-MM-DD --embargo 22 --note "hypothesis"   # a future NYSE session, embargo >= 22
uv run tr split register --cutoff YYYY-MM-DD --embargo 22 --prereg-json FILE    # your own Prereg, no registered_at
uv run tr split show [SPLIT_ID]               # train/val, embargoed and test sessions with counts (read-only)
uv run tr label --claims list                 # teacher claims without a claim label; n unlabelled, n labelled
uv run tr label --claims show CLAIM_ID        # claim text, value, cited source rows; never the model's tag
uv run tr label --claims add CLAIM_ID --tag fact|inference|opinion [--supported|--unsupported] --labeller NAME
```

The default Prereg is the §7.3 gate (claims_valid NoWorseThan, CI lower bound >= -0.15, 40 test sessions, guard
parse_ok Wilson lower bound >= 0.95). The split id is a digest of the cutoff, the embargo and the Prereg: registering
the same split again writes nothing, and a different split is a new row (nothing is rewritten). `show` without an id
reads the latest. The sessions are derived when you read them: train/val is before the embargo window (the
`--embargo` NYSE sessions before the cutoff), test is on or after the cutoff, and sessions inside the window are in
neither. The floor is 22: a swing thesis enters within the 2 sessions after it is written and exits at most 20
sessions after its entry, so with 22 the last train/val session's latest exit is the session before the cutoff and no
train/val outcome reads a test-period bar. (SPIKE §1.1 says 20; that was 2 sessions short.)

Claim labels are only for claims from teacher analyses (§7.4), one label per claim, and a second label is refused.
Label from `show` alone. The view is not fully blind. It leaks the fact/non-fact axis: a claim with cited source rows is
almost always a fact, and "none cited" means the model did not tag it a fact. It also prints the analysis id, and
`tr analyze` prints the model's tags. So the tagger's kappa on fact versus inference against these labels is
optimistic, and you should not run `tr analyze` (or look up the analysis) before labelling.

## Dataset release

No model call. `tr dataset publish` cuts the governing split's teacher analyses into a release (TRAINING-SPIKE §7.4).
One item is one analysis, as the teacher saw and wrote it, read from its run file.

```
uv run tr dataset publish --form private [--name teacher-sft] [--out DIR] [--split SPLIT_ID] [--teacher MODEL]
uv run tr dataset publish --form public                   # Alpaca prices and headlines as {{px:..}} / {{news:..}}
uv run tr dataset hydrate PUBLIC_DIR --out DIR             # refill from your own Alpaca keys; checks the private digest
```

The default output directory is `<TR_DATA_DIR>/release/<name>`. A directory that is not empty is refused. Each release
holds `<name>.train.jsonl`, `<name>.val.jsonl`, `DATASHEET.md`, `LICENSE` (CDLA-Permissive-2.0) and `SHA256SUMS`.

**Which rows go in.** Only trainable teacher-arm rows on a clean route from a pinned teacher, and only the first
analysis per ticker, session and model. A row also needs a run file and a reply with every claim valid (claims_valid 1).
Every teacher thesis on the row must pass P2-P4. Test-split and embargoed sessions are never written. Every excluded
row is counted by reason, both in the output and in the DATASHEET. val is the latest tenth of the item sessions.

**The private form** is verbatim and for personal use only, because Alpaca prices and headlines may not be
redistributed.

**The public form** replaces every Alpaca price and headline with a content-addressed placeholder. EDGAR and
scale-free rows ship verbatim. A price check scans each prompt and each free-text string: one price-looking number left
in refuses the whole publish and lists the item ids. Such an item blocks the public form, but not the private one.

**Hydrate** recomputes the rows from Alpaca the way `tr analyze` does and fills them in. The result must match the
private digests printed in the DATASHEET. If it does not, hydrate names the first differing item and writes nothing.
Bars corrected or split-adjusted since the session will fail this check.

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

## Playbook in the thesis prompt

`thesis-2` (the only prompt in `thesis.PLAYBOOK_PROMPTS`) is thesis-1 plus a PLAYBOOK block after the horizons: the
champion playbook as of the analysed session (`playbook.prompt_block`), one row per (horizon, setup_type) with n ≥ 5,
each a computed source `pb_<digest> | short | breakout_20d | 5 | 3/5 = 60.0% [..] | ...`; cells with n < 5 are one
`insufficient (n < 5, no rate shown)` line with no id, and no closed trade is one `PLAYBOOK: no closed trades yet`
line. A thesis cites rows in its own `playbook` list, never in `evidence` (P2 reads evidence as claims); an id not in
the block rejects the thesis (`unknown_playbook_row`). The block's digest joins the thesis `input_hash`; the cited ids
stay in the trace (not stored on the thesis). thesis-1 and `tr daily` are unchanged; a challenger runs thesis-2 only
through a registered `PromptVariant("thesis-2")` rule (none is in `rules.CHALLENGER_RULES` yet).
`experiments/playbook-in-prompt.toml` only records the prompt for `ci/gate.py`.

## Week 3 acceptance

`uv run pytest tests/test_week3.py -q` is the week-3 contract: it passes when the P1 judge, `tr grade --judge`,
`docs/adr/ADR-004-trace-policy.md`, `docs/slo-review.md` and `docs/measured-costs.md` exist and match it.

## Week 4 acceptance

`uv run pytest tests/test_week4.py -q` is the week-4 contract: it passes when `tradingresearch.tools`,
`analyze.analyze_with_tools`, the `tool_calls_ok` grader, a `mode="tools"` arm in `tr exp run`,
`experiments/tools-vs-fixed.toml`, `docs/adr/ADR-005-tools-vs-fixed-context.md` and the first rule change
`experiments/rule-change-1.toml` exist and match it. The loop is checked by replaying one recorded real exchange
(`tests/fixtures/week4/`, no key, no spend).

## Week 5 acceptance

`uv run pytest tests/test_week5.py -q` is the week-5 contract: it passes when the per-section grounding graders
(`indicators_grounded`, `levels_grounded`, `edgar_grounded`, `headlines_grounded`), `experiments/context-ablation.toml`,
`docs/adr/ADR-007-which-context-sections-stay.md` and `docs/adr/ADR-008-mcp-gateway-registry.md` exist and match it.
The ablation arms are checked by replaying one recorded real analyze-3 exchange (`tests/fixtures/week5/`, no key, no
spend).

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

# Measured costs (week 3)

SPIKE §9.2 budgeted every model step from token *estimates* (labelled INFERENCE there). This page replaces them with
measured usage: each call's tokens and cost as OpenRouter returned them in `usage` (its usage accounting:
https://openrouter.ai/docs/use-cases/usage-accounting), stored in the run file `data/runs/<run_id>.jsonl` and summed
by `tr usage` (ADR-004 says what else a run file holds). Models: analyze and thesis run on
`anthropic/claude-sonnet-5.5` (`DEFAULT_MODEL` in `analyze.py` and `thesis.py`), the judge on `openai/gpt-6-sol`
(`JUDGE_MODEL` in `evals.py`, ADR-003). Both cost $2 per million input tokens and $10 per million output tokens, the
prices SPIKE §9.2 used: HD's analyze call is 2,617 × $2/1e6 + 1,269 × $10/1e6 = $0.017924, its recorded cost, and
`tests/fixtures/week3/models.json` lists the judge's prices.

All measured rows come from the pre-launch dev run of 2026-11-16 and the calls around it. No live session has run
yet (the live stream starts 2026-11-17), so there is no live cost per day; `tr report` prints `cost per tr daily
run: no run recorded`.

## Per step

| Step | SPIKE §9.2 estimate | Measured | Measured ÷ estimate | Run ids |
|---|---|---|---|---|
| analyze, per ticker | 12,000 in / 2,000 out, $0.044 | mean of 5: 2,558.2 in / 1,193.6 out, $0.017052 (range $0.016208–$0.017924), mean latency 8,968 ms | cost 0.388; in 0.213, out 0.597 | run_3dbc0fb8a2dd433e (HD), run_e175b4239cc842e6 (JPM), run_b1d62689388040ee (KO), run_e1127b53ceef42c8 (AMZN), run_ad8e86350f1e43ae (XOM) |
| thesis, per ticker | 8,000 in / 1,500 out, $0.031 | mean of 5: 4,025.2 in / 1,276.4 out, $0.020814 (range $0.014856–$0.024198), mean latency 11,345 ms | cost 0.671; in 0.503, out 0.851 | run_ead2a5c981504849 (HD), run_bf90bfa5be2d4a28 (JPM), run_ce0a471158284c2a (KO), run_0225d8fcd3d94d29 (AMZN), run_cb7c0a237cd349b0 (XOM) |
| judge, per closed trade | 4,000 in / 500 out, $0.013 | 1 call: 1,558 in / 127 out, $0.005163, latency 4,350 ms; **a synthetic trade (FAKEA), not a live closed trade** | cost 0.397; in 0.390, out 0.254 | run_54953ec7ce484649 |
| daily, one `tr daily` run (analyze + thesis per shortlisted name) | shortlist 5: 5 × $0.075 = $0.375 (decided shortlist 10: $0.75) | **pre-launch dev run**, shortlist 5: $0.189334 = $0.085262 analyze + $0.104072 thesis; screen and reconcile $0 | 0.505 against shortlist 5 | dy_4c43ee70dec141a7 |
| learn, per week | 20,000 in / 3,000 out, $0.070 | not measured: no learn run exists in `data/runs` | — | — |

How each row was chosen:
- **analyze, thesis**: the 10 paid calls of `dy_4c43ee70dec141a7`, the only `tr daily` run that called a model,
  all on `anthropic/claude-sonnet-5.5`. Its sixth name, AAPL, was skipped as `already done
  (an_17f4a186735341a7)`: that analysis (`run_e72cabf720f94350`, $0.016488) and its thesis (`run_a85bcf2b033f48d7`,
  $0.019518) were made by hand before the run, and are left out so that the means are one run's calls.
- **judge**: no live trade has closed, so `tr grade --judge` has not judged one. The one measured judge call is the
  recording behind `tests/fixtures/week3/judge_request.json` and `judge_reply.json`: the P1 judge prompt on a
  synthetic FAKEA trade, run once on `openai/gpt-6-sol` with its run file under `data/scratch/g9c/` (git-ignored).
  Its prompt cost is $0.0038935, not 1,558 × $2/1e6 = $0.003116: 1,555 of the 1,558 input tokens were billed as
  cache writes at $2.50 per million (`judge_reply.json`, `usage.cost_details` and `prompt_tokens_details`). The 127
  output tokens include 49 reasoning tokens.
- **daily**: the estimate counts analyze + thesis per name, as SPIKE §9.2 does, so the measured run compares like
  for like. Per name: $0.189334 ÷ 5 = $0.037867, against $0.075. At the decided shortlist of 10, the same per-name
  cost gives 10 × $0.037867 = $0.378668 per day; that figure is arithmetic on one dev run, **an estimate**, not a
  measurement.

## Not in the per-step rows

| Run | Kind | Calls | Cost | Why not a step row |
|---|---|---|---|---|
| run_c40caab0968e44a3 | experiment, observe:baseline | 20 | $0.346798 | a `tr experiment` arm (10 tickers × 2 sessions), not the daily loop |
| run_c5fb0100989a4e0d | experiment, prompt-v2:baseline | 20 | $0.359398 | same |
| run_537a07e6ec264989 | experiment, prompt-v2:variant | 20 | $0.328348 | same |
| run_7d0a596b94a44095 | teacher-adapter analyze, KO | 1 | $0.004119 | `deepseek/deepseek-v4-pro` pinned to DeepInfra; the teacher arm is off by default in `tr daily` |
| run_d0ce65a31baa4ae5 | teacher-adapter analyze, AAPL | 1 | $0.003797 | same |
| run_33e3b0d8276941f9, run_2cdfc998ac874c5b, run_bb1d8e9cdd464cff, run_10fc0a886ddb42a2 | analyze, AAPL and MSFT 2026-11-13 | 1 each | $0.016008–$0.017304 | hand runs before `tr daily` existed |

The SPIKE §9.2 sanity line (the build-guide pilot, $0.0160–0.0173 per analyze call at about 2,500 in / 1,100 out)
matches the measured analyze calls. The 12,000-token analyze estimate counted 3,000 tokens of headlines and an
8-K list; the measured analyze prompt's source rows are indicators, levels and EDGAR facts, with no headline rows
(read from the trace of `run_3dbc0fb8a2dd433e`).

## The commands and their output

```
$ uv run tr usage
run                   kind     arm                 calls  tokens in  tokens out       cost
run_33e3b0d8276941f9  analyze  -                       1       2496        1123  $0.016222
run_2cdfc998ac874c5b  analyze  -                       1       2496        1107  $0.016062
run_bb1d8e9cdd464cff  analyze  -                       1       2534        1094  $0.016008
run_10fc0a886ddb42a2  analyze  -                       1       2672        1196  $0.017304
run_c40caab0968e44a3  exp      observe:baseline       20      50754       24529  $0.346798
run_c5fb0100989a4e0d  exp      prompt-v2:baseline     20      50754       25789  $0.359398
run_537a07e6ec264989  exp      prompt-v2:variant      20      52854       22264  $0.328348
run_e72cabf720f94350  analyze  -                       1       2469        1155  $0.016488
run_a85bcf2b033f48d7  thesis   -                       1       4034        1145  $0.019518
run_d0ce65a31baa4ae5  analyze  -                       1       1499        1076  $0.003797
run_3dbc0fb8a2dd433e  analyze  -                       1       2617        1269  $0.017924
run_e175b4239cc842e6  analyze  -                       1       2680        1156  $0.016920
run_b1d62689388040ee  analyze  -                       1       2483        1221  $0.017176
run_e1127b53ceef42c8  analyze  -                       1       2534        1114  $0.016208
run_ad8e86350f1e43ae  analyze  -                       1       2477        1208  $0.017034
run_ead2a5c981504849  thesis   -                       1       3948        1387  $0.021766
run_bf90bfa5be2d4a28  thesis   -                       1       4050        1510  $0.023200
run_ce0a471158284c2a  thesis   -                       1       4013         683  $0.014856
run_0225d8fcd3d94d29  thesis   -                       1       3941        1217  $0.020052
run_cb7c0a237cd349b0  thesis   -                       1       4174        1585  $0.024198
run_7d0a596b94a44095  analyze  -                       1       1509        1226  $0.004119
total                                                 78     206988       94054  $1.333396
openrouter key usage $62.005975
trace total $1.333396 vs key lifetime $62.005975 (the key also paid for runs outside data/runs, so the key is ≥ the trace total)
exit 0
```

Excerpt, the 2026-11-16 call lines (the full output also lists the 60 experiment calls on 2026-11-12 and -13):

```
$ uv run tr usage --by call --since 2026-11-16
call                                           calls  tokens in  tokens out       cost  mean latency
...
run_e72cabf720f94350 AAPL:2026-11-16               1       2469        1155  $0.016488       7868 ms
run_a85bcf2b033f48d7 AAPL:2026-11-16:champion      1       4034        1145  $0.019518      11171 ms
run_d0ce65a31baa4ae5 AAPL:2026-11-16               1       1499        1076  $0.003797      14029 ms
run_3dbc0fb8a2dd433e HD:2026-11-16                 1       2617        1269  $0.017924       9660 ms
run_e175b4239cc842e6 JPM:2026-11-16                1       2680        1156  $0.016920       8803 ms
run_b1d62689388040ee KO:2026-11-16                 1       2483        1221  $0.017176       9661 ms
run_e1127b53ceef42c8 AMZN:2026-11-16               1       2534        1114  $0.016208       7837 ms
run_ad8e86350f1e43ae XOM:2026-11-16                1       2477        1208  $0.017034       8881 ms
run_ead2a5c981504849 HD:2026-11-16:champion        1       3948        1387  $0.021766      14387 ms
run_bf90bfa5be2d4a28 JPM:2026-11-16:champion       1       4050        1510  $0.023200      11838 ms
run_ce0a471158284c2a KO:2026-11-16:champion        1       4013         683  $0.014856       6414 ms
run_0225d8fcd3d94d29 AMZN:2026-11-16:champion      1       3941        1217  $0.020052      11559 ms
run_cb7c0a237cd349b0 XOM:2026-11-16:champion       1       4174        1585  $0.024198      12525 ms
run_7d0a596b94a44095 KO:2026-11-16                 1       1509        1226  $0.004119      10842 ms
total                                             78     206988       94054  $1.333396       9084 ms
exit 0
```

```
$ TR_DATA_DIR=data/scratch/g9c uv run tr usage --by call
call                                 calls  tokens in  tokens out       cost  mean latency
run_54953ec7ce484649 FAKEA:p1_judge      1       1558         127  $0.005163       4350 ms
total                                    1       1558         127  $0.005163       4350 ms
exit 0
```

The daily run's cost and steps, from the journal and the scorecard (`--include-pre-live` counts the dev runs; the
second run, `dy_c5823f6f31ea47b6`, cost $0 because every step was already done, which halves the mean):

```
$ sqlite3 -readonly data/journal.db "SELECT step, ticker, status, substr(reason,1,110), cost_usd FROM daily_run WHERE daily_id='dy_4c43ee70dec141a7' ORDER BY seq;"
screen||ok|10 rows, shortlist 5|0.0
analyze|HD|ok|7 claims, 5 rejected|0.017924
analyze|JPM|ok|7 claims, 4 rejected|0.01692
analyze|KO|ok|10 claims, 2 rejected|0.017176
analyze|AMZN|ok|8 claims, 3 rejected|0.016208
analyze|XOM|ok|11 claims, 1 rejected|0.017034
thesis|AAPL|skipped|already done (an_17f4a186735341a7)|0.0
thesis|HD|ok|accepted 1, no_trade 2, rejected 0|0.021766
thesis|JPM|ok|accepted 2, no_trade 1, rejected 0|0.0232
thesis|KO|ok|accepted 0, no_trade 3, rejected 0|0.014856
thesis|AMZN|ok|accepted 0, no_trade 3, rejected 0|0.020052
thesis|XOM|ok|accepted 2, no_trade 1, rejected 0|0.024198
reconcile||ok|reconcile 2026-11-16: 6 subjects, 0 changed, 0 events, 0 teacher outcomes (appended)|0.0

$ uv run tr report --include-pre-live      (last line)
cost per tr daily run: 2 runs, total $0.189334, mean $0.094667, max $0.189334; teacher steps $0.000000 of the total

$ uv run tr report                          (last line)
cost per tr daily run: no run recorded
```

Both `tr report` commands exit 0. `tr usage` reads only the run files on disk (plus one free `GET /key` for the
key's lifetime spend); none of these commands makes a model call.

## Week 4: tools vs fixed context

One run of `experiments/tools-vs-fixed.toml` on 2026-11-17 under `TR_DATA_DIR=data-dev` (ADR-005 has the
decision): the same 20 ticker-days, analyze-1 on `anthropic/claude-sonnet-5.5`, one arm with the SOURCES table up
front and one asking for rows with tools. All measured, from `tr usage` on that data directory; per-item latency is
the sum of the item's model-call `latency_ms` in the trace.

| Arm | Run id | Items | Model calls | Tokens in | Tokens out | Cost | Per item: tokens in / out, cost, latency |
|---|---|---|---|---|---|---|---|
| fixed | run_a24247c2a8b54462 | 20 | 20 | 50,754 | 23,785 | $0.339358 | 2,537.7 / 1,189.25, $0.016968, 8,344.5 ms |
| tools | run_e80dcfcca6294408 | 20 | 41 | 141,082 | 25,647 | $0.538634 | 7,054.1 / 1,282.35, $0.026932, 10,929.15 ms |

The fixed arm matches the week-3 analyze row (mean of 5: 2,558.2 in / 1,193.6 out, $0.017052). The tools arm costs
1.59 times as much per item: each of its 2.05 calls per item re-sends the conversation, so input tokens are 2.78
times the fixed arm's while output grows by 7.8% (1,282.35 ÷ 1,189.25 = 1.078). The key's lifetime spend moved from
$62.028863 to $62.906855 across the run, $0.877992, equal to the trace total.

```
$ TR_DATA_DIR=data-dev uv run tr usage --by arm
arm                   calls  tokens in  tokens out       cost  mean latency
tools-vs-fixed:fixed     20      50754       23785  $0.339358       8344 ms
tools-vs-fixed:tools     41     141082       25647  $0.538634       5331 ms
total                    61     191836       49432  $0.877992       6319 ms
```

`--by arm` prints latency per call; the tools arm's 5,331 ms per call × 41 calls ÷ 20 items is the 10,929 ms per item
above.

## Week 5: context ablation

One run of `experiments/context-ablation.toml` on 2026-11-17 under `TR_DATA_DIR=data-dev` (ADR-007 has the result
and the decision): the same 20 ticker-days, analyze-3 on `anthropic/claude-sonnet-5.5`, one call per item, three arms
that differ only in the SOURCES rows masked out of the request. All measured, from `tr usage` on that data directory;
per-item latency is the item's model-call `latency_ms` in the trace.

| Arm | Run id | Items | Model calls | Tokens in | Tokens out | Cost | Per item: tokens in / out, cost, latency |
|---|---|---|---|---|---|---|---|
| full | run_c32ea07781a54982 | 20 | 20 | 59,274 | 22,529 | $0.343838 | 2,963.7 / 1,126.45, $0.017192, 8,028.95 ms |
| no-headlines | run_acb9119f015e4911 | 20 | 20 | 56,494 | 22,459 | $0.337578 | 2,824.7 / 1,122.95, $0.016879, 7,812.75 ms |
| no-edgar | run_95536ffe7c5e4b78 | 20 | 20 | 48,630 | 21,061 | $0.307870 | 2,431.5 / 1,053.05, $0.015394, 7,434.85 ms |

Each request differs from `full`'s only by the masked rows, so the per-item difference in input tokens is what those
rows cost: headlines 139.0 tokens per item (4.69% of `full`'s input; 5.83% over the 16 days with headlines, 0 on the
4 without), EDGAR 532.2 (17.96%, 471 to 550 on every day). analyze-3 `full` costs 1.3% more per item than week 4's
analyze-1 fixed arm ($0.017192 against $0.016968) on 16.8% more input tokens (2,963.7 against 2,537.7). The three arms
total $0.989286 in the traces.

```
$ TR_DATA_DIR=data-dev uv run tr usage --by arm
arm                            calls  tokens in  tokens out       cost  mean latency
context-ablation:full             20      59274       22529  $0.343838       8029 ms
context-ablation:no-headlines     20      56494       22459  $0.337578       7813 ms
context-ablation:no-edgar         20      48630       21061  $0.307870       7435 ms
```

(The same command also lists the two week-4 arms in that data directory; they are left out above.)

The key's lifetime spend read $62.922903 before the run and $63.896139 at the last read after it (two reads several
minutes apart agreed), a delta of $0.973236, $0.016050 below the trace total; earlier reads after the run were lower
still ($63.643149, $63.741341). The key lags the traces, so the trace total, $0.989286, is the measured cost.

## Week 6: retrieval

One run of `experiments/retrieval.toml` on 2026-11-17 (UTC 2026-11-18) under `TR_DATA_DIR=data-dev` with
`TR_PROVIDER=anthropic` (ADR-009 has the result and the decision): the same 20 ticker-days, analyze-3 on Anthropic's
API directly (route `anthropic:claude-sonnet-5-5` on all 40 stored analyses), one call per item. `none` sends week
5's `full` prompt; `hybrid` adds the top 5 hybrid passages from the pinned index. Tokens and latency are measured,
from `tr usage` on that data directory; per-item latency is the item's model-call `latency_ms` in the trace. Cost is
derived from those tokens by the adapter's Anthropic price table (ADR-014), not reported by the provider: Anthropic
has no key-spend endpoint, so there is no key reading to reconcile against.

| Arm | Run id | Items | Model calls | Tokens in | Tokens out | Cost | Per item: tokens in / out, cost, latency |
|---|---|---|---|---|---|---|---|
| none | run_3cb557202363406d | 20 | 20 | 59,274 | 22,399 | $0.342538 | 2,963.7 / 1,119.95, $0.017127, 8,084.9 ms |
| hybrid | run_83464659837d44e8 | 20 | 20 | 103,300 | 29,062 | $0.497220 | 5,165.0 / 1,453.1, $0.024861, 10,439.3 ms |

Each `hybrid` request differs from `none`'s only by the passage block, so the per-item difference in input tokens is
what the passages cost: 2,201.3 tokens per item (74.3% of `none`'s input), 2,050 to 2,422 on every day. Output grew
by 29.7% (1,453.1 ÷ 1,119.95 = 1.297) and cost per analysis by 45.2% ($0.024861 ÷ $0.017127 = 1.452); latency per
item rose by 2,354.4 ms. `none` sends as many input tokens as week 5's `full` arm on every item (2,963.7 per item on
average) and costs $0.017127 against $0.017192 there. The two arms total $0.839758: the trace total read $2.331739
before the run and $3.171497 after it.

```
$ TR_PROVIDER=anthropic TR_DATA_DIR=data-dev uv run tr usage
run_3cb557202363406d  exp      retrieval:none                    20      59274       22399   $0.342538
run_83464659837d44e8  exp      retrieval:hybrid                  20     103300       29062   $0.497220
```

(Two rows of the per-run table; the rest of the data directory's runs are left out above.)

The first, void attempt (ADR-009 Amendment 1, on OpenRouter) cost $0.3306 for `none` and $0.1012 for 4 of 20
`hybrid` items before the account's balance ran out; it is not used above.

## Week 7: injection and guards

One run of `experiments/injection.toml` (ADR-010): five pipeline arms, each item an analysis call then a thesis call on
Anthropic's API, `TR_PROVIDER=anthropic`, cost derived from the adapter's price table. Run output
`data-dev/scratch/w7refb/run2.txt`, recomputed from the stored run files by an independent read (`$3.708214` in all).

| Arm | Items | Spend (analysis + thesis) | Per item |
|---|---|---|---|
| clean | 10 | $0.3708 | $0.0371 |
| injected-off | 30 | $1.3113 | $0.0437 |
| injected-on | 30 | $1.2562 | $0.0419 |
| clean-on | 10 | $0.3896 | $0.0390 |
| clean-rerun | 10 | $0.3803 | $0.0380 |

An injected item costs more than a clean one (about $0.042 against $0.038) because the added headline lengthens the
prompt and the reply. The first attempt stopped in the thesis stage of `injected-off` (the budget preflight reserves
each call's worst case, $1.011862 for 30 thesis calls, against $0.855998 left of a $1.50 arm cap) and spent
$1.029382 before it stopped (ADR-010 Amendment 1); the cap is now $2.50 an arm. The GUARDS-SPIKE estimate was $3.6
for the five arms; the measured total is $3.71 for the run plus $1.03 for the stopped attempt.

## Week 8: routing and caching

One run of `experiments/routing.toml` (ADR-011): three pipeline arms over 10 tickers x 6 sessions (60 items each), each
item an analysis call then a thesis call on Anthropic's API, `TR_PROVIDER=anthropic`, cost derived from the adapter's
price table (the Console's billed amount was not read). Run output `data-dev/scratch/w8refb-run.txt`; per-run rows from
`tr usage --by step --run RUN_ID`.

| Arm | Analysis run | Analysis cost | Thesis run | Thesis cost | Spend | Per ticker-day |
|---|---|---|---|---|---|---|
| sonnet | run_1eba503380b7444c | $1.0304 | run_b7a046db477e4359 | $1.2783 | $2.3086 | $0.0385 |
| routed | run_98681aba3fe24a79 | $0.0858 | run_80c8bf85db874007 | $1.2659 | $1.3517 | $0.0225 |
| cached | run_0311bd3c03344a3a | $0.8990 | run_073c4b1e547f4930 | $1.0525 | $1.9515 | $0.0325 |

The run spent $5.6118 in all against about $5.4 expected (G15 spike §2); the arm cap was $5.50 and the plan's worst
case $5.270661 per arm. Haiku 5.5 on the analyze step cost 92% less than Sonnet 5.5 (135,389 output tokens against
66,809, input tokens equal at 181,139), and the thesis step did not move. The cached arm wrote 1,216 cache tokens once
and read 71,744 on the analyze step (2,112 written and 124,608 read on the thesis step), so the analyze block is long
enough to cache. The fallback model answered none of the 60 routed analysis calls.

# Week 4 labs: the folder

This folder holds week 4 of the AI engineering track, run by `tr lab` on this repo from the tag `week-4-start`. Part A is 6 exercises in labs w4l1 (three tools the model can use) and w4l2 (the tool loop), the code of the chapter's §2 and §3. Part B, labs w4l3 and w4l4, is not in the folder yet: it adds the tools arm in the experiment runner, the `tool_calls_ok` grader, route provenance and the first rule change. A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

## Exercises

| Exercise | What the learner does | Edits | Wrong fixes |
|---|---|---|---|
| [w4l1.1](exercises/w4l1.1-closed-schemas/) | Close every tool's schema and describe every argument | `tools.py` | 10 |
| [w4l1.2](exercises/w4l1.2-errors-the-model-reads/) | Turn every bad call into an error the model can read | `tools.py` | 9 |
| [w4l1.3](exercises/w4l1.3-the-rows-it-cites/) | Return the rows a claim cites, with the numbers the table shows | `tools.py` | 11 |
| [w4l2.1](exercises/w4l2.1-only-the-ticker-and-the-tools/) | Send only the ticker and the session, and offer the tools | `analyze.py` | 7 |
| [w4l2.2](exercises/w4l2.2-answer-every-tool-call/) | Answer every tool call, then call again | `analyze.py` | 7 |
| [w4l2.3](exercises/w4l2.3-the-cap-and-the-trace/) | Cap the loop and keep every span in the trace | `analyze.py` | 8 |

Part A: 52 wrong fixes. 26 are `before: RED (author)`, written with the exercise. The other 26 come from a break pass run after each exercise passed, at least three per exercise: in w4l1, a colliding tool name, an empty list allowed, a short enum, a level tool with no properties, any string as a metric, a required `names`; an error as plain text or beside rows, a non-object or unchecked value let through; an error that lists no names, a label on every row or on none, a `names` filter over every row, six digits always, a value as text. In w4l2, no line saying where the rows are, a reworded session line, two tools offered; an answer that then stops, answers in reverse order, no tool spans; a failed call's span dropped, a refusal swallowed, every span written after the loop. 25 were red when first tried. One passed: `spans-at-the-end` (w4l2.3, `before: GREEN (break pass)`) writes every span to the trace after the loop, in the right order. The check was hardened for it (the spending-cap test now requires the first call's model and tool spans in the trace after the refusal), and all 52 are red now.

## Layout

```
labs/w4/
  lab.toml                   base = "week-4-start", lab titles and pages, [unlock], [suite] deselect, [labs.w4l1.suite] deselect, [end]
  conftest.py                marks every test in this folder `lab` (plain `pytest -q` never collects them) and installs the offline guard before any test module imports learner code
  data/fakea.context.json    the FAKEA ticker-day context: session 2026-11-13, 38 source rows
  data/turn1.request.json    the recorded exchange's first request (one tool offered, get_sources) and
  data/turn1.reply.json        its reply, which calls get_sources once
  data/turn2.request.json    the second request (the call answered) and
  data/turn2.reply.json        its reply, the final JSON with 11 claims
  pages/                     index.md, w4l1.md, w4l2.md (one page per lab), concepts.md
  tools/offline.py           the offline guard: socket connections and DNS, subprocesses, os spawns and the real httpx transports raise Blocked and are counted
  tools/fakea.py             the FAKEA context, replayed replies through the real OpenRouter adapter, a spending cap that refuses, and the schema check the w4l1.1 checks use ($0, no network)
  tools/observe.py           observe: `tools` (w4l1) and `loop` (w4l2), always exits 0; installs the offline guard first
  exercises/w4lN.K-<slug>/
    exercise.toml            id, title, effect, goal, what_tested, writes, show_tests, lab, concepts, touches, check, observe, paid, fixtures, origin, red_expect
    stub/                    the week-4-end file the exercise touches (`src/tradingresearch/tools.py` in w4l1, `analyze.py` in w4l2) with this exercise's code and the later ones cut out
    test_w4lN_K.py           the check; its assertion messages are the FAIL messages
    hints.md                 two hints, each under a `## Hint N` heading: the idea and a counterexample, no code
    solution.diff            the reference change, applied with `git apply` on the stub
    wrong/*.diff             known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

`PROOF.md` and each exercise's `expected_output/` (`fail.txt`, the stub's red run, and `pass.txt`, the solution's green run) are not in the folder yet: they are written by the commands in [Prove the folder](#prove-the-folder) once the folder's review is done. Week 4 has no `session/`.

**The base.** `base = "week-4-start"` makes the first `tr lab start w4l1` set the repo's files to that tag and commit them, so week 4 does not depend on the learner's week-3 code. `week-4-start` has no `tools.py`, and its `analyze.py` has no `tools_prompt` and no `analyze_with_tools`. The w4l1.1 stub brings in the week's `tools.py` with the schemas, the error handling, the cited row and the `names` filter cut out; the w4l2.1 stub brings in the week's `analyze.py` with `tools_prompt`, the tools on the request, the answers, the cap and the span writes cut out. `MAX_TOOL_TURNS`, `_model_span` and `_tool_span` come with it.

**The data.** All five files in `data/` are byte copies of the repo's `tests/fixtures/week4/` at `week-4-start`. Only the two replies are model output: one exchange recorded on 2026-11-17 with `anthropic/claude-sonnet-5.5`, offered the capture's own tool `get_sources(groups)` with `tool_choice` auto. It called the tool once and answered with 11 claims on the second call; the two calls cost $0.022888 (the chapter's §2 has the turn-by-turn numbers). The capture's tool is not one of the three the labs build, so the exchange can only be replayed with `get_sources` put back (`fakea.capture_tool`).

**The replay.** `tools/fakea.py` swaps the OpenRouter adapter's HTTP transport for an `httpx.MockTransport`, and `fakea.replaying` answers request i with `answer(replies[i])`: `turn1` and `turn2` (the recording), `three_calls` (the first reply edited to ask for `get_indicators`, `get_levels` and `get_fundamentals` at once), `one_more` (one more `get_indicators` call), `failed` (an HTTP 400) and `busy` (an HTTP 503, which the adapter retries once). From the 13th request on (`STOP_AFTER = 12`) the replay answers HTTP 400, so a loop with no cap still ends under the lab checks and observe. `fakea.Capped` is a spending cap that refuses after a given number of calls with `BudgetExceeded`. `fakea.context(extra=True)` gives every value extra digits (a close of 101.40124722), to tell a tool that rounds the way the SOURCES table does from one that does not.

**The offline guard.** The labs claim $0 and no network, so `tools/offline.py` enforces it: `conftest.py` installs it before any test module imports learner code, and `observe.py` before it imports `fakea`. Socket connections, DNS lookups, subprocesses, os spawns and the real httpx transports raise `Blocked` and are recorded; the `httpx.MockTransport` the checks use is not touched.

## Observe

`python labs/w4/tools/observe.py tools` (lab w4l1) prints, for each of the three tools, its arguments, whether its schema is closed, how many arguments are described, and whether the schema refuses the `{"groups": [...]}` the recorded model sent. Then `run_tool` on six calls: `get_indicators {"names": ["close", "rsi_14"]}`, the recorded call to `get_sources`, text that is not JSON, an unknown name, `get_levels {}`, and an unknown metric, each with its row count and first row, its error, or what it raised. Last, how many of the 21 `get_indicators` rows on the extra-digits context carry the value the SOURCES table shows. What moves: closed False → True (w4l1.1), raised → `error: ...` (w4l1.2), 21 rows → 2 with `source_id` and `unit`, and 0 → 21 of 21 matching the table (w4l1.3).

`python labs/w4/tools/observe.py loop` (lab w4l2) prints the length of `tools_prompt`'s turn and how many source rows it holds, then runs `analyze_with_tools` five times: the recorded exchange (with each request compared to the recorded one: the keys that differ, and which turns), the three-call reply, a model that never stops asking (`max_turns` 3), an HTTP 400 on the second call, and an HTTP 503 before every reply. Each run shows the requests sent, the tool turns, the sample's outcome, parse status, error and claim count, and the trace's span kinds. What moves: 2095 chars and 38 rows → 247 and 0, and `tools` and `tool_choice` gone from the differing keys (w4l2.1); 1 request → 2 and 11 claims, tool spans in the trace (w4l2.2); 13 requests → 3 and a failed sample with `max_tool_turns`, model spans in the trace, before the tool spans they asked for (w4l2.3). What cannot move: the replies are recorded, so a run is evidence about the learner's loop only where its requests equal the recorded ones; the user turn and the tool turn's text differ by design (the recording's user turn named `get_sources`, and its tool answer came from the capture's own tool). [pages/w4l2.md](pages/w4l2.md) has the table per exercise.

## The suite gate

`tests/test_week4.py` (23 cases) covers the whole chapter and is red until the week ends. Passing: 0 at the base, 1 on the w4l1.1 stub (the tool names), 2, 6 and 6 after w4l1.1, .2 and .3 (the six tool cases), 7 after w4l2.1, 9 after w4l2.2, and 11 after w4l2.3 (the five loop cases). The end-of-lab run of `tr lab next` deselects what that lab cannot turn green yet:

| Deselected | Where | Why |
|---|---|---|
| `test_the_first_request_sends_the_tools_and_no_source_rows`, `test_the_second_request_answers_each_tool_call_with_its_run_tool_result`, `test_the_loop_stops_at_the_final_json_and_returns_a_parsed_sample`, `test_every_model_call_and_tool_call_is_in_the_trace`, `test_the_turn_cap_returns_a_failed_sample_without_raising` | `[labs.w4l1.suite]` | they run `analyze_with_tools`, which is lab w4l2; after w4l1 `analyze.py` is still the base's |
| `test_a_tools_arm_runs_through_run_arms`, `test_a_tools_arm_that_never_stops_makes_no_more_than_the_cap`, `test_tool_calls_ok_is_a_registered_code_grader_with_a_call_cap`, `test_tool_calls_ok`, `test_tool_calls_ok_fails_one_call_over_the_cap` (6 cases), `test_the_tools_vs_fixed_experiment_has_two_arms_that_differ_only_in_mode` | `[suite]` (every lab) | the tools arm, the grader and the experiment config (chapter §3 and §4) are part B's |
| `test_adr_005_records_the_decision_a_measured_table_and_the_consequences`, `test_the_first_rule_change_is_preregistered_by_the_book`, `test_the_first_rule_change_names_a_real_challenger_and_registers` | `[suite]` (every lab) | they read files written by hand from the chapter (§4 and §6) |

The cases still red at the end of each lab are exactly these: 17 after w4l1, 12 after w4l2.

Between w4l2.2 and w4l2.3, plain `pytest tests/test_week4.py` does not end: on the w4l2.3 stub the loop has no cap, and `test_the_turn_cap_returns_a_failed_sample_without_raising` replays a model that never stops through the repo's own fake, which never gives up; memory grows until the run is stopped. The lab checks and observe end, because the labs' replay answers HTTP 400 from the 13th request on, and `tr lab next` runs the repo suite only after a lab's last exercise. The w4l2 page warns the learner.

**End state.** `[end] tag = "week-4-end"`, `files` = `src/tradingresearch/tools.py` and `src/tradingresearch/analyze.py`: after w4l2.3 each must equal the tag byte for byte. `tools.py` already equals it after w4l1.3, and `analyze.py` after w4l2.3. The w4l1 exercises do not touch `analyze.py`, which stays the base's until the w4l2.1 stub brings in the week's.

## What the labs do not cover

§1 (setup and the tour of the shipped code). §4, the paid experiment, tools against fixed on 20 ticker-days: it cost $0.88 at the author's run ($0.877992) and needs the reader's own key, so it is not a lab. ADR-005, the decision written from it (at n = 20 no difference, tools mode not adopted), is written by hand and reviewed in §9. The measured costs of the week are in the chapter's Week 4 cash table. §7 (agreement with the judge on live trades, which needs closed trades) and §8 (the optional server over the journal and ADR-006, a stretch) stay in the chapter too. Part B will cover the tools arm and `tool_calls_ok` (§3), route provenance (§5) and the first rule change (§6).

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w4 > labs/w4/PROOF.md
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks of the same lab still green, every `wrong/*.diff` red with its `expect:`), the end state (the two `[end]` files equal `week-4-end`), the hint guard, the captured output and a runner smoke; [labs/w1/README.md](../w1/README.md#prove-the-folder) describes each row. It exits 1 if any row reads NOT PROVEN. Until the captures below are written, the 12 captured-output rows (`expected_output/fail.txt` and `pass.txt` of each exercise) read NOT PROVEN. Re-run it after changing an exercise, a stub, a test message, the data, observe or `lab.py`.

The hint guard is a string match: it rejects a hint that repeats a `solution.diff` added line of 12 or more characters, or holds a code fence longer than one line. It does not judge whether prose dictates the answer; that is a reading job. The week-4 hints state the idea and a counterexample, with no code and no function to call.

**Captures for the site.** The same as week 1's (see [labs/w1/README.md](../w1/README.md)), without a session: each exercise's `expected_output/fail.txt` and `pass.txt`, and the page text in each `exercise.toml`: `goal`, `what_tested`, `writes`, `show_tests` (no `show_data`), with `goal` and `section` per lab in `lab.toml`. `python labs/tools/capture.py w4 --write` writes the captured files, `--out <dir>` writes them elsewhere (two runs give the same files), `--leakcheck` checks that no page text gives away a solution line or a locked hint, and `prove.py w4` re-captures and fails on any difference.

## Reading

The week's reading is the published chapter, [Week 4](https://scout.edgelab.one/learn/ai-engineering/week-4/). These labs are the code of its [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0) and [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0); the pages link its sections.

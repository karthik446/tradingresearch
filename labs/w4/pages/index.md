# Week 4 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 4 of the AI engineering track gives the analysis model tools: instead of reading every source row up front, it asks for the rows it wants and cites them. These labs are the code half of the chapter's [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0), [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0), [§5 The route bug the recorded exchange found](https://scout.edgelab.one/learn/ai-engineering/week-4/#5-the-route-bug-the-recorded-exchange-found-05-h-0) and [§6 Champion/challenger: the first rule change](https://scout.edgelab.one/learn/ai-engineering/week-4/#6-championchallenger-the-first-rule-change-15-h-0-now): 12 exercises in 4 labs, on the `labs` branch of your tradingresearch clone. Every exercise is a change to the repo's code, checked by pytest. Each has an observe command that runs your code on the hand-built FAKEA ticker-day and the one recorded tool exchange, or edits of them: your tools (`observe.py tools`), your loop (`loop`), the tools arm (`arm`), the tool-call grader (`grader`), routes (`clean`, `route`) and the rule change (`rule`). Nothing calls a model and nothing costs money.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w4l1 Three tools the model can use](w4l1.md) | `TOOLS` and `run_tool`: closed schemas, errors the model reads, rows a claim can cite | 3 | schemas closed False → True on all three tools; an unknown tool, bad JSON and an unknown metric raised → `{"error": ...}`; rows with extra digits matching the table 0/21 → 21/21 |
| [w4l2 The tool loop](w4l2.md) | `tools_prompt` and `analyze_with_tools`: the turn with no rows, the tools offered, every call answered, the cap and the trace | 3 | the user turn 2095 chars with 38 rows → 247 chars with none; the recorded exchange 1 request → 2 requests and 11 claims; a model that never stops 13 requests → 3 and a failed sample; the trace from the trial span alone → every model and tool span in order |
| [w4l3 The tools arm in the experiment](w4l3.md) | `run_tools`, the tools arm in `run_arms`, and the `tool_calls_ok` grader | 3 | a $0.06 cap 4 requests sent → stopped before the first ($0.081384 planned); spend $0 → $0.045776; a failed item graded → not graded; the tools arm `NotImplementedError` → 4 calls stored under `openrouter:Azure`; `tool_calls_ok` 1.0 everywhere → 0.0 with the first fault on three of five loops |
| [w4l4 Route provenance and the first rule change](w4l4.md) | `clean_route` and the trainable-route refusal, the route of a whole exchange, the `short-sma50-trend` filter and `rule-change-1` | 3 | nine routes all clean → six refused on a trainable record; the recorded loop's route `openrouter:Azure` → `openrouter:mixed(Azure+Google)`; pinned arms all `google` → one route each; three short theses kept → refused; learn status no change → `rc_1` pending from 2026-11-17 |

**Week 4 starts from the author's code, not yours.** The first `tr lab start w4l1` makes the repo's files equal to the tag `week-4-start` (the author's code at the start of week 4, which includes the author's solutions to weeks 1 to 3) and commits that as `lab: week 4 base (week-4-start)`. Your earlier commits stay in the history of the `lab` branch; you can start week 4 without finishing week 3. At `week-4-start` there is no `tools.py` and no tool loop; an exercise whose file changes this week brings in the week's version of it with the exercise code cut out (the w4l1.1 stub `tools.py`, the w4l2.1 stub `analyze.py`, and so on; each page says which).

**Part A, labs w4l1 and w4l2:** the tools and the loop, one ticker-day at a time. **Part B, labs w4l3 and w4l4:** the loop as an experiment arm beside the fixed context, a grader for the calls it makes, which provider served each exchange (route provenance), and the first rule change, pre-registered. Each lab can be started on its own with `--assume-previous`.

**Not in these labs.** The rest of the chapter stays in the chapter:

- [§1](https://scout.edgelab.one/learn/ai-engineering/week-4/#1-setup-and-a-tour-of-the-shipped-code-1-h-0): setup and the tour of the shipped code.
- [§4](https://scout.edgelab.one/learn/ai-engineering/week-4/#4-the-experiment-tools-vs-fixed-adr-005-2-h-088-at-the-authors-run), the paid experiment: tools against fixed on 20 ticker-days, $0.88 at the author's run ($0.877992). It needs your own key, so it is not a lab; lab w4l3 builds the arm it runs. Its config, `experiments/tools-vs-fixed.toml`, and ADR-005, the decision written from its measured table, are written by hand; the two `test_week4` cases that read them stay red in these labs.
- The chapter's §7 (the judge's agreement with your labels on live trades) and §8 (an optional server over the journal, and ADR-006): both wait for data or are not in the repo.
- §6's live part: registering `rc_1` in your own journal and the 20 paired sessions that decide it. Lab w4l4 registers it in a scratch journal only.
- `docs/measured-costs.md`, `docs/runbook.md`, the repo README and `tests/test_tools.py`, which change at `week-4-end` but no exercise writes. The measured costs are in [Week 4 cash](https://scout.edgelab.one/learn/ai-engineering/week-4/#week-4-cash-as-measured-by-the-author).

**`tests/test_week4.py` is red until the week ends.** It covers the whole chapter: 23 cases, 0 passing at `week-4-start` (there is no `tools.py`).

| State | test_week4 passing (of 23) |
|---|---|
| `week-4-start` | 0 |
| the w4l1.1 stub | 1 (the tool names) |
| after w4l1.1, .2, .3 | 2, 6, 6 (the tool cases) |
| after w4l2.1, .2, .3 | 7, 9 (and the cap test never ends; see [lab w4l2](w4l2.md#w4l23-the-cap-and-the-trace)), 11 (the loop cases) |
| after w4l3.1, .2, .3 | 11, 13 (the tools arm), 19 (`tool_calls_ok`) |
| after w4l4.1, .2, .3 | 19, 19, 21 (the rule change) |

The 2 still red at the end are the section-4 cases written by hand: the tools-vs-fixed experiment config and ADR-005. `tr lab next` runs the repo suite at the end of each lab and leaves out the tests that lab cannot turn green yet: those 2 always (`[suite] deselect` in [`lab.toml`](../lab.toml)), plus the later labs' tests (`[labs.<id>.suite]`), each with the reason. After lab w4l4 the gate leaves out only the 2. Plain `uv run pytest -q` still shows them failing.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w4/`. `tr lab` drives the exercises: `tr lab start w4l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs of `tr lab verify` (hint 1 after 2, hint 2 after 5, the solution after 10 or at once when green; [`lab.toml`](../lab.toml) holds the numbers).

Concepts: [index](concepts.md). Reading: the chapter, [Week 4](https://scout.edgelab.one/learn/ai-engineering/week-4/). How the folder is built and proved: [README](../README.md).

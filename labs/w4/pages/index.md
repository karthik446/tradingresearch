# Week 4 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 4 of the AI engineering track gives the analysis model tools: instead of reading every source row up front, it asks for the rows it wants and cites them. These labs are the code half of the chapter's [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0) and [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0): 6 exercises in 2 labs, on the `labs` branch of your tradingresearch clone. Every exercise is a change to `src/tradingresearch/tools.py` (lab w4l1) or to `analyze_with_tools` in `src/tradingresearch/analyze.py` (lab w4l2), checked by pytest. Each has an observe command that runs your code on the hand-built FAKEA ticker-day: your three tools on six calls (lab w4l1, `observe.py tools`), and your loop on the one recorded tool exchange and edits of it (lab w4l2, `observe.py loop`). Nothing calls a model and nothing costs money.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w4l1 Three tools the model can use](w4l1.md) | `TOOLS` and `run_tool`: closed schemas, errors the model reads, rows a claim can cite | 3 | schemas closed False → True on all three tools; an unknown tool, bad JSON and an unknown metric raised → `{"error": ...}`; rows with extra digits matching the table 0/21 → 21/21 |
| [w4l2 The tool loop](w4l2.md) | `tools_prompt` and `analyze_with_tools`: the turn with no rows, the tools offered, every call answered, the cap and the trace | 3 | the user turn 2095 chars with 38 rows → 247 chars with none; the recorded exchange 1 request → 2 requests and 11 claims; a model that never stops 13 requests → 3 and a failed sample; the trace from the trial span alone → every model and tool span in order |

**Week 4 starts from the author's code, not yours.** The first `tr lab start w4l1` makes the repo's files equal to the tag `week-4-start` (the author's code at the start of week 4, which includes the author's solutions to weeks 1 to 3) and commits that as `lab: week 4 base (week-4-start)`. Your earlier commits stay in the history of the `lab` branch; you can start week 4 without finishing week 3. At `week-4-start` there is no `tools.py` and no tool loop; the w4l1.1 stub brings in the week's `tools.py`, and the w4l2.1 stub the week's `analyze.py`, each with the exercise code cut out.

**Part B adds the experiment around the loop.** After w4l2.3, `tools.py` and `analyze.py` equal the tag `week-4-end`. Part B (labs w4l3 and w4l4) runs the loop as an experiment arm beside the fixed context, writes the `tool_calls_ok` grader, records which provider served each exchange (route provenance), and brings in the first rule change.

**Not in these labs.** The rest of the chapter stays in the chapter: [§1](https://scout.edgelab.one/learn/ai-engineering/week-4/#1-setup-and-a-tour-of-the-shipped-code-1-h-0) (setup and the tour of the shipped code), and the paid experiment of [§4](https://scout.edgelab.one/learn/ai-engineering/week-4/#4-the-experiment-tools-vs-fixed-adr-005-2-h-088-at-the-authors-run), which cost $0.88 at the author's run and needs your own key; ADR-005, the decision written from it, is written by hand. The measured costs are in [Week 4 cash](https://scout.edgelab.one/learn/ai-engineering/week-4/#week-4-cash-as-measured-by-the-author).

**`tests/test_week4.py` is red until the week ends.** It covers the whole chapter: 23 cases, 0 passing at `week-4-start` (there is no `tools.py`). Lab w4l1 turns the 6 tool cases green, lab w4l2 the 5 loop cases:

| State | test_week4 passing (of 23) |
|---|---|
| `week-4-start` | 0 |
| the w4l1.1 stub | 1 (the tool names) |
| after w4l1.1, .2, .3 | 2, 6, 6 (the tool cases) |
| after w4l2.1, .2, .3 | 7, 9 (and the cap test never ends; see [lab w4l2](w4l2.md#w4l23-the-cap-and-the-trace)), 11 (the loop cases) |

The 12 still red at the end belong to the rest of the week: the tools arm (2), `tool_calls_ok` (6), the tools-vs-fixed experiment config, ADR-005 and the first rule change (2). `tr lab next` runs the repo suite at the end of each lab and leaves out the tests that lab cannot turn green yet: those 12 always (`[suite] deselect` in [`lab.toml`](../lab.toml)), and the 5 loop tests after lab w4l1 (`[labs.w4l1.suite]`), each with the reason. Plain `uv run pytest -q` still shows them failing.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w4/`. `tr lab` drives the exercises: `tr lab start w4l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs of `tr lab verify` (hint 1 after 2, hint 2 after 5, the solution after 10 or at once when green; [`lab.toml`](../lab.toml) holds the numbers).

Concepts: [index](concepts.md). Reading: the chapter, [Week 4](https://scout.edgelab.one/learn/ai-engineering/week-4/). How the folder is built and proved: [README](../README.md).

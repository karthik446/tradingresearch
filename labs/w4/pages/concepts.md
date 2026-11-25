# Concept index (week 4, labs w4l1-w4l2)

One entry per term: what it means, where to read it in the [week 4 chapter](https://scout.edgelab.one/learn/ai-engineering/week-4/), and the exercises that practise it.

| Term | Means | Practised in |
|---|---|---|
| [Closed schema](#closed-schema) | a tool's parameters as a JSON schema that lists every argument, describes each, and allows nothing else | w4l1.1 |
| [Tool error](#tool-error) | a bad call answered as `{"error": "..."}` text the model reads and can act on, never an exception | w4l1.2 |
| [Cited row](#cited-row) | a row a tool returns: its `source_id`, name, unit and value, the value written as the fixed table writes it | w4l1.3 |
| [Tools prompt](#tools-prompt) | the tools-mode user turn: the ticker and the session, and where the rows are, but no row | w4l2.1 |
| [Tool loop](#tool-loop) | call, answer every tool call the reply asks for, call again, until a reply asks for none | w4l2.2 |
| [Turn cap](#turn-cap) | at most `max_turns` model calls per item; a model that keeps asking ends in a failed sample, not an exception | w4l2.3 |
| [Tool trace](#tool-trace) | one span per model call and per tool call, each written to the trace when it ends, the trial span last | w4l2.2, w4l2.3 |
| [Replayed reply](#replayed-reply) | a recorded model reply served back for $0; evidence only for the request that produced it | w4l2.1 to w4l2.3 |

### Closed schema

The model sees a tool as a name, a description and a JSON schema for its arguments. A schema with no `properties` and no `"additionalProperties": false` accepts anything: the recorded model sent `{"groups": [...]}` to the capture's own tool, and an open `get_indicators` would take the same, ignore it and answer as if asked for nothing. A closed schema lists exactly the arguments its handler reads, each typed and described: `names` (a non-empty list of row names) for `get_indicators`, nothing for `get_levels`, `metrics` (one of the four filed metrics) for `get_fundamentals`. Read [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0).

### Tool error

The loop passes back only the text `run_tool` returns, so a raised exception is a crash the model never sees. Every mistake in a call comes back as one object with one key, `{"error": "<what was wrong, how to call again>"}`: an unknown tool (the message names every tool), argument text that is not a JSON object, an argument the schema does not list, a value that is not a non-empty list of strings, and the error a handler raises. An empty argument text is not a mistake: some providers send it for a call with no arguments. Read [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0).

### Cited row

A claim cites a row by its `source_id`, and the claim check rejects a `source_id` it does not know. So a tool row is `{source_id, name, unit, value}`, plus `label` when the row has one (the market regime), and its value is a JSON number written as the fixed SOURCES table writes it: a computed close of 101.40124722 comes back as 101.401, the table's number, so a claim made through the tools checks against the same number as one made from the table. Read [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0).

### Tools prompt

In the fixed mode the user turn carries the whole SOURCES table: 38 rows, 2095 characters for the FAKEA ticker-day. In tools mode it carries the ticker and the session as the fixed turn writes them, a line saying the table is not included and the tools return the rows, and the answer's form: about 250 characters, no row. Every number the model then cites came through a tool call, which the trace records. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Tool loop

The model answers a request that offers tools either with text or with tool calls. For tool calls, the code sends the reply back as the assistant turn, exactly as it came, then one `tool` turn per call, in the order asked, each with the call's id and what `run_tool` answered, and calls again. A reply that asks for no tool ends the loop and is parsed. Every call re-sends the whole conversation, which is why the chapter's tools arm used 2.78 times the input of the fixed arm. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Turn cap

Nothing in the conversation makes the model stop asking; only the loop can. `MAX_TOOL_TURNS = 5` model calls per item: up to 4 rounds of tools, then the answer. If the last allowed reply still asks for tools, the sample fails with the error code `max_tool_turns` and no further call is made; it is returned, not raised, so the run counts it. A failed call (an HTTP 400) ends the loop the same way, with that call's error. A spending cap's refusal is different: it stops the whole run, so it reaches the caller. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Tool trace

Each model call is a model span, each tool call a tool span, and the item as a whole a trial span that is the parent of the others. A span goes to the trace when it ends: a model call before the tool calls it asked for, the trial span last. Written then, a span survives a refusal halfway through: the calls that already ran, and cost money, are in the trace. A retried call is still one model span. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Replayed reply

The labs call the repo's real OpenRouter adapter with its HTTP transport swapped for one that answers with replies recorded once: a two-call exchange on `anthropic/claude-sonnet-5.5` that cost $0.022888, captured with the capture's own `get_sources` tool. Edited copies of the first reply ask for your three tools, ask again, or fail. A replayed reply cannot react to what you send, so it is evidence about your code only for the request that produced it: the w4l2 checks compare your requests with the recorded ones, all but the user turn and the tool turn's text. Read [§2 Tool design](https://scout.edgelab.one/learn/ai-engineering/week-4/#2-tool-design-three-tools-over-the-context-2-h-0) for the recorded exchange.

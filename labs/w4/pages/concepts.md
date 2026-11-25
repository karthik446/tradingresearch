# Concept index (week 4, labs w4l1-w4l4)

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
| [Tools arm](#tools-arm) | an experiment arm with `mode = "tools"`: the tool loop run over a dataset under the same contract a fixed arm gets from core `run` | w4l3.1, w4l3.2 |
| [Budget plan](#budget-plan) | before the first call, the budget checks the whole run fits, priced on each item's first request; every call is still reserved | w4l3.1 |
| [Route](#route) | the provider route stored with each analysis, looked up under the exchange's first user turn | w4l3.2, w4l4.2 |
| [Tool-call grader](#tool-call-grader) | `tool_calls_ok`: a code grader that reads a sample's tool calls, not its answer, and passes or fails it | w4l3.3 |
| [First fault](#first-fault) | the grader walks the calls in order and reports the first thing wrong: an error, a repeat, then too many calls | w4l3.3 |
| [Provider route](#provider-route) | who served a call, `openrouter:<host>`; clean when it names one known provider | w4l4.1, w4l4.2 |
| [Provenance](#provenance) | knowing which provider served every turn of a record; a trainable record without it is refused | w4l4.1 |
| [Exchange](#exchange) | every request of one tool loop, keyed by its first user turn; its route sums up every turn's | w4l4.2 |
| [Rule change](#rule-change) | one changed trading rule, stored as a record, tried on the challenger and decided after 20 paired sessions | w4l4.3 |
| [Pre-registration](#pre-registration) | the metric, pass rule, guard, margin and sample size of a change, fixed and stamped before its first session | w4l4.3 |
| [Challenger](#challenger) | the arm that runs the champion's rules plus the one pending change, on the same analyses in the same daily run | w4l4.3 |

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

### Tools arm

An experiment config names its arms; a fixed arm (one call per item, the whole SOURCES table in the prompt) runs through core `run`, which plans the run on the budget before the first call, reserves every call, grades only a sample that succeeded, skips a score whose grader raises `CannotGrade`, and records what the calls cost. A tools arm runs the loop of lab w4l2 instead, through `run_tools`, which has to keep that same contract: otherwise a failed loop is graded as an answer, the budget is never asked, and the record says $0. `run_arms` gives a `mode = "tools"` arm its run from `run_tools`, on the arm's own provider, and refuses, before anything is spent, a config that puts a grader that is not code beside it: a model grader is shown the final answer, not the calls, so only code reads a loop. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Budget plan

`budget.plan(requests)` prices a list of requests and refuses, before the first call, a run that does not fit the cap; nothing is spent on a run that would stop halfway. A tools arm cannot know how many calls each loop will make, so it plans on each item's first request as the loop sends it (the system turn, the tools prompt, the tools offered), and every later call is reserved on the same budget before it is sent. In lab w4l3 the FAKEA dataset plans at $0.081384, so a $0.06 cap stops the arm before its first call. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Route

Every stored analysis carries `provider_route`, the [provider route](#provider-route) of the calls that produced it, which the adapter logs per call and `route_for(prompt)` reads back. The log is keyed by the [exchange](#exchange)'s first user turn, so the lookup has to ask with the prompt the arm actually sent: the item's prompt for a fixed arm, the item's tools prompt for a tools arm. Asking a tools arm's log under the fixed prompt finds nothing, and the route reads `openrouter:unknown`. Read [§5 The route bug the recorded exchange found](https://scout.edgelab.one/learn/ai-engineering/week-4/#5-the-route-bug-the-recorded-exchange-found-05-h-0).

### Tool-call grader

`tool_calls_ok` is the one grader that reads how an answer was reached: the tool calls a sample made, with their arguments and results. It needs no model, so it is a code grader (`kind = "code"`) an experiment config can name beside a tools arm, and it scores pass or fail, 1.0 or 0.0, with the [first fault](#first-fault) as the explanation. A sample with no tool calls passes, by design: `compare` grades the fixed arm with the same grader, and the fixed arm makes none. One grader instance grades every sample on its own; a call in one sample is never a repeat in the next. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### First fault

The grader walks the calls in the order they were made and stops at the first fault: `tool_error` when a call raised or its result is an `{"error": ...}` object, `repeated_call` when a tool is called again with the same arguments (compared as parsed JSON, so key order and spacing do not hide a repeat). `too_many_calls` comes after the walk, since only then is the count known: more than `max_calls = 2 × len(TOOLS) = 6`, every tool once plus one follow-up each. Reporting one fault, the first, tells you where the loop went wrong; later faults usually follow from it. Read [§3 The loop, its cap and the budget](https://scout.edgelab.one/learn/ai-engineering/week-4/#3-the-loop-its-cap-and-the-budget-2-h-0).

### Provider route

A route names who served a call: the client, then the host, sometimes with a tier after a slash (`openrouter:Azure`, `openrouter:deepinfra/fp8/flex`). It is clean when the host names one known provider. `openrouter:unknown` (in any case: a review found `openrouter:Unknown` passing a case-sensitive check), a mix like `openrouter:mixed(Azure+Google)`, the client with no host, and the empty route are not. A reply whose `provider` field is null is unknown, not a provider named None. Read [§5 The route bug the recorded exchange found](https://scout.edgelab.one/learn/ai-engineering/week-4/#5-the-route-bug-the-recorded-exchange-found-05-h-0).

### Provenance

A record's provenance is knowing where it came from; here, which provider served every turn behind it. It matters for a record whose terms class is `trainable` (a teacher arm's output, which may become training data): the teacher terms filter can only clear a record whose provider it can name. So a trainable `Analysis` or `Thesis` with a route that is not clean is refused when it is built, with a message that names the route and says "one known provider"; a restricted record keeps any route. A tools teacher arm needs a provider pin, since a loop free to move between providers often ends up mixed. Read [§5 The route bug the recorded exchange found](https://scout.edgelab.one/learn/ai-engineering/week-4/#5-the-route-bug-the-recorded-exchange-found-05-h-0).

### Exchange

One tool loop is several requests: the first, then one follow-up per round of tool calls, each re-sending the conversation so far. They share the first user turn (the item's prompt) and no two items share it, so it is the key the adapter logs routes under; the last turn, the old key, is a tool result in every follow-up. A request with only system and user turns opens a new exchange and clears the old routes under its key, even if it then fails. The exchange's route is unknown when nothing was served or any turn's route is not clean, the route itself when every turn agrees, and otherwise `openrouter:mixed(a+b)`, each provider once, sorted. In the author's paid run 12 of the 20 tools items were served by two providers; the fixed arm, one call per item, had none. The route is per exchange, not per turn: a per-turn route would need a field the trace's spans do not have. Read [§5 The route bug the recorded exchange found](https://scout.edgelab.one/learn/ai-engineering/week-4/#5-the-route-bug-the-recorded-exchange-found-05-h-0).

### Rule change

A rule change is one changed trading rule, written as a file (`experiments/rule-change-1.toml`), committed, then registered in the journal as a `RuleChange` record (`rc_1`) with `decided = "pending"`. Its `diff_ref` names the rule in the reviewed registry `CHALLENGER_RULES`, here the `short-sma50-trend` filter: on the short horizon it drops a long below the 50-session average and a short above it. Only one change may be pending at a time. It is decided after 20 paired sessions, where only a large effect shows (a detectable delta of 0.63 R at an assumed sigma of 1.0 R), due in the author's journal around 2026-12-16 to 12-23 and by day 60 (2027-01-15) at the latest. Read [§6 Champion/challenger: the first rule change](https://scout.edgelab.one/learn/ai-engineering/week-4/#6-championchallenger-the-first-rule-change-15-h-0-now).

### Pre-registration

Before the first session a change covers, its test is written down: `primary_metric` (`session_r_net_delta:short`, the per-session net R of the horizon the rule acts on), `pass_rule` (`delta_ci_lower > 0`), `guard_metric` (`p1_met_rate`) with its `margin` (0.10), `n_planned` (20 paired sessions) and `registered_at`, a time after the last session it does not cover opened and before the first one it covers opens. Fixed first, the rule cannot be tuned to the results; the journal refuses to change these fields later. Read [§6 Champion/challenger: the first rule change](https://scout.edgelab.one/learn/ai-engineering/week-4/#6-championchallenger-the-first-rule-change-15-h-0-now).

### Challenger

The champion runs the current rules; the challenger runs the same rules plus the one pending change, on the same analyses, answering right after the champion in the same daily run, so each session gives one pair to compare. It reaches a rule only through the reviewed registry `CHALLENGER_RULES`, by the key the change's `diff_ref` names, and `pending_for(session)` says which change it runs: none before the session the change was registered for, `rc_1` from 2026-11-17. Read [§6 Champion/challenger: the first rule change](https://scout.edgelab.one/learn/ai-engineering/week-4/#6-championchallenger-the-first-rule-change-15-h-0-now).

# Concept index (week 3, labs w3l1-w3l2)

One entry per term: what it means, where to read it in the [week 3 chapter](https://scout.edgelab.one/learn/ai-engineering/week-3/), and the exercises that practise it.

| Term | Means | Practised in |
|---|---|---|
| [LLM judge](#llm-judge) | a model that grades a text against a written rubric, used where no code can decide | w3l1.1 to w3l2.3 |
| [Verdict format](#verdict-format) | the rubric's rule for the reply: reasoning first, then one JSON object, the last in the reply | w3l1.1 to w3l1.3 |
| [Abstain](#abstain) | the judge's "unknown": stored as `fail` with a reason that starts `unknown:`, left out of κ and counted | w3l1.2 |
| [CannotGrade](#cannotgrade) | gigai-core's exception for "no verdict to store": not a fail, not an abstain | w3l1.3 |
| [Judge prompt](#judge-prompt) | the frame file with the rubric in it, the thesis as OUTPUT and the evidence as INPUT | w3l2.1, w3l2.2 |
| [Evidence, not bars](#evidence-not-bars) | the judge sees the cited claims and the code-written summary, never the price path | w3l2.2 |
| [Call budget](#call-budget) | the two bounds on the one call: output tokens, and dollars checked before sending | w3l2.3 |
| [Replayed reply](#replayed-reply) | a recorded model reply served back for $0; evidence only for the request that produced it | w3l2.1 to w3l2.3 |

### LLM judge

P1 asks whether the thesis's reason played out: did the mechanism it named happen? Code cannot read a mechanism out of free text, so a model does, with a rubric, on one closed trade at a time. `p1_judge` sends the request, `p1_verdict` reads the reply. ADR-003 picks a judge from a different vendor than the model that wrote the thesis (`openai/gpt-6-sol`) and says why the verdict is not trusted until it agrees with the operator's blind labels. Read [§4 The P1 judge and `tr grade --judge`](https://scout.edgelab.one/learn/ai-engineering/week-3/#4-the-p1-judge-and-tr-grade---judge-2-h-0).

### Verdict format

The last section of `evals/rubrics/p1_thesis_quality.md`: reason it through first, then end the reply with one JSON object on its own line, the last JSON object in the reply, `{"verdict": "pass", "explanation": "one sentence"}`, with exactly those keys and the verdict in lower case. `pass` is met, `fail` is not met. Reading the last object, not the first, matters because the reasoning may quote the format example or try a draft verdict before the answer.

### Abstain

When the summary cannot decide (the reason names something code did not measure), the honest answer is "unknown". gigai-core's `JudgeVerdict` is binary, so the rubric writes unknown as `fail` with an explanation that starts `unknown:`. The `judge_verdict` table takes only `pass` or `fail`; the prefix is what lets §7 leave abstains out of Cohen's κ and count them instead. A judge that writes `"verdict": "unknown"` anyway gets the same reading: `fail`, with `unknown:` put in front of its explanation once. Read [§7 Blind labels and Cohen's κ](https://scout.edgelab.one/learn/ai-engineering/week-3/#7-blind-labels-and-cohens-κ-1-h-0-now).

### CannotGrade

A reply with no JSON object, no `verdict` key, or a verdict that is not one of the three words has nothing to store. Storing it as `fail` would count a broken reply as a judgment; storing it as an abstain would count it as "the evidence cannot decide". `p1_verdict` raises gigai-core's `CannotGrade` with a message that names what was missing, and nothing is stored for that trade. The call was still made: `tr grade --judge` counts its cost against the cap all the same.

### Judge prompt

`evals/rubrics/p1_judge_prompt.txt` is the frame: what the judge decides, what the INPUT and OUTPUT blocks hold, and a `{rubric}` line where `p1_thesis_quality.md` goes. gigai-core's `llm_judge` renders the frame, then the sample: INPUT is the evidence, OUTPUT is the text being graded. For P1 the text being graded is the thesis: `prediction:`, `reason:` and `invalidation_text:`, one labelled line each.

### Evidence, not bars

INPUT holds the claims the thesis cited, as `label.cited` writes them, then the post-trade summary code wrote from the bars, as `label.summary` writes it, each under its heading. These are the same lines `tr label show` gives the operator, so the judge and the operator decide on the same evidence. The bars stay out: with the whole price path the judge could grade by what happened after, which the rubric's Hindsight section forbids.

### Call budget

Two bounds on one call per trade. Tokens: `CallSettings` defaults to 1024 output tokens; ADR-003 sets `JUDGE_MAX_TOKENS = 4000`, about eight times the ~500 a trade is expected to take, so a runaway reply stops but a long reasoning still reaches its verdict. Dollars: `CallBudget(max_usd=..., prices=...)` estimates the call's worst case from the model's price row before sending (about $0.043 for this prompt at 4000 output tokens) and raises `BudgetExceeded` when it does not fit, so nothing is sent and nothing is spent. Without a price for the model it refuses every capped call. `tr grade --judge` passes `p1_judge` what is left of its cap.

### Replayed reply

The labs call the repo's real OpenRouter adapter with its HTTP transport swapped for one that answers every request with a reply recorded once (run `run_54953ec7ce484649`). That costs $0 and runs offline, but the reply cannot react to what you send: it says pass to an empty prompt too. So it is evidence about your code only when your request equals the one that produced it, and the w3l2 checks compare against that recorded request.

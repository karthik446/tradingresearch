# Concept index (week 3, labs w3l1-w3l4)

One entry per term: what it means, where to read it in the [week 3 chapter](https://scout.edgelab.one/learn/ai-engineering/week-3/), and the exercises that practise it.

| Term | Means | Practised in |
|---|---|---|
| [LLM judge](#llm-judge) | a model that grades a text against a written rubric, used where no code can decide | w3l1.1 to w3l4.3 |
| [Verdict format](#verdict-format) | the rubric's rule for the reply: reasoning first, then one JSON object, the last in the reply | w3l1.1 to w3l1.3 |
| [Abstain](#abstain) | the judge's "unknown": stored as `fail` with a reason that starts `unknown:`, left out of Cohen's kappa and counted | w3l1.2, w3l3.2 |
| [CannotGrade](#cannotgrade) | gigai-core's exception for "no verdict to store": not a fail, not an abstain | w3l1.3, w3l3.1 to w3l3.3 |
| [Judge prompt](#judge-prompt) | the frame file with the rubric in it, the thesis as OUTPUT and the evidence as INPUT | w3l2.1, w3l2.2 |
| [Evidence, not bars](#evidence-not-bars) | the judge sees the cited claims and the code-written summary, never the price path | w3l2.2 |
| [Call budget](#call-budget) | the two bounds on the one call: output tokens, and dollars checked before sending | w3l2.3, w3l4.2 |
| [Replayed reply](#replayed-reply) | a recorded model reply served back for $0; evidence only for the request that produced it | w3l2.1 to w3l3.1 |
| [Run file](#run-file) | the file under `data_dir/runs` that keeps one judge call and what it cost, failed calls included | w3l3.1, w3l4.2 |
| [Score record](#score-record) | the stored Score: which grader, which judge and prompt, which trace; written with its verdict row or not at all | w3l3.2 |
| [Refusal](#refusal) | a thesis the judge may not take (teacher, or no Grade) is `CannotGrade` before any call, at $0 | w3l3.3 |
| [Judge queue](#judge-queue) | the theses waiting for the judge: graded champion and challenger theses with no verdict, oldest first | w3l4.1 |
| [Run cap](#run-cap) | one dollar cap for a whole `tr grade --judge` run; what does not fit waits for the next run | w3l4.2, w3l4.3 |
| [Off by default](#off-by-default) | the one paid step of `tr grade` runs only with `--judge`, and says what it cost | w3l4.3 |

### LLM judge

P1 asks whether the thesis's reason played out: did the mechanism it named happen? Code cannot read a mechanism out of free text, so a model does, with a rubric, on one closed trade at a time. `p1_judge` sends the request, `p1_verdict` reads the reply. ADR-003 picks a judge from a different vendor than the model that wrote the thesis (`openai/gpt-6-sol`) and says why the verdict is not trusted until it agrees with the operator's blind labels. Read [§4 The P1 judge and `tr grade --judge`](https://scout.edgelab.one/learn/ai-engineering/week-3/#4-the-p1-judge-and-tr-grade---judge-2-h-0).

### Verdict format

The last section of `evals/rubrics/p1_thesis_quality.md`: reason it through first, then end the reply with one JSON object on its own line, the last JSON object in the reply, `{"verdict": "pass", "explanation": "one sentence"}`, with exactly those keys and the verdict in lower case. `pass` is met, `fail` is not met. Reading the last object, not the first, matters because the reasoning may quote the format example or try a draft verdict before the answer.

### Abstain

When the summary cannot decide (the reason names something code did not measure), the honest answer is "unknown". gigai-core's `JudgeVerdict` is binary, so the rubric writes unknown as `fail` with an explanation that starts `unknown:`. The `judge_verdict` table takes only `pass` or `fail`; the prefix is what lets §7 leave abstains out of Cohen's kappa and count them instead. A judge that writes `"verdict": "unknown"` anyway gets the same reading: `fail`, with `unknown:` put in front of its explanation once. Read [§7 Blind labels and Cohen's kappa](https://scout.edgelab.one/learn/ai-engineering/week-3/#7-blind-labels-and-cohens-κ-1-h-0-now).

### CannotGrade

A reply with no JSON object, no `verdict` key, or a verdict that is not one of the three words has nothing to store. Storing it as `fail` would count a broken reply as a judgment; storing it as an abstain would count it as "the evidence cannot decide". `p1_verdict` raises gigai-core's `CannotGrade` with a message that names what was missing, and nothing is stored for that trade. The call was still made: `tr grade --judge` counts its cost against the cap all the same.

### Judge prompt

`evals/rubrics/p1_judge_prompt.txt` is the frame: what the judge decides, what the INPUT and OUTPUT blocks hold, and a `{rubric}` line where `p1_thesis_quality.md` goes. gigai-core's `llm_judge` renders the frame, then the sample: INPUT is the evidence, OUTPUT is the text being graded. For P1 the text being graded is the thesis: `prediction:`, `reason:` and `invalidation_text:`, one labelled line each.

### Evidence, not bars

INPUT holds the claims the thesis cited, as `label.cited` writes them, then the post-trade summary code wrote from the bars, as `label.summary` writes it, each under its heading. These are the same lines `tr label show` gives the operator, so the judge and the operator decide on the same evidence. The bars stay out: with the whole price path the judge could grade by what happened after, which the rubric's Hindsight section forbids.

### Call budget

Two bounds on one call per trade. Tokens: `CallSettings` defaults to 1024 output tokens; ADR-003 sets `JUDGE_MAX_TOKENS = 4000`, about eight times the ~500 a trade is expected to take, so a runaway reply stops but a long reasoning still reaches its verdict. Dollars: `CallBudget(max_usd=..., prices=...)` estimates the call's worst case from the model's price row before sending and raises `BudgetExceeded` when it does not fit, so nothing is sent and nothing is spent. The estimate counts the prompt at about 4 characters per token plus 4000 output tokens: $0.042964 for this prompt. The recorded reply shows the prompt was really 1558 tokens, so the true worst case is $0.043116; the budget can only estimate before sending. Without a price for the model it refuses every capped call. `tr grade --judge` passes `p1_judge` what is left of its cap.

### Replayed reply

The labs call the repo's real OpenRouter adapter with its HTTP transport swapped for one that answers every request with a reply recorded once (run `run_54953ec7ce484649`). That costs $0 and runs offline, but the reply cannot react to what you send: it says pass to an empty prompt too. So it is evidence about your code only when your request equals the one that produced it, and the w3l2 checks compare against that recorded request.

### Run file

`run_eval` traces the call; analyze's `save` (`an.save(run, data_dir)`) writes the run to `data_dir/runs/run_<id>.jsonl`, with what the call spent in its header. That file is the only record of what a call cost: `tr usage` and `tr grade --judge` read it, so a call with no run file was paid for and never counted. A failed call gets one too: an HTTP 400 is still a call, with $0.000000 in its file, and `p1_judge` names that file in its `CannotGrade` so whoever reads the error can open it. The recorded reply costs $0.005163.

### Score record

The Score `p1_judge` returns (1.0 for pass, 0.0 otherwise, with a `JudgeNote` of the judge model, the prompt's sha256 and the calls) is stored as a `ScoreRecord` of kind `model`: the grader's id and version, the judge model, the prompt's sha256, the sample's trace id and the ids of its model spans, so a stored verdict can be traced back to the call that made it. The `judge_verdict` row points at that record, and both are written in one transaction on the journal connection: if the second write fails, the first is rolled back, and the thesis has no verdict, so the next run judges it again.

### Refusal

`label.labelable` is the rule `tr label` uses for which theses may be labelled: never a teacher thesis (ADR-003: teacher theses are never judged), never one `tr grade` has not graded (never entered, or not closed yet), because the post-trade summary needs its Grade. It raises `label.Refused`. `p1_judge` checks it first and raises `CannotGrade` with the refusal's message, before the prompt is built or any request is sent: no call, no run file, $0.

### Judge queue

`grade.to_judge` lists what a `tr grade --judge` run takes: champion and challenger theses with a Grade and no `judge_verdict` row yet, oldest first. Teacher theses never wait; a thesis with a verdict is never judged twice; and oldest first means that when the cap runs out, the newest theses are the ones left for the next run.

### Run cap

`grade.judge` takes the queue in one run under one dollar cap (`JUDGE_MAX_USD`, $0.25), not one cap per call. Each thesis gets `p1_judge` with what the run has left. When the budget refuses a call (`BudgetExceeded`: the budget's estimate of one call's worst case is about $0.043 and does not fit), that thesis and every later one wait for the next run; any other failure stays on its thesis and the run goes on. Each thesis is charged what the run files its call added say it spent, so a reply with no verdict counts against the cap too.

### Off by default

The judge is the one step of `tr grade` that costs money, so plain `tr grade` never calls it. `tr grade --judge` runs it and prints one line per thesis with what its call cost, a call that judged nothing included, then the count and the run's total, in dollars to the millionth as the run files have them (one call is about half a cent). `tr grade --judge --dry-run` lists what it would judge and calls nothing.

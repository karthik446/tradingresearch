# When would fine-tuning pay off here? (week 1 note)

**Not now.** Every class in `evals/taxonomy.md` that code can see is either already rejected by code or is the kind
of instruction-following a prompt rule fixes (window names, labels in {value}, opinions with parents). The cheaper
moves come first: a prompt change measured by `tr exp run` costs about $0.31 per arm of 20 ticker-days.

**What would change that.** Fine-tuning (or distilling to a smaller model) earns its cost when all of these hold:
1. A failure class survives two or three prompt iterations at a rate the interval shows is real.
2. There are labelled examples to train on: hundreds of passing analyses, which `all_claims_valid` and the journal
   already select for free.
3. Volume makes per-call cost matter. At $0.016 per analysis, 100 tickers a day is about $1.60; a cheaper tuned
   model saves little until volume is far higher.
4. The eval suite is stable enough to tell whether the tuned model is better, on the same paired dataset.

**What to measure first.** The share of failures left after the best prompt, per class, and cost per fully valid
analysis (spend ÷ analyses with `all_claims_valid` = 1). If the second number stops falling with prompt changes,
revisit this note.

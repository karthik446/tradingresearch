# Hints: w4l3.2

## Hint 1

`run_arms` already builds one Dataset, one context per item and one provider per arm; a tools arm needs only a different way to get its Run (`run_tools`, from the last exercise), with the same graders. The refusal belongs before the loop over arms: once the first arm has run, its calls are spent. A grader's `kind` says whether it is code. Look at every arm, not only the first.

## Hint 2

The adapter logs the host that served a call under the exchange's user turn (`route_for(prompt)`). A fixed arm's user turn is the item's prompt; a tools arm never sends that prompt, so asking for its route gives `openrouter:unknown`. A counterexample: FAKEA answered by Azure and FAKEB by Google, both stored as `openrouter:unknown`, or both as Google when every item asks with the last item's turn.

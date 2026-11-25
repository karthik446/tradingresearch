# Hints: w4l3.1

## Hint 1

Core `run` does three things before and around the calls that your loop has to do itself: it asks the budget whether the whole run fits before the first call (`budget.plan(requests)`), it sends every call through the budget so each one is reserved first, and it grades only what succeeded. The requests you plan are the ones the loop will send first: the system turn and that item's tools prompt, with the tools offered. The fixed arm's request, with the whole context in it, is a bigger estimate: $0.083280 for two items where the loop's first requests are $0.081384.

## Hint 2

Planning checks the first call of each item; it cannot know how many calls the loop will make. So the budget the plan used has to wrap the provider, and every call of the loop has to go through it, the second one too. A counterexample for the record: counting samples gives 2 calls for a run that made 5 model calls, and summing the tool spans' costs gives $0. The model spans hold each call's reported cost.

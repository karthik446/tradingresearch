# Hints: w4l2.3

## Hint 1

Nothing in the conversation forces the model to stop asking; only your loop can. Count model calls, not tool calls, and when the count runs out without a final reply, that is a failed item the run should count, not an exception that stops the run.

## Hint 2

The loop can end three ways: a reply with no tool call, a failed call, or the count running out. Only the last is a max_tool_turns failure, so after the loop your code has to know which one happened. A counterexample for the trace: code that collects the spans and writes them all just before returning writes nothing when a spending cap refuses the second call, though the first call and its tools already ran and cost money.

# Hints: w4l2.1

## Hint 1

In tools mode a number the model cites must have arrived through a tool call, because the trace records those and nothing else. So the turn keeps what render says about the question and the answer and drops the table; the model still has to be told where the rows went.

## Hint 2

The request model the loop builds already has a field for the tools; the adapter turns each spec into the function form the API expects and sets tool_choice for you. Offer the same tools on every call, not only the first.

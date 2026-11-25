# Hints: w4l2.2

## Hint 1

The API only accepts a tool answer for a call it can see in the conversation, so the reply that asked comes back first, with its calls attached. Then each call gets its own answer, matched by id; a model that asked three questions at once reads three answers.

## Hint 2

The module already has a helper that runs one call and returns its span and its text; a span that is not written to the sink and kept is a tool call the trace never shows. After the answers, nothing breaks the loop: the next turn is another model call.

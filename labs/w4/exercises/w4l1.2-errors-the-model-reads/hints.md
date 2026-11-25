# Hints: w4l1.2

## Hint 1

The model never sees a Python exception: the loop only passes back the text run_tool returns. So every failure has to become that text, and it should read like an instruction: what was wrong and what a good call is. The recorded run asked for a tool that does not exist; the answer should list the ones that do.

## Hint 2

A call can be wrong in several ways, and each needs its own sentence, but the step that turns a mistake into the error object should exist once, so no path slips out as a raw exception. A counterexample: the text `[]` parses as JSON and is not an object; code that only guards the parse lets it through, and the handler then fails in a way the model never reads. An empty text is not a mistake: some providers send it for a call with no arguments.

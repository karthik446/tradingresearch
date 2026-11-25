# Hints: w4l3.3

## Hint 1

`sample.tool_spans` is the calls in the order they were made; each span has `call.name`, `call.arguments` (JSON text), `result` and `error`. The grader returns as soon as it meets a fault, so the fault reported is the earliest one in that order. A count of calls is only known after the walk, so the cap is checked last. A result is a tool error only when it is itself an object with an `"error"` key, whether the span holds it parsed or as the JSON text the model was sent.

## Hint 2

Two calls are the same request when they name the same tool and their arguments are the same JSON: `{"names": ["close"]}` and `{ "names" : [ "close" ] }` are one request written twice. Parse the arguments before comparing them, and keep what you have seen inside one `grade` call, not on the grader, because one instance grades every sample of a compare. A counterexample: 6 distinct clean calls is at the cap and passes; 7 is one over.

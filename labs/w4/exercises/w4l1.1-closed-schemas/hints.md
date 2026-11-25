# Hints: w4l1.1

## Hint 1

A schema is the model's only description of a call before it makes one. Open means the model may add any key and still look valid; closed means one setting on the object that forbids everything you did not list. Then list exactly the keys the handler reads, no more.

## Hint 2

Each property needs its own type and its own description: the description is the sentence the model reads when it decides what to send. A list that may be empty asks for nothing, so require at least one item; where the allowed strings are known in advance (the metrics), the schema can list them.

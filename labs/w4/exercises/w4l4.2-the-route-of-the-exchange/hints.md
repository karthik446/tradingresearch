# Hints: w4l4.2

## Hint 1

A tool loop is several requests that all belong to one item. Look at what every one of them has in common that two items never share: the first thing the user said. The last turn changes on every follow-up (it becomes the tool result), and the system turn is the same for every item. The route of an item is then the routes of all its requests together, not the route of whichever request came last.

## Hint 2

Decide what each request is before it goes out: a request that only carries what the system and the user said opens a new exchange, so its item's old routes no longer apply, even if the call then fails. A follow-up carries the model's own turn or a tool result and adds to the open exchange. When you sum up an exchange, any turn nobody can name makes the whole exchange unnamed; otherwise collapse repeats before you decide between one route and a mix, and give the mix one fixed order. A copy of the client that shares the original's containers shares its history too.

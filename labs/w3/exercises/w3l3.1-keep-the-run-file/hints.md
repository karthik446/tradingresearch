# Hints: w3l3.1

## Hint 1

`analyze` already knows where runs live and how to write one: evals.py imports it as `an`, and its save takes the run
and the data dir and gives back the path it wrote. Save first, then look at the sample; the order is the whole point.

## Hint 2

A sample says how its call went in `outcome`, and when that is not `"succeeded"` its `error` holds a code (`http_400`
here). Keep the saved path in a variable, so the message can name the file. The verdict reading stays w3l3.2's: leave its
NotImplementedError where it is.

# Hints: w3l3.1

## Hint 1

The run file is written by code the course already has: analyze's save (`an.save`) knows where runs live and gives back
the path it wrote. Keep the file first, then decide what the call's outcome means; the order is the whole point. A
rejected request, an empty account and a reply with no verdict line are all calls on record, and some of them are paid.

## Hint 2

A sample records how its call went and, when it did not succeed, the error code the provider gave: http_400 for a
rejected request, insufficient_credits for an empty account. The CannotGrade names that code and the file's full path,
so whoever reads the error can open it, and the journal gets nothing: an outage is not a verdict. Reading the verdict is
w3l3.2's; leave its NotImplementedError where it is.

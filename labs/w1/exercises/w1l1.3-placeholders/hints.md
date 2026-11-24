# Hints: w1l1.3

## Hint 1

Find every `{...}` in the text and treat them as a set. Two checks follow: is anything in the set other than
`{value}`, and is `{value}` in the set while `value` is `None`.

## Hint 2

The first check is what is left of the set once the one allowed placeholder is taken out; sort it for the
detail. Run the bad_placeholder check before the empty_placeholder one, so `{label}` with a null value reports
`{label}`.

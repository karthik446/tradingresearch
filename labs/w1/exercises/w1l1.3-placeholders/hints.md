# Hints: w1l1.3

## Hint 1

Find every `{...}` in the text as a set (`re.findall(r"\{[^}]*\}", text)`). Two checks follow: is anything in the set
other than `{value}`, and is `{value}` in the set while `value` is `None`.

## Hint 2

Set difference does the first check: `placeholders - {"{value}"}`; join `sorted(...)` of it for the detail. Do the
bad_placeholder check before the empty_placeholder one, so `{label}` with a null value reports `{label}`.

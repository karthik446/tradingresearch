# Hints: w1l4.2

## Hint 1

Copy the shape of `experiments/observe.toml`: same model, tickers and sessions, so the items are the ones your
taxonomy came from. A second `[[arms]]` table with `prompt = "analyze-2"` is the variant.

## Hint 2

The second comment line is the pre-registration: "primary metric all_claims_valid; guard metric parsed must not
drop". Add `"inferences_grounded"` to `graders`; `load` refuses it if lab w1l3 did not register it.

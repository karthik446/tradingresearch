# Hints: w5l1.1

## Hint 1

Two questions, asked separately. First: which claims are about this section? Only the claim's own list of source
ids answers that, and each id is looked up in the expected rows to find its row name, which masking.section_of turns
into a section. Second: which claims are valid? validate_claims already answers that for the whole reply. The score
is where the two answers meet.

## Hint 2

Run validate_claims on the whole parsed reply, never on the citing claims alone: an inference that derives from a
claim of another section would lose the claim it points to. The rejections come back keyed by claim id as text, so
compare ids as text too, and build the set of rejected ids inside grade, not on the grader.

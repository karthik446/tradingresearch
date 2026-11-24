# Hints: w1l4.1

## Hint 1

For `rule_targets`: a rule is a line the variant has and the base does not, so collect the base's lines (stripped)
first and keep the variant's other non-blank lines, in order. Then file each rule under every class one of whose
`CLASS_WORDS` options it holds in full, ignoring case. Every class is a key, with or without rules.

## Hint 2

For the prompt: give each of the four target classes one rule, in words the model will meet: window names,
inferences naming what their parents never cite, opinions that cite, labels in `{value}`. Where the rule already
lives (the opinion line, the table-name line), extend that line rather than adding a second rule. Say what the model
must not do. `judgement_in_fact` needs a judge and the rest are rare; leave them. Run the observe after each rule.

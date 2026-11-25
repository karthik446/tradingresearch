# Hints: w5l2.1

## Hint 1

An ablation removes one part and keeps everything else. So the three arms should be as alike as the file can make
them: the same prompt, the same mode, the same model, the same route. The one thing that changes from arm to arm is
the list of sections it never shows the model, and each arm's name says what that list holds.

## Hint 2

Anything an arm does not set it takes from the top of the file, so the safest arm sets as little as it can: a name,
the prompt and its drop list. The arm that shows everything still gets a drop list, an empty one. The section names
are the ones the masking module sorts rows into, spelt exactly as it spells them, each in a list even when it is
alone.

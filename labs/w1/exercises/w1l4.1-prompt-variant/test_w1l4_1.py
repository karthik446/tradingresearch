"""w1l4.1 prompt variant: prompts/analyze-2.txt changes only the rules your taxonomy points at.

The check is structural: it reads your words. It cannot tell whether a rule works (only a paid run can), only that
each of the four target classes has a rule, that the window, inference and opinion rules do not point the wrong way,
and that nothing else moved. Read your rules for meaning yourself.
"""

import difflib
import re
from pathlib import Path

import tradingresearch

REPO = Path(tradingresearch.__file__).resolve().parents[2]
CLASSES = {  # target class (the ids lab w1l2 fixes) -> words one of your added lines must contain (all of a tuple)
    "window_name": [("window",), ("200-day",), ("20-day",)],
    "inference_wider": [("inference", "cite"), ("derived_from", "cite")],
    "opinion_cites": [("opinion", "derived_from"), ("opinion", "source_ids")],
    "label_in_value": [("placeholder",), ("label", "text")],
}
ASKS_FOR_CITATIONS = re.compile(r"non-?empty|not empty|at least one|must (?:list|cite|include|name)")
SAYS_NONE = re.compile(r"\bempty\b|\bno\b|\bnever\b|\bnothing\b|\bnone\b")
SAYS_NOT = re.compile(r"\bnever\b|\bnot\b|\bno\b|\bavoid\b|n't\b")
LIMITS = re.compile(r"\bonly\b|\bmust not\b|\bmay not\b|\bnever\b|\bcannot\b")
PERMITS = re.compile(r"\bprefer|\bany\b|\balso\b|\bfreely\b")


def texts() -> tuple[list[str], list[str]]:
    old = (REPO / "prompts" / "analyze-1.txt").read_text().splitlines()
    path = REPO / "prompts" / "analyze-2.txt"
    assert path.exists(), "prompts/analyze-2.txt does not exist: copy analyze-1.txt and change only the rules"
    return old, path.read_text().splitlines()


def added() -> list[str]:
    old, new = texts()
    return [line[1:].lower() for line in difflib.unified_diff(old, new, lineterm="", n=0)
            if line.startswith("+") and not line.startswith("+++")]


def test_the_variant_changes_something():
    old, new = texts()
    assert old != new, (
        "prompts/analyze-2.txt is analyze-1.txt word for word. Add one rule for each of the four target classes: "
        "window_name (31 claims), inference_wider (15 analyses), opinion_cites (5) and label_in_value (4)."
    )


def test_each_targeted_class_has_a_rule():
    lines = added()
    missing = [cls for cls, options in CLASSES.items()
               if not any(all(word in line for word in words) for line in lines for words in options)]
    assert not missing, (
        f"no added line addresses target class(es) {missing}. Each rule should name the thing that goes wrong in "
        "words the model will meet: window names such as '200-day', citations of an inference, an opinion's "
        "derived_from, a label put in {value}."
    )


def test_only_the_rules_moved():
    old, new = texts()
    for kept in (old[0], old[-1]):
        assert kept in new, (
            f"the line {kept!r} is gone. One change per experiment: if the role or the closing line also moves, a "
            "difference cannot be traced to the rules."
        )


def test_the_opinion_rule_forbids_citations():
    rules = [line for line in added() if "opinion" in line and ("derived_from" in line or "source_ids" in line)]
    wrong = [line.strip() for line in rules if ASKS_FOR_CITATIONS.search(line) or not SAYS_NONE.search(line)]
    assert not wrong, (
        f"your opinion rule {wrong[0]!r} reads as asking opinions to cite. Class opinion_cites is the opposite failure: "
        "an opinion that lists derived_from or source_ids, which the record rules reject. This check only reads "
        "words, so read the rule once more for what it tells the model to do."
    )


def test_the_window_rule_forbids_windows():
    rules = [line for line in added() if "window" in line or "200-day" in line or "20-day" in line]
    wrong = [line.strip() for line in rules if PERMITS.search(line) or not SAYS_NOT.search(line)]
    assert not wrong, (
        f"your window rule {wrong[0]!r} reads as allowing window names. Class window_name is the failure: '200-day' "
        "in a claim's text, which the digit check rejects. The rule has to tell the model not to use them. This "
        "check only reads words, so read the rule once more for what it tells the model to do."
    )


def test_the_inference_rule_limits_what_it_names():
    rules = [line for line in added() if "cite" in line and ("inference" in line or "derived_from" in line)
             and "opinion" not in line]
    wrong = [line.strip() for line in rules if PERMITS.search(line) or not LIMITS.search(line)]
    assert not wrong, (
        f"your inference rule {wrong[0]!r} reads as letting an inference name more than its parents cite. Class "
        "inference_wider is that failure, which InferencesGrounded flags. The rule has to limit the inference to what "
        "its derived_from claims cite. This check only reads words, so read the rule once more."
    )

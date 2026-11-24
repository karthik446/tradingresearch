"""w1l4.1 prompt variant: rule_targets in src/tradingresearch/replay.py, then prompts/analyze-2.txt.

The first tests call rule_targets on short prompts written here. The rest read prompts/analyze-2.txt. That check is
structural: it reads your words. It cannot tell whether a rule works (only a paid run can), only that each of the
four target classes has a rule, that the window, inference, opinion and label rules do not point the wrong way, and
that no line of analyze-1 outside its rule lines moved. Read your rules for meaning yourself.
"""

import difflib
import re
from pathlib import Path

import tradingresearch
from tradingresearch.replay import rule_targets

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
VALUE, TEXT = r"(?:the )?(?:\{value\}|\"value\"|value\b)", r"(?:the )?(?:\"text\"|text\b)"
INTO_VALUE, OUT_OF_VALUE = re.compile(rf"\b(?:in|into|to) {VALUE}"), re.compile(rf"\bout of {VALUE}")
INTO_TEXT = re.compile(rf"\b(?:in|into|to) {TEXT}")
RULE_LINES = ('- tag "inference":', "  sentence; source_ids is empty.", '- tag "opinion":', "- Write numbers ONLY",
              "  (sma_200, high_20, rsi_14).")  # the analyze-1 lines that hold the rules a variant may rewrite
BASE = "Name indicators by their table name, never by their window.\nKeep it short.\n"


def none_but(**rules: list[str]) -> dict[str, list[str]]:
    return {name: rules.get(name, []) for name in CLASSES}


def test_rule_targets_lists_every_class():
    got = rule_targets(BASE, BASE)
    assert got == none_but(), (
        f"rule_targets returned {got!r} for two identical prompts. Two identical prompts add no rule, and every target "
        f"class is still a key: {none_but()!r}. The observe prints one line per class, rule or not."
    )


def test_a_line_in_both_prompts_is_no_rule():
    variant = BASE.replace("Keep it short.", "  {value} is the only placeholder.\nKeep it short.")
    got = rule_targets(BASE, variant)
    kept = [rule for rules in got.values() for rule in rules if rule in BASE]
    assert not kept, (
        f"rule_targets filed {kept[0]!r} as a rule, but that line is in both prompts. A rule is a line the variant has "
        "and the base does not; otherwise every prompt would get credit for the rules it started with."
    )
    want = none_but(label_in_value=["{value} is the only placeholder."])
    assert got == want, f"rule_targets returned {got!r} for a variant that adds one indented line; expected {want!r}"


def test_a_rule_counts_whatever_its_case():
    variant = BASE + "Inference claims cite only what their parents cite.\n"
    got = rule_targets(BASE, variant)
    assert got.get("inference_wider") == ["Inference claims cite only what their parents cite."], (
        "rule_targets filed nothing under inference_wider for the added rule 'Inference claims cite only what their "
        f"parents cite.' (got {got!r}). A rule that starts with a capital names the same class: 'Inference' and "
        "'inference' are one word to the model."
    )


def test_a_rule_needs_every_word_of_an_option():
    variant = BASE + "Every inference states its steps.\nOpinions are judgements.\n"
    got = rule_targets(BASE, variant)
    assert got == none_but(), (
        f"rule_targets returned {got!r} for a variant that adds 'Every inference states its steps.' and 'Opinions are "
        "judgements.'. Neither line names a class: a rule names one only when it holds every word of one option, so "
        "inference_wider needs 'inference' together with 'cite', and opinion_cites needs 'opinion' together with "
        "'derived_from' or 'source_ids'. A line that only mentions a claim tag says nothing about its failure."
    )


def test_rules_keep_the_variants_order():
    rules = ["Never write a window such as 200-day.", "Avoid 20-day as well."]
    got = rule_targets(BASE, BASE + "\n".join(rules) + "\n")
    assert got.get("window_name") == rules, (
        f"rule_targets filed {got.get('window_name')!r} under window_name for a variant that adds {rules!r}, in that "
        "order. A class's rules stay in the order the variant has them, so the observe reads like the prompt."
    )


def test_one_rule_can_name_two_classes():
    rule = "An opinion has empty derived_from; an inference may cite only what its parents cite."
    got = rule_targets(BASE, BASE + rule + "\n")
    want = none_but(inference_wider=[rule], opinion_cites=[rule])
    assert got == want, (
        f"rule_targets returned {got!r} for one added line that holds 'opinion' with 'derived_from' and 'inference' "
        f"with 'cite'. That line names opinion_cites and inference_wider, so it is listed under each: {want!r}."
    )


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
    at = 0
    for line in (line for line in old if not line.startswith(RULE_LINES)):
        assert line in new[at:], (
            f"the line {line!r} of analyze-1.txt is missing from analyze-2.txt, or out of its place. Only the "
            "inference, opinion and numbers lines may be rewritten, and new lines added; every other line stays word "
            "for word, in the same order. One change per experiment: if the role, the format, the source rule or the "
            "closing line also moves, a difference cannot be traced to the rules."
        )
        at = new.index(line, at) + 1


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


def test_the_label_rule_keeps_labels_out_of_value():
    sentences = [part.strip() for line in added() for part in re.split(r"(?<=\.)\s+", line) if "label" in part]
    wrong = [s for s in sentences if (INTO_VALUE.search(s) and not (SAYS_NOT.search(s) or OUT_OF_VALUE.search(s)))
             or not (INTO_TEXT.search(s) or SAYS_NOT.search(s) or OUT_OF_VALUE.search(s))]
    assert not wrong, (
        f"your label rule {wrong[0]!r} reads as putting a label in value. Class label_in_value is that failure: a text "
        "label such as the regime written as {value} while value is null, which the placeholder check rejects as "
        "empty_placeholder. The rule has to keep labels out of value. This check only reads words, so read the rule "
        "once more for what it tells the model to do."
    )

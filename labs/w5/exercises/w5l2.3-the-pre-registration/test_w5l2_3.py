"""w5l2.3 the pre-registration: the comment block above the config's first key holds three items, each once, each on a
line of its own that starts with its label (after `#`, and optionally `- `): `Primary metric:` naming claims_valid,
`Guard metric:` naming parsed, and `Rule:` naming the primary metric and saying when a dropped section stays and
when it goes by the 95% interval.

An item runs from its label to the next blank comment line, the next line starting with `- ` or the next label.
The grader an item names is the first of the config's graders its text mentions as a whole word.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import experiment  # noqa: E402

LABELS = ("Primary metric:", "Guard metric:", "Rule:")


def items() -> dict[str, list[str]]:
    """Each label's items above the first key, as their text."""
    found: dict[str, list[str]] = {label: [] for label in LABELS}
    current = None
    for line in fakea.CONFIG.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            break
        text = line.lstrip("#").strip()
        bullet = text.startswith("- ")
        text = text.removeprefix("- ")
        label = next((x for x in LABELS if text.startswith(x)), None)
        if label:
            found[label].append(text)
            current = label
        elif current and text and not bullet:
            found[current][-1] += " " + text
        else:
            current = None
    return found


def named(text: str) -> str | None:
    """The first of the config's graders the text mentions as a whole word."""
    graders = experiment.load(fakea.CONFIG).graders
    hits = [(m.start(), g) for g in graders for m in re.finditer(rf"(?<![\w-]){re.escape(g)}(?![\w-])", text)]
    return min(hits)[1] if hits else None


def test_three_items_above_the_first_key():
    found = items()
    counts = {label: len(texts) for label, texts in found.items()}
    assert set(counts.values()) == {1}, (
        f"above the first key, items per label: {counts}; expected each of {list(LABELS)} once, every one before "
        f"the first key, so the file shows them to anyone reading the config")


def test_the_primary_and_guard_metrics():
    found = items()
    primary, guard = (found[x][0] if found[x] else "" for x in LABELS[:2])
    assert named(primary) == "claims_valid", (
        f"the primary metric names {named(primary)!r} ({primary[:120]!r}); expected claims_valid")
    assert named(guard) == "parsed", f"the guard metric names {named(guard)!r} ({guard[:120]!r}); expected parsed"


def test_the_rule_says_when_a_section_stays_and_when_it_goes():
    rule = (items()["Rule:"] or [""])[0]
    words = re.findall(r"[\w%-]+", rule.lower())
    missing = [w for w in ("claims_valid", "stays", "goes", "interval", "95%") if w not in words]
    assert not missing, f"the rule ({rule[:200]!r}) does not say {missing}"
    assert named(rule) == "claims_valid", (
        f"the rule decides on {named(rule)!r} ({rule[:200]!r}); expected claims_valid: the first grader the rule "
        f"names is the one its interval decides on, and that is the primary metric")

"""Week 8 acceptance: the routing experiment (`experiments/routing.toml`) and ADR-011.

Specs: REPO-PLAN "Week 8" and §1.3, G15-SPIKE §2 and §4. The plumbing (the `route` and `cache` arm knobs, the Haiku
price, `tr usage --by step|model`, the plan pre-flight, `tr grade --judge --batch`) ships at week-8-start with its own
tests. Your two files are looked up inside each test, so before you write them each of the six contract tests fails
with `learner part missing: ...` and the rest of the suite still runs. The tests that run the same checks on a small
example (bottom of this file) need no learner file and pass from the start, so no check passes on nothing.

The contract, in the names these tests use:
- **Experiment.** `experiments/routing.toml` loads (`experiment.load`):
  - every arm is a pipeline arm (`kind = "pipeline"`), over at least 10 tickers;
  - the first arm is the baseline, and the only arm with no `route` and no `cache`;
  - a routed arm: its `route.analyze` is not the baseline model, and its thesis runs on the baseline model
    (`route.thesis` the baseline model, or left out);
  - a cached arm: identical to the baseline except its name and `cache`;
  - the same `prompt` and `thesis_prompt` on every arm, and `all_claims_valid` among the graders.
- **Prices.** `anthropic.prices` knows every model the config may ask (`experiment.models`: each arm's model, route
  step models and fallback), so the run cannot stop on a missing price.
- **ADR.** `docs/adr/ADR-011-*.md` starts `# ADR-011` and records:
  - `**Status:**`, `**Options considered.**` (at least two, one per bullet or numbered line), `**Decision.**`,
    `**Consequences.**`, `**Readings.**` (with a link), and it names `routing.toml`;
  - a `**Pre-registration...**` paragraph, before `**Decision.**`, that names `all_claims_valid`, `NoWorseThan`, the
    margin (the word and a number between 0 and 1), the item count (tickers x sessions of routing.toml) and the cap
    (`max_usd_per_arm`);
  - the routing table: one column per arm name of routing.toml, and rows for `all_claims_valid`, `$ per ticker-day`,
    `p50`, `p95` and `thesis changed`;
  - the judge table: a `sync` column and a `batch` column, and rows for `cost per call`, `turnaround` and
    `cost per day at 10x shortlist`.
  - Each cell is a plain number (units go in the row label; an interval in brackets may follow) or `awaiting
    experiment` in the routing table, `awaiting run` in the judge table. `n/a` is allowed in the baseline's
    `thesis changed` cell and anywhere in the judge table. The `run_<16 hex>` ids the routing numbers came from go
    beside the table, not in a cell; once a routing cell holds a number, the ADR must name at least one.

Not tested: that ADR-011's pre-registration was committed before the paid run. Code cannot see commit order; the
runbook ("Week 8 contract") gives the order.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from tradingresearch import experiment
from tradingresearch.providers import anthropic

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments" / "routing.toml"
ADRS = ROOT / "docs" / "adr"
AWAITING = "awaiting experiment"
AWAITING_RUN = "awaiting run"
NUMBER = r"\$?-?\d[\d,]*(?:\.\d+)?\s*%?"
CELL = re.compile(rf"{NUMBER}(?:\s*\[{NUMBER},\s*{NUMBER}\])?")  # a number, optionally its interval
RUN_ID = r"\brun_[0-9a-f]{16}\b"
ROUTING_ROWS = ("all_claims_valid", "$ per ticker-day", "p50", "p95", "thesis changed")
JUDGE_ROWS = ("cost per call", "turnaround", "cost per day at 10x shortlist")


def missing(what: str) -> None:
    pytest.fail(f"learner part missing: {what} (contract in tests/test_week8.py)", pytrace=False)


def learner(path: Path, what: str) -> str:
    """The learner file's text; missing or empty fails the test with what to write."""
    if not path.exists() or not path.read_text().strip():
        missing(f"{path.relative_to(ROOT)} ({what})")
    return path.read_text()


def load(path: Path) -> experiment.Config:
    try:
        return experiment.load(path)
    except SystemExit as exc:
        pytest.fail(str(exc), pytrace=False)


def routing() -> experiment.Config:
    learner(CONFIG, "the routing experiment: a baseline, a routed and a cached pipeline arm")
    return load(CONFIG)


def adr() -> str:
    found = sorted(ADRS.glob("ADR-011-*.md"))
    if not found:
        missing("docs/adr/ADR-011-<slug>.md (the model-routing ADR)")
    return learner(found[0], "the model-routing ADR")


def tables(text: str) -> list[list[list[str]]]:
    """The cells of every markdown table, separator rows dropped."""
    found, block = [], []
    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            block.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif block:
            found.append([cells for cells in block if not set("".join(cells)) <= set("-: ")])
            block = []
    return found


def bare(cell: str) -> str:
    return cell.lower().strip("`* ")


def table(text: str, columns: set[str], what: str) -> tuple[list[str], list[list[str]]]:
    found = [t for t in tables(text) if t and columns <= {bare(c) for c in t[0]}]
    assert found, f"no {what} table with the columns {sorted(columns)}"
    header, *body = found[0]
    return [bare(c) for c in header], body


def rows(body: list[list[str]], names: tuple[str, ...]) -> None:
    for name in names:
        assert [cells for cells in body if name in bare(cells[0])], f"no table row for {name}"


# ---------- the checks (the contract tests and the example tests share them) ----------

def check_arms(config: experiment.Config) -> None:
    arms = list(config.arms)
    assert [arm for arm in arms if arm.kind == "pipeline"] == arms, "every arm is a pipeline arm"
    assert len(set(config.tickers)) >= 10, f"{len(set(config.tickers))} tickers, at least 10"
    plain = [arm.name for arm in arms if arm.route == experiment.Route() and arm.cache is None]
    assert plain == [arms[0].name], f"one arm with no route and no cache, the first (the baseline): {plain}"
    base = arms[0]
    assert [arm for arm in arms if arm.route.analyze and arm.route.analyze != base.model
            and arm.thesis_model == base.model], \
        f"a routed arm: route.analyze is not {base.model}, and the thesis runs on {base.model}"
    assert [arm for arm in arms if arm.cache and replace(arm, name=base.name, cache=None) == base], \
        f"a cached arm: identical to {base.name} except its name and `cache`"
    assert {(arm.prompt, arm.thesis_prompt) for arm in arms} == {(base.prompt, base.thesis_prompt)}, \
        "the same prompt and thesis_prompt on every arm"
    assert "all_claims_valid" in config.graders, "all_claims_valid among the graders"


def check_prices(config: experiment.Config) -> None:
    models = experiment.models(config)
    try:
        anthropic.prices(models)
    except (KeyError, anthropic.WrongProvider) as exc:
        pytest.fail(f"anthropic.prices({models}): {exc}", pytrace=False)


def check_record(text: str) -> None:
    assert text.startswith("# ADR-011"), text[:40]
    for label in ("**Status:**", "**Options considered.**", "**Decision.**", "**Consequences.**", "**Readings.**"):
        assert label in text, label
    options = re.split(r"\n\*\*", text.split("**Options considered.**", 1)[1], maxsplit=1)[0]
    listed = [line for line in options.splitlines() if re.match(r"\s*(?:[-*]|\d+\.)\s+\S", line)]
    assert len(listed) >= 2, "list at least two options, one per bullet or numbered line"
    assert "routing.toml" in text
    assert re.search(r"https?://", text.split("**Readings.**", 1)[1]), "readings need a link"


def check_prereg(text: str, config: experiment.Config) -> None:
    assert "**Pre-registration" in text, "no **Pre-registration...** paragraph"
    assert "**Decision.**" in text and text.index("**Pre-registration") < text.index("**Decision.**"), \
        "the pre-registration sits before **Decision.**"
    paragraph = re.split(r"\n\*\*", text.split("**Pre-registration", 1)[1], maxsplit=1)[0]
    numbers = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", paragraph)]
    for term in ("all_claims_valid", "NoWorseThan"):
        assert term in paragraph, f"the pre-registration names {term}"
    assert "margin" in paragraph.lower() and [n for n in numbers if 0 < n < 1], "the pre-registration names the margin"
    items = len(config.tickers) * len(config.sessions)
    assert items in numbers, f"the pre-registration names the item count ({items})"
    assert config.max_usd_per_arm in numbers, f"the pre-registration names the cap ({config.max_usd_per_arm})"


def check_routing_table(text: str, config: experiment.Config) -> None:
    names = {arm.name.lower() for arm in config.arms}
    header, body = table(text, names, "routing")
    rows(body, ROUTING_ROWS)
    base = header.index(config.arms[0].name.lower())
    numbers = []
    for cells in body:
        for column, cell in enumerate(cells[1:], start=1):
            na = "thesis changed" in bare(cells[0]) and column == base and cell.lower() == "n/a"
            assert CELL.fullmatch(cell) or cell.lower() == AWAITING or na, f"not a number or {AWAITING}: {cell!r}"
            numbers += [cell] if CELL.fullmatch(cell) else []
    if numbers:
        assert re.search(RUN_ID, text), "a measured number needs the run id it came from"


def check_judge_table(text: str) -> None:
    _, body = table(text, {"sync", "batch"}, "judge")
    rows(body, JUDGE_ROWS)
    for cells in body:
        for cell in cells[1:]:
            assert CELL.fullmatch(cell) or cell.lower() in (AWAITING_RUN, "n/a"), \
                f"not a number, {AWAITING_RUN} or n/a: {cell!r}"


# ---------- the contract (your files) ----------

def test_the_routing_experiment_has_baseline_routed_and_cached_arms():
    check_arms(routing())


def test_every_routing_model_has_an_anthropic_price():
    check_prices(routing())


def test_adr_011_records_the_options_the_decision_and_the_readings():
    check_record(adr())


def test_adr_011_preregisters_the_rule():
    check_prereg(adr(), routing())


def test_adr_011_has_the_routing_comparison_table():
    check_routing_table(adr(), routing())


def test_adr_011_has_the_judge_sync_vs_batch_table():
    check_judge_table(adr())


# ---------- the same checks on a small example (no learner file) ----------

EXAMPLE_CONFIG = """\
name = "routing-example"
model = "anthropic/claude-sonnet-5.5"
max_usd_per_arm = 3.00
tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO", "CAT"]
sessions = ["2026-11-13"]
graders = ["parsed", "claims_valid", "all_claims_valid"]

[[arms]]
name = "sonnet"
kind = "pipeline"
prompt = "analyze-3"

[[arms]]
name = "routed"
kind = "pipeline"
prompt = "analyze-3"
route = { analyze = "anthropic/claude-haiku-5.5", fallback = "anthropic/claude-sonnet-5.5" }

[[arms]]
name = "cached"
kind = "pipeline"
prompt = "analyze-3"
cache = "5m"
"""

EXAMPLE_ADR = """\
# ADR-011: example (a test fixture, not a decision)

**Status:** proposed

**Options considered.**
- Sonnet on both steps.
- Haiku on analyze, Sonnet on thesis.

**Pre-registration.** `routed` passes if `NoWorseThan("all_claims_valid", margin=0.15, bound="ci_lower")` holds
against `sonnet`, 10 items per arm, cap $3.00 per arm (`routing.toml`).

| metric | sonnet | routed | cached |
|---|---|---|---|
| `all_claims_valid` | awaiting experiment | awaiting experiment | awaiting experiment |
| $ per ticker-day | awaiting experiment | awaiting experiment | awaiting experiment |
| p50 latency per item (s) | awaiting experiment | awaiting experiment | awaiting experiment |
| p95 latency per item (s) | awaiting experiment | awaiting experiment | awaiting experiment |
| thesis changed | n/a | awaiting experiment | awaiting experiment |

| judge | sync | batch |
|---|---|---|
| cost per call ($) | awaiting run | awaiting run |
| turnaround (s) | awaiting run | n/a |
| cost per day at 10x shortlist ($) | awaiting run | awaiting run |

**Decision.** Awaiting the run.

**Consequences.** None yet.

**Readings.** https://platform.claude.com/docs/en/about-claude/pricing
"""

MEASURED = {"| `all_claims_valid` | awaiting experiment | awaiting experiment |":
            "| `all_claims_valid` | 0.900 [0.80, 1.00] | 0.800 |",
            "| thesis changed | n/a | awaiting experiment |": "| thesis changed | n/a | 30% |"}

CHECKS = {
    "arms": lambda config, text: check_arms(config),
    "prices": lambda config, text: check_prices(config),
    "record": lambda config, text: check_record(text),
    "prereg": lambda config, text: check_prereg(text, config),
    "routing_table": lambda config, text: check_routing_table(text, config),
    "judge_table": lambda config, text: check_judge_table(text),
}

# (check, file, old, new): one edit to the example that the check must refuse
BROKEN = {
    "no_cached_arm": ("arms", "config", 'cache = "5m"\n', ""),
    "unpriced_fallback": ("prices", "config", 'fallback = "anthropic/claude-sonnet-5.5"',
                          'fallback = "anthropic/claude-nope-1"'),
    "one_option": ("record", "adr", "- Haiku on analyze, Sonnet on thesis.\n", ""),
    "decision_first": ("prereg", "adr", "**Pre-registration.**", "**Decision.** Routed.\n\n**Pre-registration.**"),
    "no_margin": ("prereg", "adr", "margin=0.15, ", ""),
    "arm_not_in_table": ("routing_table", "adr", "| metric | sonnet | routed | cached |", "| metric | sonnet | routed |"),
    "number_without_run_id": ("routing_table", "adr", "| $ per ticker-day | awaiting experiment |",
                              "| $ per ticker-day | 0.038 |"),
    "unit_in_a_judge_cell": ("judge_table", "adr", "| turnaround (s) | awaiting run |", "| turnaround (s) | ~2 h |"),
}


def example(tmp_path: Path, config: str = EXAMPLE_CONFIG) -> experiment.Config:
    path = tmp_path / "routing.toml"
    path.write_text(config)
    return load(path)


@pytest.mark.parametrize("check", list(CHECKS))
def test_each_check_passes_on_the_example(check, tmp_path):
    CHECKS[check](example(tmp_path), EXAMPLE_ADR)


def test_the_routing_table_takes_numbers_once_a_run_id_is_beside_it(tmp_path):
    text = EXAMPLE_ADR
    for old, new in MEASURED.items():
        assert old in text, old
        text = text.replace(old, new)
    text = text.replace("**Decision.**", "Runs: run_0123456789abcdef.\n\n**Decision.**")
    check_routing_table(text, example(tmp_path))


@pytest.mark.parametrize("case", list(BROKEN))
def test_each_check_refuses_a_broken_example(case, tmp_path):
    check, where, old, new = BROKEN[case]
    source = EXAMPLE_CONFIG if where == "config" else EXAMPLE_ADR
    assert old in source, old
    edited = source.replace(old, new, 1)
    config = example(tmp_path, edited) if where == "config" else example(tmp_path)
    text = edited if where == "adr" else EXAMPLE_ADR
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        CHECKS[check](config, text)

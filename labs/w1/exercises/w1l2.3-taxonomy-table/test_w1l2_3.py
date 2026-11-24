"""w1l2.3 taxonomy table: code_classes in src/tradingresearch/taxonomy.py, then 5 to 8 failure classes in
evals/taxonomy.md, each with counts, what catches it and a real example.

code_classes is called on the recorded observe run. The table's examples and the two classes the code checks
already find (window_name, label_in_value) are looked up in the same run.
"""

import json
import os
import re
from pathlib import Path

import tradingresearch
from tradingresearch.analyze import validate_claims
from tradingresearch.taxonomy import code_classes

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
REPO = Path(tradingresearch.__file__).resolve().parents[2]
RUN = DATA / "observe.jsonl"
REASONS = {"number_in_text", "bad_placeholder", "empty_placeholder", "unknown_source", "number_in_opinion",
           "unsourced_number", "bad_derivation", "not_a_claim"}
REQUIRED = {  # class id -> the later exercise that reads it under this name
    "window_name": "w1l4.1 writes a rule for it",
    "inference_wider": "w1l3.6 compares the grader's flags with it",
    "opinion_cites": "w1l4.1 writes a rule for it",
    "label_in_value": "w1l4.1 writes a rule for it",
}
WINDOW = re.compile(r"\b\d+-day\b", re.IGNORECASE)
HOW = {"window_name": "rejected as number_in_text and naming a window such as '200-day'",
       "label_in_value": "rejected as empty_placeholder", "cascade": "rejected as bad_derivation"}


def pack() -> list[dict]:
    return [json.loads(line) for line in RUN.open()]


def found_by_code() -> dict[str, dict[str, list[str]]]:
    """class -> item -> claim ids, for what the code checks find by themselves."""
    hits: dict[str, dict[str, list[str]]] = {name: {} for name in HOW}
    for row in pack():
        texts = {c.get("id"): str(c.get("text") or "") for c in row["output_parsed"]["claims"]}
        for x in validate_claims(row["output_parsed"], row["values"], "an_lab")[1]:
            if x.reason == "number_in_text" and WINDOW.search(texts.get(x.claim, "")):
                hits["window_name"].setdefault(row["item"], []).append(x.claim)
            elif x.reason == "empty_placeholder":
                hits["label_in_value"].setdefault(row["item"], []).append(x.claim)
            elif x.reason == "bad_derivation":
                hits["cascade"].setdefault(row["item"], []).append(x.claim)
    return hits


def size(by_item: dict[str, list[str]]) -> tuple[int, int]:
    return sum(map(len, by_item.values())), len(by_item)


def test_code_classes_lists_three_classes():
    got = code_classes(RUN)
    assert got and set(HOW) <= set(got), (
        f"code_classes returned {got!r} for the observe run. It should return window_name, label_in_value and "
        "cascade, each as item -> claim ids: e.g. label_in_value lists KO:2026-11-12 ['c9'], the claim rejected as "
        "empty_placeholder there."
    )


def test_a_number_in_text_without_a_window_is_not_window_name():
    got = code_classes(RUN)["window_name"]
    wrong = [f"{item} {claim}" for item, claim in (("CAT:2026-11-12", "c5"), ("XOM:2026-11-13", "c7"),
                                                   ("XOM:2026-11-13", "c9")) if claim in got.get(item, [])]
    assert not wrong, (
        f"window_name lists {', '.join(wrong)}. These are rejected as number_in_text, but their text names no window: "
        "CAT:2026-11-12 c5 says 'the oversold level of 30', XOM:2026-11-13 c7 says '188.5 USD'. window_name is a "
        "number_in_text claim whose text names a window such as '200-day' or '14-day RSI'."
    )


def test_code_classes_matches_the_recording():
    got, want = code_classes(RUN), found_by_code()
    for name in HOW:
        for item in sorted(set(got[name]) | set(want[name])):
            assert got[name].get(item, []) == want[name].get(item, []), (
                f"{name} in {item}: code_classes lists {got[name].get(item, [])}, but the claims {HOW[name]} there "
                f"are {want[name].get(item, [])} (in reply order)"
            )


def claim(cid: str, tag: str, text: str, value: float | None, sources: list[str], parents: list[str]) -> dict:
    return {"id": cid, "tag": tag, "text": text, "value": value, "unit": "usd" if value is not None else None,
            "source_ids": sources, "derived_from": parents, "steps": None}


def trace(item: str, values: dict, *claims: dict) -> dict:
    return {"item": item, "analysis_id": "an_" + item[:3].lower().rjust(16, "0"), "values": values,
            "output_parsed": {"claims": list(claims)}}


def test_code_classes_reads_the_run_it_is_given(tmp_path):
    clean = trace("QQQ:2030-01-02", {"src_a": 412.0},
                  claim("c1", "fact", "The close stood at {value} USD.", 412.0, ["src_a"], []))
    failing = trace("ZZZ:2030-01-02", {"src_a": 412.0, "src_b": None},
                    claim("c1", "fact", "The 50-day average stood at {value} USD.", 412.0, ["src_a"], []),
                    claim("c2", "fact", "The regime is labeled {value} today.", None, ["src_b"], []),
                    claim("c3", "inference", "So the trend still points up.", None, [], ["c1"]),
                    claim("c4", "fact", "The close stood 5 USD above it.", None, ["src_a"], []))
    run = tmp_path / "run.jsonl"
    run.write_text("".join(json.dumps(row) + "\n" for row in (clean, failing)))
    want = {"window_name": {"ZZZ:2030-01-02": ["c1"]}, "label_in_value": {"ZZZ:2030-01-02": ["c2"]},
            "cascade": {"ZZZ:2030-01-02": ["c3"]}}
    got = code_classes(run)
    assert got == want, (
        f"on a two-trace run written for this test (QQQ:2030-01-02 clean; ZZZ:2030-01-02 c1 '50-day' in prose, c2 "
        f"{{value}} with value null, c3 standing on c1, c4 '5 USD' in prose) code_classes returned {got}; expected "
        f"{want}. It reads the run it is given, and lists only items with such a claim."
    )
    run.write_text(json.dumps(clean) + "\n")
    got = code_classes(run)
    assert got == {name: {} for name in HOW}, (
        f"on a run whose only trace is clean, code_classes returned {got}; every class is still a key, with no items"
    )


def test_a_window_is_digits_then_day_whatever_its_case(tmp_path):
    failing = trace("ZZZ:2030-01-02", {"src_a": 61.0, "src_b": 412.0},
                    claim("c1", "fact", "The 14-Day RSI stood at {value}.", 61.0, ["src_a"], []),
                    claim("c2", "fact", "The close stood 5 USD above its mid-day level.", None, ["src_b"], []))
    run = tmp_path / "run.jsonl"
    run.write_text(json.dumps(failing) + "\n")
    got = code_classes(run)["window_name"]
    assert got == {"ZZZ:2030-01-02": ["c1"]}, (
        f"on a one-trace run written for this test (c1 '14-Day RSI' in prose, c2 '5 USD' and 'mid-day' in prose; "
        f"both rejected as number_in_text) window_name is {got}; expected {{'ZZZ:2030-01-02': ['c1']}}. A window is "
        "a number of days, digits then '-day', in any case ('14-Day' too); a '-day' word with no digits ('mid-day') "
        "names no window. WINDOW in taxonomy.py says exactly that."
    )


def table() -> list[list[str]]:
    path = REPO / "evals" / "taxonomy.md"
    assert path.exists(), f"{path} does not exist"
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in path.read_text().splitlines() if re.match(r"\|\s*\d+\s*\|", line)]
    return rows


def test_five_to_eight_classes():
    rows = table()
    assert 5 <= len(rows) <= 8, (
        f"taxonomy.md has {len(rows)} class rows; group your 20 notes into 5 to 8 classes (week-1.md §4). Fewer "
        "and the classes say nothing; more and they will not get evals."
    )
    for row in rows:
        assert len(row) == 6, f"row {row[0]} has {len(row)} cells; columns are # | Class | Claims | Analyses | " \
                              "Caught today by | Example"


def test_classes_are_failures_not_validator_reasons():
    names = []
    for row in table():
        name, _, definition = row[1].partition(":")
        assert re.fullmatch(r"[a-z_]+", name.strip()) and definition.strip(), (
            f"class cell {row[1]!r} should be `snake_name: definition`, so labels.csv can use the name"
        )
        names.append(name.strip())
    assert "bad_derivation" not in names and "cascade" not in names, (
        "bad_derivation / cascade is a consequence of a parent's failure, not a class (week-1.md §4): count the "
        "parent's class instead"
    )
    assert not set(names) <= REASONS, (
        f"every class ({', '.join(names)}) is a validator reason. Grouping by reasons hides the failures no check "
        "fires on, which are the ones you most need an eval for."
    )


def test_the_classes_later_exercises_read_are_named_as_given():
    names = {row[1].partition(":")[0].strip() for row in table()}
    missing = [f"{name} ({why})" for name, why in REQUIRED.items() if name not in names]
    assert not missing, (
        f"taxonomy.md has no row for {'; '.join(missing)}. Lab w1l2 fixes these four class ids so later exercises can "
        "find them: keep the name exactly, write your own definition and counts. Other classes are yours to name."
    )


def test_counts_and_caught_by():
    rows, total = table(), sum(len(row["output_parsed"]["claims"]) for row in pack())
    for row in rows:
        claims, analyses = int(row[2]), int(row[3])
        assert 1 <= analyses <= 20 and analyses <= claims <= total, (
            f"{row[1].split(':')[0]}: {claims} claims in {analyses} analyses; each counted analysis has at least one "
            f"failing claim, there are 20 analyses and {total} claims"
        )
    counted = sum(int(row[2]) for row in rows)
    assert counted <= total, (
        f"the Claims column adds up to {counted}, but the observe run has {total} claims. Count each failing claim in "
        "the one class that explains it."
    )
    assert any(row[4].lower().startswith("nothing") for row in rows), (
        "no class is 'Caught today by: nothing'. The point of the table is to find the largest class the code misses."
    )


def test_the_classes_code_finds_match_the_recording():
    rows = {row[1].partition(":")[0].strip(): (int(row[2]), int(row[3])) for row in table()}
    found = found_by_code()
    for name in ("window_name", "label_in_value"):
        claims, analyses = size(found[name])
        assert rows[name] == (claims, analyses), (
            f"{name}: the table says {rows[name][0]} claims in {rows[name][1]} analyses, but the observe run has "
            f"{claims} claims {HOW[name]}, in {analyses} analyses. These two counts come straight from the code "
            "checks: `uv run python -m tradingresearch.taxonomy table` puts your code_classes next to the table."
        )


def test_the_classes_code_finds_say_code_catches_them():
    rows = {row[1].partition(":")[0].strip(): row[4] for row in table()}
    for name, reason in (("window_name", "number_in_text"), ("label_in_value", "empty_placeholder")):
        assert rows[name].lower().startswith("code"), (
            f"{name}: Caught today by says {rows[name]!r}, but the code checks reject every {name} claim "
            f"({HOW[name]}). Write what catches it as the TODO asks, code and the reason, here {reason}."
        )


def test_examples_are_real_claims():
    items = {row["item"]: row for row in pack()}
    for row in table():
        found = re.search(r"\b([A-Z]+) (\d\d-\d\d) (c\d+)\b", row[5])
        assert found, f"{row[1].split(':')[0]}: example {row[5]!r} should start `TICKER MM-DD cN`, e.g. JPM 11-12 c2"
        ticker, day, claim = found.groups()
        item = items.get(f"{ticker}:2026-{day}")
        assert item, f"example {ticker} {day} is not an analysis of the observe run"
        ids = {c["id"] for c in item["output_parsed"]["claims"]}
        assert claim in ids, f"example {ticker} {day} {claim}: that analysis has no claim {claim}"

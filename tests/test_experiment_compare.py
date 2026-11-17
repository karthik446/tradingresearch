"""`experiment.compare` skips, and names, a grader the two arms did not both score on a common item; `tr exp compare`
prints the `tr exp run` compare block for two stored runs (W5fix). Hand-built gigai-core runs, no call."""

from datetime import UTC, datetime

import pytest
from gigai_core import Dataset, DatasetItem, Run, compare as core_compare
from gigai_core.comparison import ComparisonRefused
from gigai_core.providers import ProviderIdentity
from gigai_core.records import RunRecord
from gigai_core.sample import Sample
from gigai_core.score import ScoreRecord

from tradingresearch import analyze as an, experiment
from tradingresearch.cli import main
from tradingresearch.commands.exp import show
from tradingresearch.hashing import new_id

T0 = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)
TICKERS = ("AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO", "CAT")  # compare needs 10 clusters
GRADERS = ("parsed", "claims_valid", "levels_grounded", "edgar_grounded")
DATASET = Dataset.of("ablation", [DatasetItem(id=f"{t}:2026-11-13", cluster_id=t, expected={}, prompt=f"SOURCES {t}")
                                  for t in TICKERS])
IDS = [item.id for item in DATASET.items]


def run(arm: str, scores: dict[str, dict[str, float]]) -> Run:
    """One arm's run: every item asked and parsed; `scores` is grader -> item -> value, an absent item ungraded."""
    run_id = new_id("run")
    samples = [Sample(trace_id=new_id("trace"), run_id=run_id, item_id=item.id, item_version=item.version,
                      cluster_id=item.cluster_id, repeat_index=0, input=(), output_text="{}", output_parsed={},
                      parse_status="ok", outcome="succeeded", error=None, recorded_at=T0) for item in DATASET.items]
    records = [ScoreRecord(score_id=new_id("score"), trace_id=sample.trace_id, grader_id=grader, grader_version="1",
                           kind="code", value=values[sample.item_id], recorded_at=T0)
               for sample in samples for grader, values in scores.items() if sample.item_id in values]
    record = RunRecord(run_id=run_id, dataset=DATASET.ref, settings=an.call_settings("openai/gpt-4.1-nano"),
                       provider=ProviderIdentity(provider="openrouter", endpoint="test", adapter="test"),
                       created_at=T0, tag=f"ablation:{arm}:analyze-3")
    return Run(record=record, items={item.id: item for item in DATASET.items}, samples=tuple(samples),
               scores=tuple(records))


def arms() -> tuple[Run, Run]:
    """`full` and `no-edgar` as W5RefB measured them: EDGAR cited only in `full`, levels cited on disjoint items."""
    full = run("full", {"parsed": dict.fromkeys(IDS, 1.0),
                        "claims_valid": {item: 0.8 + 0.02 * i for i, item in enumerate(IDS)},
                        "levels_grounded": {IDS[0]: 1.0},
                        "edgar_grounded": dict.fromkeys(IDS[:6], 1.0)})
    no_edgar = run("no-edgar", {"parsed": dict.fromkeys(IDS, 1.0),
                                "claims_valid": {item: 0.9 + 0.01 * i for i, item in enumerate(IDS)},
                                "levels_grounded": {IDS[1]: 1.0, IDS[2]: 1.0}})
    return full, no_edgar


def test_core_compare_refuses_both_ways_the_repo_helper_skips():
    full, no_edgar = arms()
    with pytest.raises(ComparisonRefused) as missing:
        core_compare(full, no_edgar, GRADERS)
    assert missing.value.code == "metric_missing"
    with pytest.raises(ComparisonRefused) as disjoint:
        core_compare(full, no_edgar, ("parsed", "levels_grounded"))
    assert disjoint.value.code == "no_paired_items"


def test_a_drop_arm_compares_on_the_shared_graders_and_names_each_skipped_one():
    compared = experiment.compare(*arms(), GRADERS)
    assert [m.metric for m in compared.comparison.metrics] == ["parsed", "claims_valid"]
    assert compared.comparison.items == compared.comparison.clusters == 10
    assert compared.skipped == ("levels_grounded: no item scored in both arms (n=1 vs 2)",
                                "edgar_grounded: not scored in both arms (n=6 vs 0)")


def test_no_grader_scored_on_a_common_item_refuses_and_names_them():
    with pytest.raises(ComparisonRefused, match=r"no grader is scored on a common item in both runs "
                                                r"\(levels_grounded: .*\(n=1 vs 2\); edgar_grounded: .*n=6 vs 0") as e:
        experiment.compare(*arms(), ("levels_grounded", "edgar_grounded"))
    assert e.value.code == "no_shared_metric"


def test_the_printed_block_lists_skipped_graders_before_the_metrics(capsys):
    show("full", "no-edgar", *arms(), GRADERS)
    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == ["compare full -> no-edgar: 10 items, 10 clusters",
                         "    skipped levels_grounded: no item scored in both arms (n=1 vs 2)",
                         "    skipped edgar_grounded: not scored in both arms (n=6 vs 0)"]
    assert [line.split()[0] for line in lines[3:]] == ["parsed", "claims_valid"]
    show("full", "no-edgar", *arms(), ("edgar_grounded",))
    assert capsys.readouterr().out.startswith("compare full -> no-edgar refused: cannot compare: no grader is scored")


def test_tr_exp_compare_on_two_stored_runs_prints_the_exp_run_block(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    full, no_edgar = arms()
    for arm in (full, no_edgar):
        an.save(arm, tmp_path)
    a, b = full.record.run_id, no_edgar.record.run_id
    show("full", "no-edgar", full, no_edgar, GRADERS)  # what `tr exp run` prints for these two arms
    expected = capsys.readouterr().out.splitlines()
    main(["exp", "compare", a, b])
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == f"compare {a} -> {b}: 10 items, 10 clusters"
    assert printed[1:] == expected[1:]
    main(["exp", "compare", a, b, "--graders", "claims_valid,edgar_grounded"])
    printed = capsys.readouterr().out.splitlines()
    assert printed[1] == "    skipped edgar_grounded: not scored in both arms (n=6 vs 0)"
    assert [line.split()[0] for line in printed[2:]] == ["claims_valid"]
    with pytest.raises(SystemExit, match="no stored run run_missing"):
        main(["exp", "compare", a, "run_missing"])

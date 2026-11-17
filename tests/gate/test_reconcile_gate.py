"""Reconcile gate (G5): the cases match the goldens; a moved result fails with a diff and needs a rules bump."""

import json
import shutil

import gate
import pytest
import test_reconcile as fx

from tradingresearch.costs import Costs
from tradingresearch.records import RULES_VERSION

GOLDEN = gate.ROOT / gate.GOLDEN


@pytest.fixture(scope="module")
def outputs():
    return gate.reconcile_outputs()


@pytest.fixture(scope="module")
def moved():
    """A cost change (1 bps commission per side): every graded case moves, the rules_version does not."""
    return gate.reconcile_outputs(Costs(commission_bps=1.0))


def copy(tmp_path):
    golden = tmp_path / gate.GOLDEN
    golden.parent.mkdir(parents=True)
    shutil.copy(GOLDEN, golden)
    return golden


def test_clean_tree_matches_goldens(outputs):
    assert gate.check_reconcile(GOLDEN, outputs) == []


def test_every_fixture_case_is_gated():
    assert {case for _, case, _, _ in gate.CASES} == set(fx.FIXTURES) - {"_about"}


def test_cost_change_fails_with_a_readable_diff(moved):
    problems = gate.check_reconcile(GOLDEN, moved)
    assert "RULES_VERSION bump" in problems[0]
    text = "\n".join(problems)
    assert '-    "cost_bps": 8.0,' in text and '+    "cost_bps": 10.0,' in text  # a stop-class exit: 8 → 10 bps
    assert "--- golden " in text and "+++ now " in text


def test_a_dropped_case_fails(outputs):
    fewer = {name: value for name, value in outputs.items() if name != "exit_target/long"}
    assert "exit_target/long" in "\n".join(gate.check_reconcile(GOLDEN, fewer))


def test_accept_refuses_a_change_without_a_rules_bump(tmp_path, moved):
    golden = copy(tmp_path)
    before = golden.read_bytes()
    problems = gate.accept_reconcile(golden, moved)
    assert problems and problems[0].startswith("refused") and f"still {RULES_VERSION}" in problems[0]
    assert golden.read_bytes() == before


def test_accept_after_a_rules_bump(tmp_path, moved):
    golden = copy(tmp_path)
    stored = json.loads(golden.read_text())
    golden.write_text(json.dumps(stored | {"rules_version": "rules-0"}))  # goldens older than the code's rules
    assert gate.accept_reconcile(golden, moved) == []
    assert json.loads(golden.read_text())["rules_version"] == RULES_VERSION
    assert gate.check_reconcile(golden, moved) == []


def test_accept_of_a_new_case_needs_no_bump(tmp_path, outputs):
    golden = copy(tmp_path)
    stored = json.loads(golden.read_text())
    del stored["cases"]["exit_target/long"]
    golden.write_text(json.dumps(stored))
    assert gate.check_reconcile(golden, outputs) != []
    assert gate.accept_reconcile(golden, outputs) == []
    assert golden.read_bytes() == GOLDEN.read_bytes()


def test_goldens_are_reproducible(tmp_path, outputs):
    golden = copy(tmp_path)
    assert gate.accept_reconcile(golden, outputs) == []
    assert golden.read_bytes() == GOLDEN.read_bytes()

"""Prompt gate (G5): recorded prompts are immutable; a new prompt needs an experiment arm and a recorded hash."""

import json
import shutil
import subprocess
import sys

import gate

PROMPT_V9 = """name = "prompt-v9"
model = "anthropic/claude-sonnet-5.5"
max_usd_per_arm = 1.00
tickers = ["AAPL"]
sessions = ["2026-11-13"]
graders = ["parsed"]

[[arms]]
name = "variant"
prompt = "analyze-9"
"""


def layout(tmp_path):
    """A copy of the files the gate reads; tests edit the copy, never the repo."""
    for folder in ("prompts", "experiments", "tests/gate/golden"):
        shutil.copytree(gate.ROOT / folder, tmp_path / folder)
    (tmp_path / "ci").mkdir()
    shutil.copy(gate.ROOT / gate.HASHES, tmp_path / gate.HASHES)
    return tmp_path


def test_clean_tree():
    assert gate.check_prompts(gate.ROOT) == []


def test_modified_prompt_fails(tmp_path):
    root = layout(tmp_path)
    with (root / "prompts" / "analyze-2.txt").open("ab") as f:
        f.write(b"\n")
    problems = gate.check_prompts(root)
    assert len(problems) == 1 and problems[0].startswith("prompts/analyze-2.txt: bytes changed")
    assert gate.record_prompts(root) == [] and gate.check_prompts(root) == problems  # recording never re-records


def test_deleted_prompt_fails(tmp_path):
    root = layout(tmp_path)
    (root / "prompts" / "thesis-1.txt").unlink()
    assert gate.check_prompts(root)[0].startswith("prompts/thesis-1: recorded")


def test_unregistered_new_prompt_fails(tmp_path):
    root = layout(tmp_path)
    (root / "prompts" / "analyze-9.txt").write_text("A new system prompt.\n")
    problems = gate.check_prompts(root)
    assert len(problems) == 1 and "no experiments/*.toml arm names it" in problems[0]
    assert "analyze-9.txt" in gate.record_prompts(root)[0]
    assert "analyze-9" not in json.loads((root / gate.HASHES).read_text())


def test_new_prompt_with_an_arm_fails_until_recorded(tmp_path, capsys):
    root = layout(tmp_path)
    (root / "prompts" / "analyze-9.txt").write_text("A new system prompt.\n")
    (root / "experiments" / "prompt-v9.toml").write_text(PROMPT_V9)
    assert "--record-prompts" in gate.check_prompts(root)[0]
    assert gate.record_prompts(root) == []
    assert "recorded prompts/analyze-9.txt -> experiment 'prompt-v9'" in capsys.readouterr().out
    assert gate.check_prompts(root) == []


def test_baseline_only_for_a_first_prompt(tmp_path):
    root = layout(tmp_path)
    (root / "prompts" / "thesis-2.txt").write_text("A second thesis prompt.\n")
    assert "thesis-2.txt" in gate.record_prompts(root)[0]  # no arm and not *-1: nothing to record it under
    hashes = json.loads((root / gate.HASHES).read_text())
    hashes["thesis-2"] = {"experiment": "baseline", "sha256": gate._sha256(root / "prompts" / "thesis-2.txt")}
    (root / gate.HASHES).write_text(json.dumps(hashes))
    assert "does not justify it" in gate.check_prompts(root)[0]


def test_gate_command_exit_codes(tmp_path):
    clean = subprocess.run([sys.executable, str(gate.ROOT / "ci" / "gate.py")], capture_output=True, text=True,
                           cwd=gate.ROOT)
    assert clean.returncode == 0 and clean.stdout.startswith("gate: ok"), clean.stderr
    root = layout(tmp_path)
    (root / "prompts" / "analyze-1.txt").write_text("edited\n")
    assert gate.main([], root=root) == 1

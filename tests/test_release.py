"""`ci/release_check.py` (REPO-PLAN Week 9, SPIKE §11): each check passing and failing on a temp git repo, and the
fresh-clone step with a stubbed runner (no real clone, no `uv sync`, no network)."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))

import release_check  # noqa: E402

README = """# tradingresearch

Educational software. Not financial advice. No orders are placed.

```
# a comment in a fence is not a heading: reader setup
```

## Licences

The code is MIT (LICENSE). The guide text is CC BY-NC 4.0. The dataset is CDLA-Permissive-2.0.

## Reference architecture

One journal, one CLI.

## Reader setup

Put ANTHROPIC_API_KEY and APCA_API_KEY_ID in `.env`. Alpaca's market data is US-only.

### Keys

Never commit `.env`.

## Next

Nothing here counts for the reader setup.
"""
FILES = {"LICENSE": "MIT License\n\nCopyright (c) 2026 Kar\n", "README.md": README,
         ".gitignore": "data/\ndata-dev/\n.env\n.idea/\n", "src/app.py": "KEY = 'APCA_API_KEY_ID=not-a-real-id'\n",
         "logo.bin": "sk-" + "ant-" + "a" * 30 + "\0"}  # binary: not scanned
NAMES = list(release_check.CHECKS)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", "-c",
                    "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args], check=True, capture_output=True)


def repo(tmp_path: Path, drop: tuple[str, ...] = (), changes: dict[str, str] | None = None) -> Path:
    """A temp git repo holding FILES minus `drop`, plus or replaced by `changes` (path: text), every file added."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    files = {k: v for k, v in FILES.items() if k not in drop} | (changes or {})
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    git(root, "add", "--force", "--", *files)
    return root


def results(root: Path, capsys, argv: list[str] | None = None) -> tuple[int, dict[str, str]]:
    code = release_check.main(argv or [], root)
    lines = capsys.readouterr().out.splitlines()
    return code, {line.split(" ", 2)[1].rstrip(":"): line for line in lines if line.startswith(("ok ", "FAIL "))}


def test_a_complete_repo_passes_each_check_with_one_line_per_check(tmp_path, capsys):
    code, lines = results(repo(tmp_path), capsys)
    assert code == 0 and list(lines) == NAMES
    assert all(line.startswith(f"ok {name}: ") for name, line in lines.items())
    assert lines["secrets"] == "ok secrets: no secret-shaped string in 4 tracked text files"


@pytest.mark.parametrize(("drop", "changes", "failing", "detail"), [
    (("LICENSE",), {}, "license", "LICENSE missing"),
    ((), {"LICENSE": "Apache License\n"}, "license", "LICENSE does not start `MIT License`"),
    (("README.md",), {}, "readme_licences", "README.md missing"),
    ((), {"README.md": README.replace("CC BY-NC 4.0", "CC BY 4.0")}, "readme_licences",
     "README.md does not name: CC BY-NC 4.0 (guide text)"),
    ((), {"README.md": README.replace("Not financial advice.", "")}, "disclaimer",
     "README.md has no paragraph containing `not financial advice`"),
    ((), {".gitignore": "data-dev/\n.env\n"}, "gitignore", ".gitignore does not cover: data/x.db, .idea/x, data/traces/x"),
    ((), {".env": "A=1\n"}, "tracked_data", "tracked private files: .env"),
    ((), {"data/journal.db": "x\n", "data-dev/x": "y\n"}, "tracked_data",
     "tracked private files: data-dev/x, data/journal.db"),
    ((), {"README.md": README.replace("## Reference architecture", "## Architecture")}, "readme_setup",
     "README.md has no section: reference architecture"),
    ((), {"README.md": README.replace("US-only", "US only")}, "readme_setup",
     "README.md reader setup does not name: US-only"),
    ((), {"README.md": README.replace("## Next", "## Next\n\nAPCA_API_KEY_ID").replace(" and APCA_API_KEY_ID", "")},
     "readme_setup", "README.md reader setup does not name: APCA_API_KEY_ID"),  # a later section does not count
])
def test_each_check_fails_on_its_broken_repo_and_only_it(tmp_path, capsys, drop, changes, failing, detail):
    code, lines = results(repo(tmp_path, drop, changes), capsys)
    assert code == 1 and lines[failing] == f"FAIL {failing}: {detail}"
    assert [name for name, line in lines.items() if line.startswith("FAIL ")] == (
        ["readme_licences", "disclaimer", "readme_setup"] if drop == ("README.md",) else [failing])


@pytest.mark.parametrize(("name", "secret"), [
    ("sk_ant_key", "sk-" + "ant-api03-" + "Ab_9" * 6), ("sk_or_key", "sk-" + "or-v1-" + "0f" * 16),
    ("apca_value", "APCA" + "_API_SECRET_KEY=" + "Zq7" * 4), ("aws_key_id", "AKIA" + "Q7" * 8)])
def test_a_secret_shaped_line_fails_by_file_line_and_pattern_never_the_value(tmp_path, capsys, name, secret):
    code, lines = results(repo(tmp_path, changes={"notes/keys.txt": f"first line\nvalue {secret} here\n"}), capsys)
    assert code == 1 and lines["secrets"] == f"FAIL secrets: 1 secret-shaped strings: notes/keys.txt:2 ({name})"
    assert secret not in "\n".join(lines.values())


def test_named_prefixes_and_placeholders_are_not_secret_shaped(tmp_path, capsys):
    text = "sk-" + "ant-colony and sk-" + "or-v1-… and APCA" + "_API_KEY_ID=not-a-real-id and AKIA" + "SHORT\n"
    code, lines = results(repo(tmp_path, changes={"docs/keys.md": text}), capsys)
    assert code == 0 and lines["secrets"].startswith("ok secrets: ")


class Stub:
    """Records each fresh-clone step; `fail` names the first command word pair that exits 1."""

    def __init__(self, fail: str | None = None):
        self.calls, self.fail = [], fail

    def __call__(self, cmd, cwd, env):
        self.calls.append((cmd, cwd, env))
        failed = self.fail is not None and " ".join(cmd).startswith(self.fail)
        return subprocess.CompletedProcess(cmd, 1 if failed else 0, "", "error: no network\n" if failed else "")


def test_fresh_clone_runs_clone_sync_gate_and_tests_in_a_removed_temp_dir(tmp_path, capsys, monkeypatch):
    root = repo(tmp_path)
    git(root, "commit", "-qm", "init")
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    stub = Stub()
    monkeypatch.setattr(release_check, "run", stub)
    monkeypatch.setenv("TR_PROVIDER", "anthropic")
    code = release_check.main(["--fresh-clone"], root)
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[-2] == "fresh-clone: needs network for `uv sync --frozen`; no key and no model call"
    assert out[-1] == f"ok fresh_clone: HEAD {head[:12]} in a clean clone: uv sync --frozen, ci/gate.py and pytest -q -x pass (the retrieval-index test is deselected)"
    [clone_cmd, *rest] = [cmd for cmd, _, _ in stub.calls]
    temp = Path(clone_cmd[-1]).parent
    assert clone_cmd == ["git", "clone", "--quiet", str(root), str(temp / "repo")]
    assert rest == [["git", "checkout", "--quiet", "--detach", head], ["uv", "sync", "--frozen"],
                    ["uv", "run", "--frozen", "python", "ci/gate.py"], ["uv", "run", "--frozen", "pytest", "-q", "-x", release_check.NO_INDEX_TEST]]
    assert all(cwd == temp / "repo" for _, cwd, _ in stub.calls[1:])
    env = stub.calls[-1][2]
    assert env["TR_DATA_DIR"] == str(temp / "data") and "TR_PROVIDER" not in env and "TR_ENV_FILE" not in env
    assert not temp.exists()  # removed after


def test_a_failing_fresh_clone_step_stops_the_rest_and_fails(tmp_path, capsys, monkeypatch):
    root = repo(tmp_path)
    git(root, "commit", "-qm", "init")
    stub = Stub(fail="uv sync")
    monkeypatch.setattr(release_check, "run", stub)
    code, lines = results(root, capsys, ["--fresh-clone"])
    assert code == 1 and lines["fresh_clone"] == "FAIL fresh_clone: `uv sync --frozen` exited 1: error: no network"
    assert [cmd[:2] for cmd, _, _ in stub.calls] == [["git", "clone"], ["git", "checkout"], ["uv", "sync"]]

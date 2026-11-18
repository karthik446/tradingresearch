"""Tests do not depend on the shell: no `TR_PROVIDER` or `TR_ENV_FILE` leaks in, and the env file is a path that does
not exist unless the test points `TR_ENV_FILE` somewhere itself (monkeypatch.setenv after this fixture wins). A
`live` test is left alone: it reads the real keys on purpose. Every test, live ones included, gets its own
`TR_LEDGER` under tmp_path, so no test appends to the repo's `data/cost-ledger.jsonl`."""

import pytest


@pytest.fixture(autouse=True)
def no_shell_env(request, monkeypatch, tmp_path):
    monkeypatch.setenv("TR_LEDGER", str(tmp_path / "cost-ledger.jsonl"))
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.delenv("TR_PROVIDER", raising=False)
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "absent.env"))

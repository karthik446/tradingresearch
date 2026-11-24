"""Every test under labs/w2/ is a lab check: it carries the `lab` marker, which plain `pytest` deselects
(pyproject.toml addopts `-m 'not live and not lab'`). `tr lab verify` passes `-m lab` to select them.

pytest loads this file before it imports any test module, so the offline guard (tools/offline.py) is installed before
any learner code is imported. Its record of attempts (`offline.HITS`) is cleared only after each test, never before
one: an attempt made while a test module imports learner code stays recorded and is reported by the first test that
runs. A test that passes while its code tried a guarded call (and caught the error) is turned into a failure here; a
test that checks for such attempts itself reads them from the `offline_hits` fixture, and then owns them.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("labs_w2_offline", HERE / "tools" / "offline.py")
offline = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = offline
_spec.loader.exec_module(offline)
offline.install()


@pytest.hookimpl(tryfirst=True)  # before the -m filter deselects by marker
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if HERE in item.path.resolve().parents:
            item.add_marker(pytest.mark.lab)


@pytest.fixture
def offline_hits() -> list[str]:
    """The guarded calls tried since the last test ended (for the first test, since import; tools/offline.py)."""
    return offline.HITS


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    outcome = yield
    report = outcome.get_result()
    if call.when != "call" or "offline_hits" in getattr(item, "fixturenames", ()):
        return
    hits = list(dict.fromkeys(offline.HITS))
    offline.HITS.clear()
    if hits and report.passed:
        report.outcome = "failed"
        report.longrepr = (f"E   The code under test tried {', '.join(hits)} and caught the error. The week-2 labs "
                           f"make no network, subprocess or model call, so an attempt fails the check even when it is "
                           f"swallowed")

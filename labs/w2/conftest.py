"""Every test under labs/w2/ is a lab check: it carries the `lab` marker, which plain `pytest` deselects
(pyproject.toml addopts `-m 'not live and not lab'`). `tr lab verify` passes `-m lab` to select them."""

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)  # before the -m filter deselects by marker
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if HERE in item.path.resolve().parents:
            item.add_marker(pytest.mark.lab)

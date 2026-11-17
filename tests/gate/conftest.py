"""The gate tests import `ci/gate.py` as `gate`; it runs the same checks as `uv run python ci/gate.py`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ci"))

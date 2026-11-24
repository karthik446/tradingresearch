"""Count analyses per failure class from evals/labels.csv (week 1, axial coding).

    uv run python -m tradingresearch.taxonomy evals/labels.csv
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

TAGS = {"cascade"}  # marks on a row, not failure classes: never counted


def class_counts(path: Path) -> dict[str, int]:
    """Analyses per class: a row adds one to each class it lists, however often it lists it.

    Classes are ';'-separated in the `classes` column. Blanks and TAGS are skipped.
    """
    # TODO(w1l2.2) read the CSV with csv.DictReader and count.
    return {}


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "evals/labels.csv")
    counts = class_counts(path)
    for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n:>3}  {name}")
    print(f"{len(counts)} classes in {path}")


if __name__ == "__main__":
    main()

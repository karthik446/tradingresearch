"""Digests and ids in gigai-core's style.

gigai-core's canonical JSON forbids floats (`canonical/encode.py`), because two programs can print the same float
differently. Prices and indicator values are floats, so they are turned into their shortest round-trip text
(`repr`) before hashing. The digest is then stable across runs and machines that compute the same float.
"""

from __future__ import annotations

from uuid import uuid4

from gigai_core.canonical import canonical_json_digest
from pydantic import BaseModel


def floats_as_text(value: object) -> object:
    """A JSON value with every float replaced by repr(float); dicts and lists are walked."""
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {key: floats_as_text(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [floats_as_text(item) for item in value]
    return value


def digest(value: object) -> str:
    """`sha256:<hex>` of a JSON-able value (a pydantic record is dumped in JSON mode first)."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return canonical_json_digest(floats_as_text(value))  # type: ignore[arg-type]


def new_id(prefix: str) -> str:
    """`<prefix>_<16 hex of a uuid4>`, the id style of gigai-core's runs and traces."""
    return f"{prefix}_{uuid4().hex[:16]}"

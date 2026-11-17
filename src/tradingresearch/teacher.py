"""Teacher models: open weights on OpenRouter, each pinned to one DeepInfra endpoint (SPIKE §9.4, P12).

The slugs are the endpoint `tag`s from `GET /api/v1/models/<id>/endpoints` (read 2026-11-16): FP8 or BF16 only, never
FP4, the flex tier where DeepInfra sells one, no fallback to another host. DeepInfra's terms leave the output with the
customer, so a teacher record is `terms_class="trainable"` (TRAINING-SPIKE §8)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from .openrouter import Routing

QUANTIZATIONS = ("fp8", "bf16")
BAKEOFF_NAMES = 4  # names per bake-off session, drawn from that session's shortlist of 10 (SPIKE §9.4)


@dataclass(frozen=True)
class Teacher:
    """One teacher model and the single endpoint allowed to serve it."""

    model: str
    slug: str  # provider/variant[/tier], e.g. deepinfra/fp8/flex
    terms_class: str = "trainable"

    @property
    def routing(self) -> Routing:
        return Routing(only=(self.slug,), allow_fallbacks=False, quantizations=QUANTIZATIONS)

    @property
    def route(self) -> str:
        return f"openrouter:{self.slug}"


TEACHERS = {t.model: t for t in (
    Teacher("deepseek/deepseek-v4-pro", "deepinfra/fp8/flex"),
    Teacher("qwen/qwen3.5-397b-a17b", "deepinfra/fp8/flex"),
    Teacher("openai/gpt-oss-120b", "deepinfra/bf16"),  # DeepInfra lists no flex endpoint for it
)}


def get(model: str) -> Teacher:
    """The pinned teacher for `model`, or a refusal naming the ones there are."""
    if model not in TEACHERS:
        raise SystemExit(f"{model} is not a teacher; choose one of {', '.join(TEACHERS)}")
    return TEACHERS[model]


def from_args(arm: str, teacher: str | None, model: str, default_model: str) -> Teacher | None:
    """The teacher for `--arm teacher --teacher <model>`, None for the other arms; refused before any spend."""
    if arm != "teacher":
        if teacher:
            raise SystemExit("--teacher needs --arm teacher")
        return None
    if not teacher:
        raise SystemExit(f"--arm teacher needs --teacher <model>: one of {', '.join(TEACHERS)}")
    if model != default_model:
        raise SystemExit("--model is for the other arms; the teacher arm takes its model from --teacher")
    return get(teacher)


def draw(session: date, shortlist: list[str], k: int = BAKEOFF_NAMES) -> list[str]:
    """The bake-off names for one session: the same session and shortlist always give the same names, so the screen
    rank does not pick them. Each name is ranked by sha256 of (sha256 of the ISO date) + name; `random.sample` is not
    used because CPython keeps only `random()` stable across versions."""
    seed = hashlib.sha256(session.isoformat().encode()).hexdigest()
    names = sorted(set(shortlist))
    ranked = sorted(names, key=lambda name: hashlib.sha256(f"{seed}{name}".encode()).hexdigest())
    return sorted(ranked[:k])

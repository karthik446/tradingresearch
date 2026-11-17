"""Teacher models: open weights on OpenRouter, each pinned to one DeepInfra endpoint (SPIKE §9.4, P12).

The slugs are the endpoint `tag`s from `GET /api/v1/models/<id>/endpoints` (read 2026-11-16): FP8 or BF16 only, never
FP4, the flex tier where DeepInfra sells one, no fallback to another host. DeepInfra's terms leave the output with the
customer, so a teacher record is `terms_class="trainable"` (TRAINING-SPIKE §8)."""

from __future__ import annotations

from dataclasses import dataclass

from .openrouter import Routing

QUANTIZATIONS = ("fp8", "bf16")


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

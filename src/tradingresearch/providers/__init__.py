"""One provider interface (ADR-014). `TR_PROVIDER` (`openrouter`, the default, or `anthropic`) picks the adapter for
every model call except the teachers': the champion and challenger (`analyze`, `thesis`, `daily`), experiment arms
and the judge. Teachers are not Claude and always run on OpenRouter. Only the chosen provider's key is read.

Both adapters are gigai-core `ModelProvider`s with the same `route_for`, `routes` and `served`, and both map their
failures into `errors.py`. A provider change for a role is a new route, never the same route: the trace's identity
and every record's `provider_route` name the provider."""

from __future__ import annotations

from gigai_core.budget import Price

from ..config import Settings, require
from . import anthropic, openrouter
from .anthropic import Anthropic
from .openrouter import OpenRouter, Routing

ROLES = ("champion", "experiment", "judge", "teacher")
KEYS = {"openrouter": "OPENROUTER_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def name_for(cfg: Settings, role: str) -> str:
    """The provider a role's calls go to: the teacher always OpenRouter, every other role `TR_PROVIDER`."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r} (one of {', '.join(ROLES)})")
    return "openrouter" if role == "teacher" else cfg.provider


def make_provider(cfg: Settings, role: str, *, routing: Routing | None = None) -> OpenRouter | Anthropic:
    """The role's adapter, built with its provider's key only; a missing key exits with one line naming it. `routing`
    (a teacher's host pin) is OpenRouter's alone."""
    name = name_for(cfg, role)
    if name == "anthropic":
        if routing is not None:
            raise SystemExit("an OpenRouter routing table cannot run on TR_PROVIDER=anthropic")
        return Anthropic(require(cfg.anthropic_key, KEYS[name]))
    return OpenRouter(require(cfg.openrouter_key, KEYS[name]), routing=routing)


def check_models(cfg: Settings, role: str, models: list[str]) -> None:
    """Refuse, before any call or spend, a model the role's provider cannot serve (another vendor on Anthropic)."""
    if name_for(cfg, role) == "anthropic":
        for model in models:
            try:
                anthropic.wire_model(model)
            except anthropic.WrongProvider as error:
                raise SystemExit(str(error)) from error


def prices(cfg: Settings, role: str, models: list[str]) -> dict[str, Price]:
    """The role's provider's per-token prices (neither reads a key): OpenRouter's public list, Anthropic's table."""
    check_models(cfg, role, models)
    source = anthropic.prices if name_for(cfg, role) == "anthropic" else openrouter.prices
    return source(models)

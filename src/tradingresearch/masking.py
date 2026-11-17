"""The `drop` arm knob (REPO-PLAN §2.5, week 5): an arm sees the analyze prompt with named SOURCES sections removed.

The sections are the three groups the week-4 tools already serve (get_indicators, get_levels, get_fundamentals).
The dataset item keeps the full prompt, so every arm shares one dataset digest; `Masked` removes the dropped rows
from the request on its way to the model, and experiment.run_masked traces that masked request.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping

from gigai_core.providers import ModelRequest, ModelResult

from .tools import LEVEL_PREFIXES, METRICS

SECTIONS = ("indicators", "levels", "edgar")
ROW = re.compile(r"src_\w+ \| ([^|]+) \| ")  # one SOURCES line of analyze.render: source_id | name | value | unit


def section_of(name: str) -> str:
    """The section of a SOURCES row: EDGAR facts are `<metric>_<frame>`, levels carry the tools' level prefixes."""
    if name.rsplit("_", 1)[0] in METRICS:
        return "edgar"
    return "levels" if name.startswith(LEVEL_PREFIXES) else "indicators"


def mask(prompt: str, drop: Iterable[str]) -> str:
    """`prompt` without the SOURCES lines of the dropped sections; an empty `drop` returns it unchanged."""
    dropped = set(drop)
    if not dropped:
        return prompt
    return "\n".join(line for line in prompt.split("\n") if not shown_in(line, dropped))


def shown_in(line: str, sections: set[str]) -> bool:
    """Whether `line` is a SOURCES row of one of `sections`."""
    row = ROW.match(line)
    return row is not None and section_of(row.group(1)) in sections


def hidden(names: Mapping[str, str], drop: Iterable[str]) -> frozenset[str]:
    """The source ids (of a `source_id -> name` map) whose rows a `drop` arm never sees."""
    dropped = set(drop)
    return frozenset(source_id for source_id, name in names.items() if section_of(name) in dropped)


class Masked:
    """A provider that sends every request with the arm's dropped sections removed from its user turns."""

    def __init__(self, inner, drop: tuple[str, ...]) -> None:
        self.inner = inner
        self.drop = drop

    @property
    def identity(self):
        return self.inner.identity

    @property
    def capabilities(self):
        return self.inner.capabilities

    def request(self, request: ModelRequest) -> ModelRequest:
        """What the model is sent for `request`; masking twice is a no-op, so the result can be sent as is."""
        turns = tuple(t.model_copy(update={"content": mask(t.content, self.drop)}) if t.role == "user" else t
                      for t in request.turns)
        return request.model_copy(update={"turns": turns})

    def invoke(self, request: ModelRequest, *, cancel: threading.Event | None = None) -> ModelResult:
        return self.inner.invoke(self.request(request), cancel=cancel)

    def route_for(self, prompt: str) -> str:
        """The route of the call made for the full `prompt`: the inner provider keys it by the masked text it sent."""
        return self.inner.route_for(mask(prompt, self.drop))

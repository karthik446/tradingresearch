"""w4l4.1 one known provider: records.clean_route is True only when a route names one known provider behind the
openrouter client (the host, the part before any /tier, is neither empty, unknown in any case, nor mixed(...)), and a
trainable Analysis or Thesis is refused when it is built with a route that is not clean. A restricted record keeps any
route: only the training set needs to know who served every turn.

Records are built with the repo's own factories (tests/factories.py), changing only the arm, terms_class and route.
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests"))
from factories import analysis, thesis  # noqa: E402

from tradingresearch.records import clean_route  # noqa: E402

CLEAN = {
    "openrouter:Anthropic": "one provider, as the replies report it",
    "openrouter:azure": "one provider, lower case",
    "openrouter:google-vertex": "one provider whose name has a dash",
    "openrouter:deepinfra/fp8": "one provider and its quantization: the host is the part before the /",
    "openrouter:azure/flex": "one provider at a service tier, as a pinned arm logs it",
}
DIRTY = {
    "openrouter:unknown": "the reply did not say who served it",
    "openrouter:Unknown": "unknown in another case is still unknown",
    "openrouter:mixed(Azure+Google)": "two providers served one exchange",
    "openrouter:unknown/flex": "an unknown host at a tier is still an unknown host",
    "openrouter:UNKNOWN/flex": "an unknown host at a tier, upper case",
    "openrouter:": "an empty host names nobody",
    "openrouter": "the client alone names nobody",
    "unknown": "no client and no host",
    "": "an empty route",
}
BUILD = {
    "a main-arm Analysis": lambda **kw: analysis(arm="main", **kw),
    "a teacher Analysis": lambda **kw: analysis(arm="teacher", **kw),
    "a champion Thesis": lambda **kw: thesis("an_1", arm="champion", **kw),
    "a teacher Thesis": lambda **kw: thesis("an_1", arm="teacher", **kw),
}


@pytest.mark.parametrize("route", [*DIRTY, *CLEAN])
def test_clean_route_is_true_only_for_one_known_provider(route):
    expected = route in CLEAN
    why = CLEAN.get(route) or DIRTY[route]
    got = clean_route(route)
    assert bool(got) is expected, (
        f"clean_route({route!r}) returned {got!r}; expected {expected}: {why}")


def build(kind: str, **fields):
    """(record, None) when the record is built, else (None, the validator's own words), without pydantic's dump of
    the input, which always contains the route."""
    try:
        return BUILD[kind](**fields), None
    except ValidationError as exc:
        return None, "; ".join(error["msg"] for error in exc.errors())


@pytest.mark.parametrize("kind", BUILD)
@pytest.mark.parametrize("route", ["openrouter:unknown", "openrouter:mixed(Azure+Google)", "openrouter:Unknown",
                                   "openrouter:"])
def test_a_trainable_record_with_a_route_that_is_not_clean_is_refused(kind, route):
    record, text = build(kind, terms_class="trainable", provider_route=route)
    assert record is None, (
        f"{kind}, terms_class 'trainable', route {route!r} was built (route {record.provider_route!r}); expected a "
        f"ValidationError: a trainable record must name the one provider that served it")
    assert route in text, (
        f"{kind} with route {route!r} was refused with {text!r}; expected the message to name the refused route, so "
        f"the reader knows which record lost provenance")
    assert "one known provider" in text, (
        f"{kind} with route {route!r} was refused with {text!r}; expected the words 'one known provider', which "
        f"tests/test_route.py (the chapter's Done-when) matches")


@pytest.mark.parametrize("kind", BUILD)
def test_a_trainable_record_with_one_known_provider_is_built(kind):
    for route in ("openrouter:Azure", "openrouter:deepinfra/fp8"):
        record, text = build(kind, terms_class="trainable", provider_route=route)
        assert text is None, (
            f"{kind}, terms_class 'trainable', route {route!r} raised {text!r}; expected it built: one known "
            f"provider is clean")
        assert record.provider_route == route


@pytest.mark.parametrize("terms", ["restricted", "unknown"])
@pytest.mark.parametrize("kind", ["a main-arm Analysis", "a champion Thesis"])
@pytest.mark.parametrize("route", ["openrouter:unknown", "openrouter:mixed(Azure+Google)", "openrouter", ""])
def test_a_record_that_is_not_trainable_keeps_any_route(kind, route, terms):
    record, text = build(kind, terms_class=terms, provider_route=route)
    assert text is None, (
        f"{kind}, terms_class {terms!r}, route {route!r} raised {text!r}; expected it built: only a trainable record "
        f"needs one known provider, and a record whose terms are {terms} is not training data")
    assert record.provider_route == route

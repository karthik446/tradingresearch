"""w4l4.2 the route of the exchange: the adapter logs each served route under the exchange's first user turn (the item
prompt), so every turn of one tool loop counts; route_for gives the one route, openrouter:mixed(a+b) with each provider
once in sorted order, or openrouter:unknown when nothing was served or any turn's provider is null, missing or not
clean. A request with no assistant or tool turn starts a new exchange for its key, a retried turn stays in its exchange,
and a pinned copy (routed) keeps its own log.

The real adapter replays the recorded exchange at the HTTP transport (tools/fakea.py `replaying`): turn1 (served by
Azure) asks for a tool, turn2 (served by Google) answers. Other providers, null and missing ones are edits of those
replies. Two items, FAKEA and FAKEB (fakea.other), have different item prompts. The replay answers HTTP 400 from
request 13 on.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import analyze as an  # noqa: E402
from tradingresearch import experiment as ex  # noqa: E402
from tradingresearch import journal  # noqa: E402
from tradingresearch.openrouter import Routing  # noqa: E402

SESSION = date(2026, 11, 13)  # fakea.experiment's session
UNKNOWN = "openrouter:unknown"
GONE = object()  # the reply carries no provider field at all


def hosts(*names):
    """`edit` for fakea.replaying: request i is answered as served by names[i % len(names)] (None: a null provider,
    GONE: no provider field)."""
    def edit(n: int, body: dict) -> dict:
        name = names[n % len(names)]
        if name is GONE:
            body.pop("provider", None)
        else:
            body["provider"] = name
        return body
    return edit


def item_prompt(body: dict) -> str:
    """The first user turn of a request body: the item prompt every request of its loop carries."""
    return next(m["content"] for m in body["messages"] if m["role"] == "user")


def loop(provider, ctx=None):
    """One item's tool loop; a failed exchange is a result here, not an error."""
    try:
        return fakea.run(provider, ctx=ctx)
    except Exception as exc:  # noqa: BLE001 - a failed call may surface as an exception
        return exc


def log(provider) -> str:
    return f"routes logged {provider.routes!r}, served {[route for _, route in provider.served]!r}"


def test_a_tool_loop_served_by_two_providers_is_mixed_under_its_item_prompt():
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("turn1", "turn2"), cycle=True, edit=hosts("Azure", "Google", "Azure", "Azure"))
    loop(provider)
    loop(provider, fakea.other())
    a, b = item_prompt(sent[0]), item_prompt(sent[2])
    got = (provider.route_for(a), provider.route_for(b))
    assert got == ("openrouter:mixed(Azure+Google)", "openrouter:Azure"), (
        f"route_for(FAKEA prompt), route_for(FAKEB prompt) = {got}; expected ('openrouter:mixed(Azure+Google)', "
        f"'openrouter:Azure'): FAKEA's loop was served by Azure then Google, FAKEB's by Azure twice, and every "
        f"request of one loop shares its item prompt while two items do not ({log(provider)})")
    keys = [key for key, _ in provider.served]
    assert keys == [a, a, b, b], (
        f"served was logged under {len(set(keys))} distinct keys in the order {[k[:40] for k in keys]}; expected each "
        f"call under its item prompt (FAKEA, FAKEA, FAKEB, FAKEB)")


@pytest.mark.parametrize("host", ["Google", "Azure"])
def test_one_provider_on_every_turn_is_that_provider(host):
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("turn1", "turn2"), edit=hosts(host))
    loop(provider)
    got = provider.route_for(item_prompt(sent[0]))
    assert got == f"openrouter:{host}", (
        f"route_for(item prompt) = {got!r}; expected 'openrouter:{host}': both turns were served by {host} "
        f"({log(provider)})")


@pytest.mark.parametrize(("replies", "names"), [
    (("turn1", "turn2"), ("Google", "Azure")),
    (("turn1", "one_more", "turn2"), ("Google", "Azure", "Google")),
    (("turn1", "one_more", "turn2"), ("Azure", "Google", "Azure")),
    (("one_more", "one_more", "one_more", "turn2"), ("Azure", "Azure", "Azure", "Google")),
])
def test_mixed_names_each_provider_once_in_sorted_order(replies, names):
    sent: list[dict] = []
    provider = fakea.replaying(sent, replies, edit=hosts(*names))
    loop(provider)
    got = provider.route_for(item_prompt(sent[0]))
    assert got == "openrouter:mixed(Azure+Google)", (
        f"route_for(item prompt) = {got!r} after turns served by {' then '.join(names)}; expected "
        f"'openrouter:mixed(Azure+Google)': every turn of the exchange counts, the last one too, and each provider "
        f"is named once, sorted, so one mix always reads the same ({log(provider)})")


def test_a_retried_turn_keeps_the_routes_logged_before_it():
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("one_more", "busy", "turn2"), edit=hosts("Azure", "Google", "Google"))
    loop(provider)
    got = provider.route_for(item_prompt(sent[0]))
    assert got == "openrouter:mixed(Azure+Google)", (
        f"route_for(item prompt) = {got!r} after Azure served the first turn and Google answered the second on a "
        f"retry after an HTTP 503; expected 'openrouter:mixed(Azure+Google)': a retry is the same turn of the same "
        f"exchange, so the routes logged before it stay ({log(provider)})")


@pytest.mark.parametrize(("names", "what"), [
    ((None, "Google"), "turn1's provider is null"),
    (("Azure", None), "turn2's provider is null"),
    ((GONE, "Google"), "turn1 has no provider field"),
    (("Azure", GONE), "turn2 has no provider field"),
    ((None, None), "both providers are null"),
    (("Azure", "Unknown"), "turn2 reports Unknown"),
])
def test_a_turn_with_no_known_provider_makes_the_exchange_unknown(names, what):
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("turn1", "turn2"), edit=hosts(*names))
    loop(provider)
    got = provider.route_for(item_prompt(sent[0]))
    assert got == UNKNOWN, (
        f"route_for(item prompt) = {got!r} when {what}; expected {UNKNOWN!r}: one turn nobody can name is enough to "
        f"lose the exchange's provenance ({log(provider)})")


def test_nothing_served_is_unknown():
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("turn1", "turn2"))
    got = provider.route_for("a prompt never sent")
    assert got == UNKNOWN, f"route_for on a fresh client = {got!r}; expected {UNKNOWN!r}: nothing was served"
    loop(provider)
    other = item_prompt(sent[0]) + " (another item)"
    got = provider.route_for(other)
    assert got == UNKNOWN, (
        f"route_for(a prompt this client never sent) = {got!r}; expected {UNKNOWN!r} ({log(provider)})")


def test_a_new_exchange_for_an_item_replaces_its_last_one_and_leaves_other_items_alone():
    sent: list[dict] = []
    names = ("Azure", "Google", "Azure", "Azure", "Google", "Google")
    provider = fakea.replaying(sent, ("turn1", "turn2"), cycle=True, edit=hosts(*names))
    loop(provider)
    loop(provider, fakea.other())
    loop(provider)
    a, b = item_prompt(sent[0]), item_prompt(sent[2])
    got = (provider.route_for(a), provider.route_for(b))
    assert got == ("openrouter:Google", "openrouter:Azure"), (
        f"after FAKEA (Azure, Google), FAKEB (Azure, Azure), FAKEA again (Google, Google): route_for = {got}; expected "
        f"('openrouter:Google', 'openrouter:Azure'): FAKEA's route is its latest exchange, FAKEB's is untouched "
        f"({log(provider)})")
    assert len(provider.served) == 6, (
        f"served holds {len(provider.served)} calls; expected 6: the per-call log keeps every call of every exchange")


def test_a_new_exchange_that_fails_leaves_the_item_unknown():
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("turn1", "turn2", "failed"), edit=hosts("Azure"))
    loop(provider)
    prompt = item_prompt(sent[0])
    first = provider.route_for(prompt)
    loop(provider)
    got = provider.route_for(prompt)
    assert (first, got) == ("openrouter:Azure", UNKNOWN), (
        f"route_for(item prompt) = {first!r} after a loop served by Azure, then {got!r} after a new exchange whose "
        f"first request failed; expected ('openrouter:Azure', {UNKNOWN!r}): the failed exchange served nothing, so "
        f"the earlier exchange's route must not stand for it ({log(provider)})")


def pinned_hosts(sent):
    """`edit` for fakea.replaying: each request is served by the first host its arm is pinned to (Azure unpinned)."""
    def edit(n: int, body: dict) -> dict:
        only = (sent[n].get("provider") or {}).get("only") or ["Azure"]
        body["provider"] = only[0].split("/")[0].capitalize()
        return body
    return edit


def test_each_pinned_arm_keeps_its_own_routes():
    sent: list[dict] = []
    base = fakea.replaying(sent, ("turn1", "turn2"), cycle=True, edit=pinned_hosts(sent))
    loop(base, fakea.other())  # the original ran FAKEB before the arms were pinned
    azure, google = base.routed(Routing(only=("azure",))), base.routed(Routing(only=("google",)))
    loop(azure)
    loop(google)
    early, prompt = item_prompt(sent[0]), item_prompt(sent[2])
    got = (azure.route_for(prompt), google.route_for(prompt), base.route_for(prompt))
    assert got == ("openrouter:azure", "openrouter:google", UNKNOWN), (
        f"after FAKEA ran on an arm pinned to azure, then one pinned to google: route_for(FAKEA prompt) on azure, "
        f"google, the unpinned client = {got}; expected ('openrouter:azure', 'openrouter:google', {UNKNOWN!r}): each "
        f"arm sees only the exchanges it ran")
    got = (azure.route_for(early), google.route_for(early), base.route_for(early))
    assert got == (UNKNOWN, UNKNOWN, "openrouter:Azure"), (
        f"route_for(FAKEB prompt) on azure, google, the unpinned client = {got}; expected ({UNKNOWN!r}, {UNKNOWN!r}, "
        f"'openrouter:Azure'): only the original ran FAKEB, before the arms were pinned, so the arms start empty")
    served = ([r for _, r in azure.served], [r for _, r in google.served], [r for _, r in base.served])
    assert served == (["openrouter:azure"] * 2, ["openrouter:google"] * 2, ["openrouter:Azure"] * 2), (
        f"served on azure, google, the unpinned client = {served}; expected two calls each, every one on the client "
        f"that made it")
    loop(base)
    got = (azure.route_for(prompt), base.route_for(prompt))
    assert got == ("openrouter:azure", "openrouter:Azure"), (
        f"after the unpinned client ran FAKEA too: route_for on azure, unpinned = {got}; expected "
        f"('openrouter:azure', 'openrouter:Azure'): the copy and the original never share a log")


def test_the_stored_analysis_carries_the_route_of_the_whole_exchange(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: 1600)  # the tokenizer is not on disk
    sent: list[dict] = []
    provider = fakea.replaying(sent, ("turn1", "turn2"), cycle=True, edit=hosts("Azure", "Google", "Google", "Google"))
    config = fakea.experiment(tmp_path / "arms.toml", modes=("tools",))
    conn = journal.connect(tmp_path / "journal.db")
    ex.run_arms(conn, config, [fakea.context(), fakea.other()], provider, fakea.prices(), tmp_path)
    routes = {a.ticker: a.provider_route for a in journal.analyses(conn, SESSION, "main")}
    assert routes == {"FAKEA": "openrouter:mixed(Azure+Google)", "FAKEB": "openrouter:Google"}, (
        f"stored provider_route per ticker = {routes}; expected FAKEA 'openrouter:mixed(Azure+Google)' and FAKEB "
        f"'openrouter:Google': the analysis stores the route of every turn of its own loop")

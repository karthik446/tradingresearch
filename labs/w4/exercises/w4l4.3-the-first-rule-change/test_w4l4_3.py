"""w4l4.3 the first rule change: a short-horizon thesis that trades against the 50-session trend (long while
dist_sma_50_atr < 0, short while it is > 0, however small the distance) is refused, a missing dist_sma_50_atr is
refused, and everything else is kept; the filter is a reviewed CHALLENGER_RULES entry, short-sma50-trend, on the
champion prompt; and experiments/rule-change-1.toml pre-registers it by the chapter's Prereg (week 4 section 6) on the
short horizon, registered after the 2026-11-16 open and before the first session it covers, 2026-11-17, and before
any challenger thesis.

Theses and analyses come from the repo's tests/factories.py; the filter is reached through the registry, as the
challenger arm reaches it. Registration runs in a journal under the test's temp directory.
"""

import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from factories import analysis, snapshot, thesis  # noqa: E402

from tradingresearch import journal, rules, sessions  # noqa: E402
from tradingresearch import thesis as th  # noqa: E402
from tradingresearch.records import RuleChange  # noqa: E402

KEY = "short-sma50-trend"
TOML = ROOT / "experiments" / "rule-change-1.toml"
SHORT_PRICES = {"stop": 238.0, "target": 220.0, "invalidation_price": 238.0}  # a valid short around close 230


def entry():
    rule = rules.CHALLENGER_RULES.get(KEY)
    assert rule is not None, (
        f"CHALLENGER_RULES has the keys {sorted(rules.CHALLENGER_RULES)}; expected a {KEY!r} entry: the challenger "
        f"reaches the filter only through the reviewed registry")
    assert isinstance(rule, rules.Filter), (
        f"CHALLENGER_RULES[{KEY!r}] is a {type(rule).__name__}; expected a Filter: rule-change-1 drops written theses, "
        f"it does not change the prompt")
    return rule


def case(horizon: str, direction: str, dist: float | None):
    values = {"close": 230.0, "atr_14": 4.0} | ({} if dist is None else {"dist_sma_50_atr": dist})
    a = analysis(snapshot=snapshot(values=values))
    prices = ({} if direction == "long" else SHORT_PRICES) | ({"hold_sessions": 0} if horizon == "day" else {})
    t = thesis(a.analysis_id, horizon=horizon, direction=direction, **prices)
    return t, a


def refused(horizon: str, direction: str, dist: float | None):
    t, a = case(horizon, direction, dist)
    return entry().refuse(t, a)


@pytest.mark.parametrize("dist", [-0.4, -2.5])
def test_a_short_horizon_long_below_the_sma50_is_refused_and_one_above_it_is_kept(dist):
    below, above = refused("short", "long", dist), refused("short", "long", -dist)
    assert isinstance(below, str) and below.strip(), (
        f"refuse(short-horizon long, dist_sma_50_atr {dist}) returned {below!r}; expected a reason (a non-empty str): "
        f"a long below the sma_50 trades against the trend")
    assert above is None, (
        f"refuse(short-horizon long, dist_sma_50_atr {-dist}) returned {above!r}; expected None: a long above the "
        f"sma_50 trades with the trend, and only None keeps a thesis")


@pytest.mark.parametrize("dist", [0.4, 2.5])
def test_a_short_horizon_short_above_the_sma50_is_refused_and_one_below_it_is_kept(dist):
    above, below = refused("short", "short", dist), refused("short", "short", -dist)
    assert isinstance(above, str) and above.strip(), (
        f"refuse(short-horizon short, dist_sma_50_atr {dist}) returned {above!r}; expected a reason (a non-empty str): "
        f"a short above the sma_50 trades against the trend")
    assert below is None, (
        f"refuse(short-horizon short, dist_sma_50_atr {-dist}) returned {below!r}; expected None: a short below the "
        f"sma_50 trades with the trend")


def test_a_hundredth_or_a_ten_thousandth_from_the_sma50_is_already_against_the_trend():
    for direction, side in (("long", -1), ("short", 1)):
        for size in (0.01, 0.001, 0.0004):
            dist = side * size
            got = refused("short", direction, dist)
            assert isinstance(got, str) and got.strip(), (
                f"refuse(short-horizon {direction}, dist_sma_50_atr {dist}) returned {got!r}; expected a reason: the "
                f"sign of the distance is the side of the trend however small it is, and only exactly 0.0 sits on the "
                f"sma_50")


@pytest.mark.parametrize("direction", ["long", "short"])
def test_a_close_exactly_on_the_sma50_is_kept(direction):
    got = refused("short", direction, 0.0)
    assert got is None, (
        f"refuse(short-horizon {direction}, dist_sma_50_atr 0.0) returned {got!r}; expected None: on the sma_50 the "
        f"thesis is not against the trend, so the rule has no reason to drop it")


@pytest.mark.parametrize("direction", ["long", "short"])
def test_a_short_horizon_thesis_with_no_dist_value_is_refused(direction):
    got = refused("short", direction, None)
    assert isinstance(got, str) and got.strip(), (
        f"refuse(short-horizon {direction}, no dist_sma_50_atr) returned {got!r}; expected a reason: without the value "
        f"nobody can tell the thesis is with the trend")


@pytest.mark.parametrize("horizon", ["day", "swing"])
@pytest.mark.parametrize(("direction", "dist"), [("long", -2.5), ("short", 2.5), ("long", None), ("short", None)])
def test_other_horizons_are_never_refused(horizon, direction, dist):
    got = refused(horizon, direction, dist)
    assert got is None, (
        f"refuse({horizon}-horizon {direction}, dist_sma_50_atr {dist}) returned {got!r}; expected None: the change "
        f"is pre-registered on the short horizon only")


def test_the_challenger_store_keeps_the_trend_and_rejects_the_rest():
    against, _ = case("short", "long", -0.4)
    kept, a = case("short", "short", -0.4)
    swing, _ = case("swing", "long", -0.4)
    against, kept, swing = (t.model_copy(update={"analysis_id": a.analysis_id}) for t in (against, kept, swing))
    apply = rules.post(entry(), a)
    out = apply(th.Checked([against, kept, swing], [], []))
    got = ([(t.horizon, t.direction) for t in out.theses], [(r.horizon, r.reason) for r in out.rejected])
    assert got == ([("short", "short"), ("swing", "long")], [("short", "rule_filter")]), (
        f"on one analysis at dist_sma_50_atr -0.4 the challenger kept {got[0]} and rejected {got[1]}; expected the "
        f"short-horizon short and the swing long kept and the short-horizon long rejected as rule_filter")


def test_the_entry_is_a_reviewed_filter_on_the_champion_prompt():
    rule = entry()
    words = rule.description.lower().split()
    assert len(words) >= 3 and not {"tbd", "todo", "fixme", "placeholder"} & set(words) and not (
            rule.description.lower().startswith("example")), (
        f"the {KEY!r} description is {rule.description!r}; expected the change's own words, not a placeholder and "
        f"not an example's: the description is what a reviewer reads before the challenger runs")
    assert rules.prompt_of(rule) == th.DEFAULT_PROMPT, (
        f"prompt_of({KEY!r}) = {rules.prompt_of(rule)!r}; expected {th.DEFAULT_PROMPT!r}: a filter keeps the champion "
        f"prompt, so the arms differ only by the rule")
    examples = sorted(k for k in rules.CHALLENGER_RULES if k.startswith("example-"))
    assert examples == ["example-breakout-volume", "example-same-prompt"], (
        f"the registry's example entries are {examples}; expected both examples kept beside the real entry")


def change() -> RuleChange:
    try:
        return RuleChange.model_validate(tomllib.loads(TOML.read_text()))
    except Exception as exc:  # noqa: BLE001 - reported below
        error = f"{type(exc).__name__}: {exc}".splitlines()
    raise AssertionError(f"experiments/rule-change-1.toml does not load as a RuleChange ({' / '.join(error[:4])}); "
                         f"expected the top-level fields and a [prereg] table with an aware registered_at")


def test_the_change_names_the_entry_and_waits_for_its_decision():
    c = change()
    assert c.diff_ref == KEY, (
        f"diff_ref is {c.diff_ref!r}; expected {KEY!r}: the challenger answers under the registry entry it names")
    assert rules.resolve(c.diff_ref) is entry()
    assert (c.change_id, c.decided) == ("rc_1", "pending"), (
        f"change_id, decided = {(c.change_id, c.decided)}; expected ('rc_1', 'pending'): the first change, undecided "
        f"until its sessions are in")
    assert c.description.strip() and not c.description.lower().startswith("example"), (
        f"description is {c.description!r}; expected what the change does")


def test_the_prereg_is_the_chapters_unit_on_the_short_horizon():
    p = change().prereg
    assert p.primary_metric == "session_r_net_delta:short", (
        f"primary_metric is {p.primary_metric!r}; expected 'session_r_net_delta:short': the rule acts on the short "
        f"horizon, so that horizon's per-session net R is what it is judged on")
    want = journal.rule_prereg("short", p.hypothesis, p.registered_at)
    got = {k: getattr(p, k) for k in ("pass_rule", "guard_metric", "margin", "n_planned")}
    expected = {k: getattr(want, k) for k in got}
    assert got == expected, (
        f"the prereg's pass_rule, guard_metric, margin, n_planned are {got}; expected {expected}: the chapter fixes "
        f"them before any session (week 4 section 6), so nobody tunes them after seeing results")
    assert p.hypothesis.strip(), "the prereg's hypothesis is empty; expected the claim the sessions will test"


class Clock(datetime):
    """journal's clock pinned to after the 2026-11-17 close: a challenger thesis stored then is the first one."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 17, 21, 30, tzinfo=UTC)


def test_it_registers_after_the_last_open_and_before_the_first_session_it_covers(tmp_path, monkeypatch):
    c = change()
    opens_16, opens_17 = sessions.open_close(date(2026, 11, 16))[0], sessions.open_close(date(2026, 11, 17))[0]
    when = c.prereg.registered_at
    assert opens_16 <= when < opens_17, (
        f"registered_at is {when.isoformat()}; expected from {opens_16.isoformat()} (the 2026-11-16 open) to before "
        f"{opens_17.isoformat()} (the 2026-11-17 open): the first session the change covers is 2026-11-17, and "
        f"pre-registration comes before it opens")
    conn = journal.connect(tmp_path / "journal.db")
    monkeypatch.setattr(journal, "datetime", Clock)
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    journal.add(conn, thesis(a.analysis_id, arm="challenger"))
    monkeypatch.undo()
    try:
        rules.register(conn, c)
        error = None
    except ValueError as exc:
        error = str(exc)
    assert error is None, (
        f"rules.register refused the change: {error}; expected it stored: a journal whose first challenger thesis was "
        f"stored on 2026-11-17 21:30 UTC accepts a change registered before it")
    got = (rules.pending_for(conn, date(2026, 11, 16)), rules.pending_for(conn, date(2026, 11, 17)))
    assert got == (None, c), (
        f"pending_for(2026-11-16), pending_for(2026-11-17) = {tuple(x and x.change_id for x in got)}; expected "
        f"(None, 'rc_1'): the challenger answers from the first session after registration")

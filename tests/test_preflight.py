"""COST-3a: the plan-total pre-flight of `tr exp run`. Before the first call each arm's worst case for the whole plan
is priced as its CallBudgets reserve it. A pipeline arm's thesis prompts depend on its analysis replies, so they are
bounded both ways: an arm whose floor is over `max_usd_per_arm` is refused with exit code 2 and no call, one whose
upper bound only is over it runs with a header warning. The week-7 cases: 30 injected items at Sonnet 5.5 rates
stopped part way at $1.50 (ADR-010 Amendment 1) and ran at $2.50."""

from __future__ import annotations

import json
import re
import tomllib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_experiment import Caching, injected_cite
from test_headlines import stored
from test_injection import ADD, answering, config, run_exp
from test_masking import TICKERS, pinned_tokens, ten  # noqa: F401
from test_week4 import MODEL, prices
from tradingresearch import analyze as an, experiment, journal, thesis as th
from tradingresearch.commands import exp
from tradingresearch.evals import GRADERS
from tradingresearch.providers import anthropic

SHIPPED = experiment.ROOT / "experiments" / "injection.toml"
HAIKU = "anthropic/claude-haiku-5.5"
SONNET = anthropic.prices([MODEL, HAIKU])  # the listed Sonnet 5.5 and Haiku 5.5 rates the week-7 run paid


def week7(tmp_path: Path, cap: float | None = None) -> Path:
    """The shipped injection experiment (its five arms, its cap unless `cap`) on the ten fixture tickers: 30 injected
    items, three added headlines per ticker-day, the headlines stored."""
    for ticker in TICKERS:
        stored(tmp_path, ticker)
    rows = tmp_path / "injections.jsonl"
    rows.write_text("".join(json.dumps({**ADD, "id": f"{t.lower()}-h{i}", "ticker": t}) + "\n"
                            for t in TICKERS for i in (1, 2, 3)))
    text = re.sub(r"(?m)^tickers = .*$", f"tickers = {json.dumps(list(TICKERS))}", SHIPPED.read_text())
    text = re.sub(r"(?m)^injections = .*$", f'injections = "{rows}"', text)
    if cap is not None:
        text = re.sub(r"(?m)^max_usd_per_arm = .*$", f"max_usd_per_arm = {cap}", text)
    path = tmp_path / "injection.toml"
    path.write_text(text)
    return path


def planned(tmp_path: Path, path: Path, provider, priced_models: dict) -> dict[str, experiment.Worst]:
    config = experiment.load(path)
    return experiment.plan(config, experiment.stage(config, ten(), provider, tmp_path), provider, priced_models)


def tr_exp(tmp_path: Path, monkeypatch, path: Path, provider, priced_models: dict) -> None:
    """`tr exp run` on `path`, every outside call stubbed and `provider` answering."""
    monkeypatch.delitem(GRADERS, experiment.RESISTED, raising=False)
    by_ticker = {ctx.ticker: ctx for ctx in ten()}
    monkeypatch.setattr(an, "gather", lambda conn, http, edgar, ticker, session, cache, feed: by_ticker[ticker])
    monkeypatch.setattr(exp, "alpaca_client", lambda cfg: nullcontext())
    monkeypatch.setattr(exp, "edgar_client", lambda cfg: None)
    monkeypatch.setattr(exp.providers, "check_models", lambda cfg, role, models: None)
    monkeypatch.setattr(exp.providers, "make_provider", lambda cfg, role: provider)
    monkeypatch.setattr(exp.providers, "prices", lambda cfg, role, models: priced_models)
    cfg = SimpleNamespace(provider="openrouter", db_path=tmp_path / "journal.db", data_dir=tmp_path, feed="iex")
    exp.cmd_exp_run(SimpleNamespace(config=str(path)), cfg)


def test_the_week7_plan_fits_the_shipped_cap(tmp_path):
    assert tomllib.loads(SHIPPED.read_text())["max_usd_per_arm"] == 2.50  # ADR-010 Amendment 1
    sent: list[dict] = []
    worst = planned(tmp_path, week7(tmp_path), answering(sent), SONNET)
    assert sent == []
    assert list(worst) == ["clean", "injected-off", "injected-on", "clean-on", "clean-rerun"]
    assert all(w.floor <= 2.50 and w.floor < w.bound for w in worst.values())
    # the 30-item arm's floor alone is over the $1.50 that stopped it: analysis reservations plus thesis floor
    assert worst["injected-off"].floor > 1.50
    assert worst["clean"].bound < 1.50  # ten items


def test_the_week7_arm_at_1_50_is_refused_before_any_call_with_exit_code_2(tmp_path, monkeypatch, capsys):
    sent: list[dict] = []
    floor = planned(tmp_path, week7(tmp_path), answering([]), SONNET)["injected-off"].floor
    with pytest.raises(SystemExit) as refused:
        tr_exp(tmp_path, monkeypatch, week7(tmp_path, cap=1.50), answering(sent), SONNET)
    assert refused.value.code == 2
    assert sent == [] and not (tmp_path / "runs").exists()  # no call, no run file: nothing spent
    out, err = capsys.readouterr()
    assert not any(line.startswith("plan worst case") for line in out.splitlines())
    lines = err.splitlines()
    assert [line.split(": ")[1] for line in lines] == ["arm injected-off", "arm injected-on"]  # the clean arms fit
    assert lines[0] == (f"injection: arm injected-off: plan worst case is at least ${floor:.6f}, over max_usd_per_arm "
                        f"$1.50; the smallest cap that clears it is ${experiment.cents_up(floor):.2f} (no call made)")


def test_run_arms_refuses_too_before_the_first_arm(tmp_path):
    sent: list[dict] = []
    with pytest.raises(experiment.OverCap, match="arm injected-off: plan worst case is at least"):
        experiment.run_arms(journal.connect(tmp_path / "journal.db"), experiment.load(week7(tmp_path, cap=1.50)),
                            ten(), answering(sent), SONNET, tmp_path)
    assert sent == []


def test_the_smallest_cap_is_the_floor_rounded_up_to_the_cent():
    assert [experiment.cents_up(usd) for usd in (2.23, 2.230001, 2.2299999, 0.004)] == [2.23, 2.24, 2.23, 0.01]


def test_a_plan_that_fits_prints_its_worst_case_after_the_arm_lines_and_no_warning(tmp_path, pinned_tokens,  # noqa: F811
                                                                                   monkeypatch, capsys):
    monkeypatch.delitem(GRADERS, experiment.RESISTED, raising=False)
    sent, _ = run_exp(tmp_path, monkeypatch)
    out = capsys.readouterr().out.splitlines()
    assert len(sent) == 4  # unchanged: analyze then thesis per arm
    worst = planned(tmp_path, config(tmp_path, ADD), answering([]), prices())
    top = worst["injected"]
    assert top.bound >= worst["clean"].bound
    assert out[3] == (f"plan worst case ${top.bound:.6f} per arm (arm injected, at least ${top.floor:.6f}), "
                      f"cap $1.50")
    assert not any("WARNING" in line for line in out)


def test_an_arm_whose_upper_bound_only_is_over_the_cap_runs_with_a_warning(tmp_path, pinned_tokens,  # noqa: F811
                                                                         monkeypatch, capsys):
    cite = injected_cite(tmp_path)
    worst = planned(tmp_path, config(tmp_path, ADD), answering([]), prices())
    floor, bound = max(w.floor for w in worst.values()), min(w.bound for w in worst.values())
    assert floor < bound
    cap = (floor + bound) / 2  # every floor fits, no upper bound does
    path = config(tmp_path, ADD)
    path.write_text(path.read_text().replace("max_usd_per_arm = 1.5", f"max_usd_per_arm = {cap}"))
    sent: list[dict] = []
    tr_exp(tmp_path, monkeypatch, path, answering(sent, cite), prices())
    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if "WARNING" in line] == [
        f"WARNING arm {name}: plan worst case up to ${w.bound:.6f} with every thesis prompt at its largest, "
        f"over the cap ${cap:.2f} (floor ${w.floor:.6f} fits): its thesis stage may stop part way"
        for name, w in worst.items()]
    assert len(sent) == 4  # both arms ran on


def test_a_routed_arm_plans_less_than_the_same_arm_unrouted(tmp_path):
    injected_cite(tmp_path)  # headlines stored
    plain = planned(tmp_path, config(tmp_path, ADD), answering([]), SONNET)["injected"]
    routed = planned(tmp_path, config(tmp_path, ADD, extra=f'route = {{ analyze = "{HAIKU}" }}\n'), answering([]),
                     SONNET)["injected"]
    assert routed.floor < plain.floor and routed.bound < plain.bound
    assert plain.bound - routed.bound == pytest.approx(plain.floor - routed.floor)  # only the analysis step moved


def test_a_cached_arm_plans_at_the_cache_write_rate(tmp_path):
    injected_cite(tmp_path)
    plain = planned(tmp_path, config(tmp_path, ADD), Caching(answering([]), []), SONNET)["injected"]
    cached = planned(tmp_path, config(tmp_path, ADD, extra='cache = "5m"\n'), Caching(answering([]), []),
                     SONNET)["injected"]
    assert cached.floor > plain.floor and cached.bound > plain.bound


def test_the_thesis_bounds_hold_the_thesis_prompts_a_run_sends(tmp_path, pinned_tokens):  # noqa: F811
    cite = injected_cite(tmp_path)
    loaded = experiment.load(config(tmp_path, ADD))
    staged = experiment.stage(loaded, ten(), answering([]), tmp_path)
    sent: list[dict] = []
    experiment.run_arms(journal.connect(tmp_path / "journal.db"), loaded, ten(), answering(sent, cite), prices(),
                        tmp_path)
    thesis = an.system_prompt(th.DEFAULT_PROMPT)
    real = [user_turn(body) for body in sent if system_turn(body) == thesis]
    assert len(real) == 2  # the clean arm's, then the injected arm's (which cites the injected headline)
    for arm, text in zip(loaded.arms, real, strict=True):
        [smallest], [largest] = experiment.thesis_requests(arm, staged.data(arm))
        assert len(smallest.turns[1].content) < len(text) <= len(largest.turns[1].content)
        assert text.startswith(smallest.turns[1].content)  # the floor is the SOURCES table the thesis turn opens with


def system_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "system")


def user_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")

"""The `drop` arm knob (REPO-PLAN §2.5, week 5): the sections, the mask, the masking provider, and two arms at $0."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from gigai_core import compare
from gigai_core.providers import ModelRequest, Turn, request_sha256
from gigai_core.trace import ModelSpan

from test_teacher import context as live_context
from test_week4 import LIVE_CONTEXT_TOKENS, MODEL, PROMPT, context, load, prices, replaying
from tradingresearch import analyze as an, experiment, journal, masking, tools

TICKERS = ("FAKEA", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO")  # compare needs 10 clusters
EDGAR_NAMES = ("revenue_", "net_income_", "eps_diluted_")

PAIR = f"""name = "drop-pair"
model = "{MODEL}"
max_usd_per_arm = 1.0
tickers = {json.dumps(list(TICKERS))}
sessions = ["2026-11-13"]
graders = ["parsed", "all_claims_valid", "inferences_grounded"]

[[arms]]
name = "full"
prompt = "{PROMPT}"
drop = []

[[arms]]
name = "no-edgar"
prompt = "{PROMPT}"
drop = ["edgar"]
"""


@pytest.fixture
def pinned_tokens(monkeypatch):
    """The student tokenizer downloads from the HF hub; the stored context_tokens is pinned instead."""
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: LIVE_CONTEXT_TOKENS)


def ten() -> list[an.Context]:
    """The FAKEA context under ten tickers: ten items, ten clusters, the recorded reply valid for each."""
    ctx = context()
    return [replace(ctx, ticker=t, snapshot=ctx.snapshot.model_copy(update={"ticker": t})) for t in TICKERS]


def user_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")


def reply() -> dict:
    """The recorded reply cut to its valid claims (c1-c6) plus one fact citing an EDGAR row, valid on full context."""
    raw = load("turn2.reply")
    claims = json.loads(raw["choices"][0]["message"]["content"])["claims"]
    eps = next(row for row in context().rows if row.name == "eps_diluted_CY2026Q3")
    edgar = dict(id="c12", tag="fact", text="Diluted EPS for CY2026Q3 was {value}.", value=eps.value, unit=eps.unit,
                 source_ids=[eps.source_id], derived_from=[], steps=None)
    raw["choices"][0]["message"]["content"] = json.dumps({"claims": [*claims[:6], edgar]})
    return raw


@pytest.mark.parametrize("ctx", [context(), live_context()], ids=["fakea", "aapl-live"])
def test_the_sections_are_the_rows_each_week4_tool_serves(ctx):
    served = {"indicators": tools.indicators(ctx, {}), "levels": tools.levels(ctx, {}),
              "edgar": tools.fundamentals(ctx, {})}
    assert {row.name: masking.section_of(row.name) for row in ctx.rows} == {
        row.name: section for section, rows in served.items() for row in rows}
    assert set(masking.sections_shown(PROMPT)) == set(served)  # `headlines` only under analyze-3 (test_headlines)


def test_an_empty_drop_leaves_the_prompt_byte_for_byte():
    prompt = an.render(context())
    assert masking.mask(prompt, ()) is prompt


def test_dropping_a_section_removes_exactly_its_sources_lines():
    ctx = context()
    prompt = an.render(ctx)
    masked = masking.mask(prompt, ("edgar",))
    removed = [line for line in prompt.split("\n") if line not in masked.split("\n")]
    assert removed == [line for line in prompt.split("\n")
                       if any(row.source_id in line and row.name.startswith(EDGAR_NAMES) for row in ctx.rows)]
    assert len(removed) == 5 and "SOURCES (source_id | name | value | unit)" in masked
    assert masking.mask(masked, ("edgar",)) == masked  # masking twice is a no-op
    names = {row.source_id: row.name for row in ctx.rows}
    assert masking.hidden(names, ("edgar",)) == {s for s, n in names.items() if n.startswith(EDGAR_NAMES)}
    assert masking.hidden(names, ()) == frozenset()


def test_the_masking_provider_masks_only_user_turns_and_maps_the_route():
    sent: list[dict] = []
    masked = masking.Masked(replaying([load("turn2.reply")], sent), ("edgar", "levels"))
    prompt = an.render(context())
    request = ModelRequest(settings=an.call_settings(MODEL),
                           turns=(Turn(role="system", content=an.system_prompt(PROMPT)), Turn(role="user", content=prompt)))
    masked.invoke(request)
    assert sent[0]["messages"][0]["content"] == an.system_prompt(PROMPT)
    assert user_turn(sent[0]) == masking.mask(prompt, ("edgar", "levels")) != prompt
    assert masked.route_for(prompt) == "openrouter:Google"
    assert masked.inner.route_for(prompt) == "openrouter:unknown", "the inner provider only knows the masked text"


def test_two_arms_share_the_dataset_but_not_the_request_the_hash_or_the_verdict(tmp_path, pinned_tokens):
    sent: list[dict] = []
    path = tmp_path / "pair.toml"
    path.write_text(PAIR)
    config = experiment.load(path)
    assert [arm.drop for arm in config.arms] == [(), ("edgar",)]
    conn = journal.connect(tmp_path / "journal.db")
    full, no_edgar = experiment.run_arms(conn, config, ten(), replaying([reply()], sent), prices(), tmp_path)
    assert full.run.record.dataset == no_edgar.run.record.dataset
    assert [any(n in user_turn(body) for n in EDGAR_NAMES) for body in sent] == [True] * 10 + [False] * 10

    traced = {}
    for result in (full, no_edgar):
        lines = [json.loads(line) for line in Path(result.run.record.trace_path).read_text().splitlines()]
        traced[result.arm.name] = [line for line in lines if line["kind"] == ModelSpan.model_fields["kind"].default]
    assert len(traced["full"]) == len(traced["no-edgar"]) == 10
    for a, b, sample in zip(traced["full"], traced["no-edgar"], no_edgar.run.samples, strict=True):
        assert a["request_sha256"] != b["request_sha256"]
        masked = ModelRequest(settings=an.call_settings(MODEL), turns=sample.input)
        assert b["request_sha256"] == request_sha256(masked), "the trace digests the masked request"
        assert not any(n in b["last_turn"]["content"] for n in EDGAR_NAMES)

    rows = conn.execute("SELECT json_extract(body, '$.run_id'), json_extract(body, '$.input_hash'), "
                        "json_extract(body, '$.provider_route') FROM analysis").fetchall()
    hashes = {run: {h for r, h, _ in rows if r == run} for run in (full.run.record.run_id, no_edgar.run.record.run_id)}
    assert all(len(found) == 10 for found in hashes.values()) and not set.intersection(*hashes.values())
    assert {route for _, _, route in rows} == {"openrouter:Google"}
    assert (full.analyses, no_edgar.analyses) == (10, 10)

    assert experiment.means(full.run)["all_claims_valid"] == (1.0, 10)
    assert experiment.means(no_edgar.run)["all_claims_valid"] == (0.0, 10)
    assert {s.explanation for s in no_edgar.run.scores if s.grader_id == "all_claims_valid"} == {"dropped_source"}
    comparison = compare(full.run, no_edgar.run, config.graders)
    assert comparison.items == comparison.clusters == 10


def test_a_judge_grader_is_refused_for_a_drop_arm_before_any_call(tmp_path):
    sent: list[dict] = []
    path = tmp_path / "pair.toml"
    path.write_text(PAIR.replace('"inferences_grounded"]', '"inferences_grounded", "p1_judge"]'))
    conn = journal.connect(tmp_path / "journal.db")
    with pytest.raises(SystemExit, match="drop arm grades with code graders only, not p1_judge"):
        experiment.run_arms(conn, experiment.load(path), ten(), replaying([reply()], sent), prices(), tmp_path)
    assert sent == []

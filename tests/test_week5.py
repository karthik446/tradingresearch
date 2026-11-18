"""Week 5 acceptance: per-section grounding, the context-ablation experiment, ADR-007 and ADR-008.

Specs: REPO-PLAN "Week 5" and §2.5, PLAN-60 "Week 5". The learner files are looked up inside each test, so before
you write them every test here fails on its own and the rest of the suite still runs.

The contract, in the names these tests use:
- Per-section grounding: four registered code graders, one per `masking.SECTIONS`, with ids
  `indicators_grounded`, `levels_grounded`, `edgar_grounded` and `headlines_grounded`. Each has a `drop` attribute
  (default `()`), so `evals.graders(names, drop)` hands it a drop arm's list, as it does `all_claims_valid`.
  For one sample, a grader looks at the claims whose `source_ids` cite at least one row of its section
  (`masking.section_of(expected["names"][source_id])`). A claim citing rows of two sections counts in both. Its
  value is the share of those claims that `analyze.validate_claims` keeps, given the arm's hidden rows
  (`analyze.hidden_of(expected, drop)`). Below 1.0, the explanation starts with the sorted, distinct rejection
  reasons of the failed claims (`dropped_source`, `unsourced_number`, ...). When no claim cites the section, the
  grader raises `CannotGrade` with a message starting `not_cited`: no score, never 1.0. A sample that did not
  parse also raises `CannotGrade`.
- `experiments/context-ablation.toml`, a new file next to `headlines.toml`: three fixed arms with prompt
  `analyze-3` and the same model and provider, differing only in `drop`: `[]`, `["headlines"]` and `["edgar"]`.
  `cluster = "ticker"`. Its graders include `all_claims_valid` and the four section graders.
- `docs/adr/ADR-007-which-context-sections-stay.md`: the decision, the experiment it reads, a table with one column
  per arm (full, no headlines, no EDGAR) whose cells are numbers (with the run id they came from) or
  `awaiting experiment` / `awaiting sessions`, and the consequences.
- `docs/adr/ADR-008-mcp-gateway-registry.md`: a design write-up: the decision, the options considered (at least
  two), the consequences and readings. It covers the registry, auth and the audit trail, the week-4 tools by name,
  and where an exchange's provenance (route) is kept.

The model reply is one recorded real exchange (claude-sonnet-5.5 through the repo's `OpenRouter` and analyze's
request builder, prompt analyze-3, 2026-11-17 UTC, $0.016048, run run_a9e1c3a279e24b05) on the made-up FAKEA
context in tests/fixtures/week5/: week 4's rows plus three invented headlines. It is replayed at the HTTP transport.
Of its 11 claims, 7 cite indicator rows (one fails, `empty_placeholder`), 1 cites a headline, none cites a level or
an EDGAR row.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from gigai_core.budget import Price
from gigai_core.graders.protocol import CannotGrade
from gigai_core.sample import Sample
from gigai_core.score import Score

from tradingresearch import analyze as an, evals, experiment, journal, masking, news, tools
from tradingresearch.providers.openrouter import API, OpenRouter
from tradingresearch.records import IndicatorSnapshot, SourceRef

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "week5"
PROMPT = "analyze-3"  # the recorded system prompt
CONFIG = ROOT / "experiments" / "context-ablation.toml"
ADR_007 = ROOT / "docs" / "adr" / "ADR-007-which-context-sections-stay.md"
ADR_008 = ROOT / "docs" / "adr" / "ADR-008-mcp-gateway-registry.md"
SECTIONS = masking.SECTIONS
DROPS = [(), ("edgar",), ("headlines",)]
AWAITING = ("awaiting sessions", "awaiting experiment")
NUMBER = re.compile(r"\$?-?\d[\d,]*(\.\d+)?\s*(%|ms|s)?", re.IGNORECASE)
RUN_ID = r"\brun_[0-9a-f]{16}\b"
T0 = datetime(2026, 11, 17, tzinfo=UTC)
LIVE_CONTEXT_TOKENS = 1600  # pinned: the student tokenizer downloads from the HF hub
RECORDED = {"indicators": (6 / 7, "empty_placeholder"), "headlines": (1.0, None)}  # cited sections of the reply


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def context() -> an.Context:
    """The hand-built FAKEA context, headlines included, that the recorded call was asked about."""
    raw = load("fakea.context")
    return an.Context(raw["ticker"], date.fromisoformat(raw["session"]),
                      IndicatorSnapshot.model_validate_json(json.dumps(raw["snapshot"])),
                      [SourceRef.model_validate_json(json.dumps(s)) for s in raw["sources"]],
                      [an.Row(**r) for r in raw["rows"]],
                      tuple(news.Headline.model_validate_json(json.dumps(h)) for h in raw["headlines"]))


def expected() -> dict:
    return an.item_for(context()).expected


def recorded_parsed() -> dict:
    return json.loads(load("analyze3.reply")["choices"][0]["message"]["content"])


def user_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")


def system_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "system")


def prices(models) -> dict[str, Price]:
    """The /models price row recorded with the exchange, for each model named."""
    [row] = load("models")["data"]
    return {model: Price(model=model, prompt_usd_per_token=float(row["pricing"]["prompt"]),
                         completion_usd_per_token=float(row["pricing"]["completion"]), fetched_at=T0,
                         source=f"{API}/models") for model in models}


def replaying(reply: dict, sent: list[dict]) -> OpenRouter:
    """The real adapter; its transport answers every request with the recorded reply."""
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=reply)

    provider = OpenRouter("not-a-real-key")
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


@pytest.fixture
def pinned_tokens(monkeypatch):
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: LIVE_CONTEXT_TOKENS)


# ---------- the per-section grounding graders (hand-built samples) ----------

def name_of(section: str) -> str:
    return f"{section}_grounded"


def sample_of(parsed: dict | None) -> Sample:
    """A succeeded sample of `parsed` (None: a reply that did not parse)."""
    return Sample(trace_id="trace_week5", run_id="run_week5", item_id="FAKEA:2026-11-13", item_version="1",
                  cluster_id="FAKEA", repeat_index=0, input=(), output_text=json.dumps(parsed) if parsed else "nope",
                  output_parsed=parsed, parse_status="ok" if parsed is not None else "not_json",
                  outcome="succeeded", error=None, spans=(), recorded_at=T0)


def grade(section: str, claims: list[dict], drop: tuple[str, ...] = ()) -> Score:
    """The section's grader, built as an experiment arm builds it, on a sample holding `claims`."""
    [grader] = evals.graders([name_of(section)], drop)
    return grader.grade(sample_of({"claims": claims}), expected())


def row(name: str) -> an.Row:
    return next(r for r in context().table() if r.name == name)


def fact(cid: str, *names: str, value: float | None = None) -> dict:
    """A fact citing the named rows; `value` defaults to the first row's (valid), or pass a wrong one."""
    rows = [row(name) for name in names]
    value = rows[0].value if value is None else value
    return dict(id=cid, tag="fact", text="The row reads {value}." if value is not None else "A headline says so.",
                value=value, unit=rows[0].unit, source_ids=[r.source_id for r in rows], derived_from=[], steps=None)


def headline_name() -> str:
    return next(r.name for r in context().table() if masking.section_of(r.name) == "headlines")


def edgar_name() -> str:
    return next(r.name for r in context().rows if masking.section_of(r.name) == "edgar")


def test_one_grounding_grader_per_section_is_registered_as_code():
    for section in SECTIONS:
        cls = evals.GRADERS[name_of(section)]
        assert cls.kind == "code" and cls.id == name_of(section) and cls.version, cls
        assert getattr(cls(), "drop", None) == (), f"{cls.id} needs a `drop` attribute defaulting to ()"


def test_each_cited_section_scores_the_share_of_its_valid_claims():
    """Indicators: one valid, one wrong number (0.5, `unsourced_number`); the other sections' claims all pass."""
    claims = [fact("c1", "close"), fact("c2", "close", value=150.0), fact("c3", "level_hvn_1"),
              fact("c4", edgar_name()), fact("c5", headline_name())]
    indicators = grade("indicators", claims)
    assert indicators.value == 0.5 and (indicators.explanation or "").startswith("unsourced_number"), indicators
    for section in ("levels", "edgar", "headlines"):
        assert grade(section, claims).value == 1.0, section


@pytest.mark.parametrize("claims", [[], [fact("c1", "close")]], ids=["no_claims", "indicators_only"])
def test_a_section_no_claim_cites_is_not_cited_never_one(claims):
    for section in ("levels", "edgar", "headlines"):
        with pytest.raises(CannotGrade, match=r"^not_cited"):
            grade(section, claims)


def test_a_claim_citing_two_sections_counts_in_both():
    valid, wrong = fact("c1", "close", "level_hvn_1"), fact("c2", "close", "level_hvn_1", value=150.0)
    for section in ("indicators", "levels"):
        assert grade(section, [valid]).value == 1.0, section
        score = grade(section, [wrong])
        assert score.value == 0.0 and (score.explanation or "").startswith("unsourced_number"), (section, score)


@pytest.mark.parametrize("dropped", ["headlines", "edgar"])
def test_a_drop_arm_fails_the_dropped_sections_claims(dropped):
    claims = [fact("c1", "close"), fact("c2", headline_name() if dropped == "headlines" else edgar_name())]
    score = grade(dropped, claims, (dropped,))
    assert score.value == 0.0 and (score.explanation or "").startswith("dropped_source"), score
    assert grade("indicators", claims, (dropped,)).value == 1.0
    assert grade(dropped, claims).value == 1.0, "the full arm saw the row"


def test_a_reply_that_did_not_parse_cannot_be_graded():
    for section in SECTIONS:
        [grader] = evals.graders([name_of(section)])
        with pytest.raises(CannotGrade):
            grader.grade(sample_of(None), expected())


# ---------- the recorded analyze-3 reply ----------

def test_the_recorded_reply_gets_a_result_per_section():
    """Indicators 6/7 (c10 is `empty_placeholder`), headlines 1/1, levels and EDGAR not cited."""
    names = expected()["names"]
    cited = {masking.section_of(names[s]) for claim in recorded_parsed()["claims"] for s in claim["source_ids"]}
    assert cited == set(RECORDED), "the fixture is not the recorded reply"
    for section in SECTIONS:
        [grader] = evals.graders([name_of(section)])
        if section not in RECORDED:
            with pytest.raises(CannotGrade, match=r"^not_cited"):
                grader.grade(sample_of(recorded_parsed()), expected())
            continue
        value, reason = RECORDED[section]
        score = grader.grade(sample_of(recorded_parsed()), expected())
        assert score.value == pytest.approx(value), (section, score)
        if reason:
            assert (score.explanation or "").startswith(reason), (section, score)


def test_dropping_headlines_flags_the_recorded_headline_claim():
    all_valid, headlines = evals.graders(["all_claims_valid", name_of("headlines")], ("headlines",))
    sample = sample_of(recorded_parsed())
    assert "dropped_source" in (all_valid.grade(sample, expected()).explanation or "")
    score = headlines.grade(sample, expected())
    assert score.value == 0.0 and (score.explanation or "").startswith("dropped_source"), score


# ---------- the context-ablation experiment ----------

def test_the_context_ablation_has_three_analyze3_arms_that_differ_only_in_drop():
    config = experiment.load(CONFIG)
    assert CONFIG.name != "headlines.toml"
    assert sorted(arm.drop for arm in config.arms) == DROPS
    assert {(arm.prompt, arm.model, json.dumps(arm.provider, sort_keys=True, default=str), arm.mode)
            for arm in config.arms} == {(PROMPT, config.arms[0].model,
                                         json.dumps(config.arms[0].provider, sort_keys=True, default=str), "fixed")}
    assert config.cluster == "ticker"
    for name in ("all_claims_valid", *map(name_of, SECTIONS)):
        assert name in config.graders, name


def run_ablation(tmp_path: Path, sent: list[dict]):
    """The ablation's arms over its tickers at $0, every ticker holding the FAKEA rows and headlines: the headlines
    sit in the news store (analyze-3 arms read them there), each window day marked fetched."""
    config = experiment.load(CONFIG)
    ctx = context()
    contexts = [replace(ctx, ticker=t, snapshot=ctx.snapshot.model_copy(update={"ticker": t}), headlines=())
                for t in config.tickers]
    for t in config.tickers:
        news.store(tmp_path, t, list(ctx.headlines))
        for day in news.days_in(*news.window(ctx.session)):
            news.path_for(tmp_path, t, day).touch()
        assert news.missing_days(tmp_path, t, ctx.session) == []
    conn = journal.connect(tmp_path / "journal.db")
    provider = replaying(load("analyze3.reply"), sent)
    return config, experiment.run_arms(conn, config, contexts, provider, prices({a.model for a in config.arms}),
                                       tmp_path)


def test_the_ablation_sends_each_arm_the_recorded_request_masked_over_one_dataset(tmp_path, pinned_tokens):
    sent: list[dict] = []
    config, results = run_ablation(tmp_path, sent)
    n = len(config.tickers)
    assert len(results) == 3 and len(sent) == 3 * n
    assert len({result.run.record.dataset for result in results}) == 1, "the arms must share one dataset digest"
    recorded = load("analyze3.request")
    assert user_turn(recorded) == an.render(context()), "the fixture is not the current render"
    requests = set()
    for i, result in enumerate(results):
        want = masking.mask(user_turn(recorded), result.arm.drop)
        for body in sent[i * n:(i + 1) * n]:
            assert system_turn(body) == an.system_prompt(PROMPT) == system_turn(recorded)
            ticker = re.match(r"TICKER: (\S+)", user_turn(body)).group(1)
            assert user_turn(body) == want.replace("TICKER: FAKEA", f"TICKER: {ticker}", 1)
        requests.add(want)
        assert result.analyses == n
    assert len(requests) == 3


def test_the_ablation_grades_the_recorded_reply_per_arm(tmp_path, pinned_tokens):
    """The reply cites one headline and no EDGAR row: dropping headlines fails that claim (`dropped_source`),
    dropping EDGAR leaves every score as on the full arm, and the uncited sections get no score in any arm."""
    sent: list[dict] = []
    config, results = run_ablation(tmp_path, sent)
    n = len(config.tickers)
    by_drop = {result.arm.drop: result.run for result in results}
    for drop in [(), ("edgar",)]:
        means = experiment.means(by_drop[drop])
        assert means[name_of("headlines")] == (1.0, n), drop
        assert means[name_of("indicators")] == (pytest.approx(6 / 7), n), drop
        assert name_of("levels") not in means and name_of("edgar") not in means, drop
    no_headlines = by_drop[("headlines",)]
    assert experiment.means(no_headlines)[name_of("headlines")] == (0.0, n)
    for score in no_headlines.scores:
        if score.grader_id == name_of("headlines"):
            assert (score.explanation or "").startswith("dropped_source"), score
        if score.grader_id == "all_claims_valid":
            assert "dropped_source" in (score.explanation or ""), score


# ---------- ADR-007 (structure only) ----------

def table(text: str, what: str) -> list[list[str]]:
    """The cells of the first markdown table, the separator row dropped."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("|")), None)
    assert start is not None, f"{what} has no table"
    block = []
    for line in lines[start:]:
        if not line.lstrip().startswith("|"):
            break
        block.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return [cells for cells in block if not set("".join(cells)) <= set("-: ")]


def adr(path: Path, number: str) -> str:
    assert path.exists(), f"{path.relative_to(ROOT)} is missing"
    text = path.read_text()
    assert text.startswith(f"# ADR-{number}"), text[:40]
    for label in ("**Status:**", "**Decision.**", "**Consequences.**"):  # the labels ADR-001..005 use
        assert label in text, label
    return text


def test_adr_007_records_the_decision_a_measured_table_and_the_consequences():
    """Reads context-ablation.toml; a full / no-headlines / no-EDGAR table of numbers (with a run id) or awaiting."""
    text = adr(ADR_007, "007")
    assert "context-ablation.toml" in text
    header, *body = table(text, "ADR-007")
    columns = [cell.lower() for cell in header[1:]]
    for arm in ("full", "headlines", "edgar"):
        assert any(arm in cell for cell in columns), f"no column for the {arm} arm: {header}"
    for metric in ("all_claims_valid", "grounded", "token", "cost"):
        assert [cells for cells in body if metric in cells[0].lower()], f"no table row for {metric}"
    values = [cell for cells in body for cell in cells[1:]]
    for cell in values:
        assert NUMBER.fullmatch(cell) or cell.lower() in AWAITING, f"not a number or {AWAITING}: {cell!r}"
    if any(NUMBER.fullmatch(cell) for cell in values):
        assert re.search(RUN_ID, text), "a measured number needs the run id it came from"


# ---------- ADR-008 (structure only) ----------

def test_adr_008_weighs_options_for_an_mcp_gateway_and_registry():
    text = adr(ADR_008, "008")
    for label in ("**Options considered.**", "**Readings.**"):
        assert label in text, label
    options = text.split("**Options considered.**", 1)[1].split("**Decision.**", 1)[0]
    listed = [line for line in options.splitlines() if re.match(r"\s*(?:[-*]|\d+\.)\s+\S", line)]
    assert len(listed) >= 2, "list at least two options, one per bullet or numbered line"
    lower = text.lower()
    for topic in ("registry", "auth", "audit", "route"):
        assert topic in lower, topic
    for spec in tools.TOOLS:
        assert spec.name in text, f"name the week-4 tool {spec.name}"
    assert re.search(r"https?://", text.split("**Readings.**", 1)[1]), "readings need a link"

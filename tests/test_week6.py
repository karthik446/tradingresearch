"""Week 6 acceptance: retrieval scoping, the labelled query set, the citation_accuracy grader, the retrieval
experiment and ADR-009.

Specs: REPO-PLAN "Week 6" and §1.3, RETRIEVAL-SPIKE §3 and §4.3. The learner files are looked up inside each test, so
before you write them each of those tests fails with `learner part missing: ...` and the rest of the suite still
runs. The tests on the recorded exchange need no learner file and pass from the start.

The contract, in the names these tests use:
- `docs/retrieval-scoping.md`: a `#` title and `##` sections for the corpus, permissions (who may see what), freshness,
  what is out of scope and the threat model; no section is empty, and the threat model names prompt injection.
- `evals/retrieval_query.jsonl` (shipped empty; `evals/retrieval_query.schema.md` defines a row): at least 30 rows
  that `retrieval.evaluate.parse` accepts, unique ids, kinds from `evaluate.KINDS` with at least two kinds holding 5
  rows or more, each `as_of` an NYSE session. Every gold quote must resolve (`evaluate.validate`) in the newest index
  under `<data dir>/retrieval/` (`TR_DATA_DIR`, else `data/`); with no index the test names the
  `uv run tr retrieval build --ticker ...` command to run. The test makes no network call.
- The `citation_accuracy` grader, a registered code grader (`evaluate.citation_grader()` finds it). Its `expected` is
  a retrieval arm's grading view (`experiment.with_passages`): `passages` maps each retrieved chunk id to its text.
  A claim cites a passage by putting its chunk id (`<doc id>#<n>`) in `source_ids`; that id is the citation and the
  chunk's text is the quote. analyze-3 claims have no quote field, and a claim whose text holds digits already fails
  `number_in_text`, so the grader checks the chunk id and the claim's `value`, never a quoted span.
  The graded claims are those citing at least one chunk id. A graded claim is supported when every chunk id it cites
  is among the passages (else `not_retrieved`) and its `value`, when not null, matches a number written in one of
  its cited passages within `analyze.REL_TOL` (0.5%; else `number_mismatch`). Signs are ignored, since a filing
  prints a loss as `(45)`, and so are thousands separators. Score = supported share of the graded claims. Below 1.0
  the explanation starts with the sorted, distinct reasons. No graded claim raises `CannotGrade` with a message
  starting `no_claims`, and so does a reply that did not parse. A judge that checks what a claim's prose says about
  a passage is a later variant, not part of this contract.
- `evals/specs/citation_accuracy.md`: the eval spec, in the shape of the other files in evals/specs/.
- `experiments/retrieval.toml`: two fixed arms with prompt `analyze-3` and the same model and provider, one without
  retrieval (no table or `mode = "none"`) and one `hybrid` with k 5, over at least 20 ticker-days. `cluster = "ticker"`.
  Its graders include `claims_valid`, `all_claims_valid` and `citation_accuracy`.
- `docs/adr/ADR-009-retrieval-design.md`: status, the options considered (at least two), the decision, the
  consequences and readings. It has two tables. The recall table has one row per retriever (`evaluate.RETRIEVERS`) and
  recall_any@1/5/10/20 columns, with the index digest stated for any number. The experiment table has none and hybrid
  columns and rows for claims_valid, all_claims_valid, citation_accuracy and cost, with a run id stated for any
  number. A cell is a number or `awaiting experiment` / `awaiting sessions`; `citation_accuracy` may read `n/a` in
  the none arm, which has no passages.

The model reply is one recorded real exchange (claude-sonnet-5.5 through the repo's `OpenRouter`, served by Google, a
retrieval arm's request built by `experiment.run_masked` and `masking.Augmented`, prompt analyze-3, 2026-11-17 UTC,
$0.028106, 3,373 prompt / 2,136 completion tokens, run run_e41138c0dd4a45e0). It was asked about week 5's made-up
FAKEA context with three BM25 passages (k 3, the default query) from an index of G13a's invented FAKEA filings
(tests/fixtures/retrieval/). The reply is replayed at the HTTP transport. Its 12 claims all pass `claims_valid` and
none cites a passage, so `citation_accuracy` cannot grade it. The graded cases are hand-made claims on its passages.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from gigai_core import Dataset
from gigai_core.budget import Price
from gigai_core.graders.protocol import CannotGrade
from gigai_core.sample import Sample
from test_retrieval_ingest import NOW, fake_archives

from tradingresearch import analyze as an, evals, experiment, masking, news, sessions
from tradingresearch.config import settings
from tradingresearch.providers.openrouter import API, OpenRouter
from tradingresearch.records import IndicatorSnapshot, SourceRef
from tradingresearch.retrieval import evaluate, ingest, manifest, store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "week6"
PROMPT = "analyze-3"  # the recorded system prompt
SCOPING = ROOT / "docs" / "retrieval-scoping.md"
QUERIES = ROOT / "evals" / "retrieval_query.jsonl"
SPEC = ROOT / "evals" / "specs" / "citation_accuracy.md"
CONFIG = ROOT / "experiments" / "retrieval.toml"
ADR_009 = ROOT / "docs" / "adr" / "ADR-009-retrieval-design.md"
GRADER = evaluate.CITATION_GRADER
AWAITING = ("awaiting sessions", "awaiting experiment")
NUMBER = re.compile(r"\$?-?\d[\d,]*(\.\d+)?\s*(%|ms|s)?", re.IGNORECASE)
RUN_ID = r"\brun_[0-9a-f]{16}\b"
DIGEST = r"\bsha256:[0-9a-f]{12,64}\b"
T0 = datetime(2026, 11, 17, tzinfo=UTC)
RECORDED_USD = 0.028106
EX991 = "0009999999-26-000101/fakea-ex991.htm#1"  # retrieved: the statement of operations table
RECALL = "0009999999-26-000103/fakea-8k_20261106.htm#0"  # retrieved: the Gizmo recall 8-K
TENQ = "0009999999-26-000102/fakea-20260930.htm#0"  # retrieved: the 10-Q MD&A (cash $2,980 million)
UNSEEN = "0009999999-26-000101/fakea-8k_20261029.htm#0"  # in the index, not retrieved


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


def retrieved() -> store.Retrieved:
    """The three passages the recorded call was sent."""
    raw = load("retrieved")
    return store.Retrieved(raw["ticker"], date.fromisoformat(raw["as_of"]), raw["mode"], raw["k"], raw["index_digest"],
                           raw["query"], raw["query_template"], tuple(store.Passage(**p) for p in raw["passages"]),
                           raw["masked_docs"])


def expected() -> dict:
    """The retrieval arm's grading view of the FAKEA item."""
    return experiment.with_passages(an.item_for(context()).expected, retrieved())


def recorded_parsed() -> dict:
    return json.loads(load("analyze3.reply")["choices"][0]["message"]["content"])


def user_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")


def system_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "system")


def prices(model: str) -> dict[str, Price]:
    [row] = load("models")["data"]
    return {model: Price(model=model, prompt_usd_per_token=float(row["pricing"]["prompt"]),
                         completion_usd_per_token=float(row["pricing"]["completion"]), fetched_at=T0,
                         source=f"{API}/models")}


def replaying(reply: dict, sent: list[dict]) -> OpenRouter:
    """The real adapter; its transport answers every request with the recorded reply."""
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=reply)

    provider = OpenRouter("not-a-real-key")
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def learner(path: Path, what: str) -> str:
    """The learner file's text; missing or empty fails the test with what to write."""
    if not path.exists() or not path.read_text().strip():
        pytest.fail(f"learner part missing: {path.relative_to(ROOT)} ({what}; contract in tests/test_week6.py)",
                    pytrace=False)
    return path.read_text()


# ---------- the recorded exchange (no learner file) ----------

def test_the_recorded_passages_come_from_the_fakea_filing_index(tmp_path):
    archives, _ = fake_archives(tmp_path / "edgar")
    built, records = manifest.build(ingest.filing_docs(archives, "FAKEA", 1, NOW), 256)
    manifest.write(tmp_path / "retrieval", built, records)
    index = manifest.load(tmp_path / "retrieval")
    want = retrieved()
    assert index.digest == want.index_digest
    knob = store.Knob(want.mode, want.k, index.digest, want.query_template)
    got = store.retrieve(index, evaluate.bm25_retriever(index), knob, want.ticker, want.as_of,
                         datetime.fromisoformat(load("retrieved")["now"]))
    assert got == want
    assert {EX991, RECALL, TENQ} == {p.chunk_id for p in want.passages}
    assert UNSEEN.rsplit("#", 1)[0] in index.docs


def test_the_recorded_request_is_analyze3_with_the_passages_before_the_closing_line():
    recorded = load("analyze3.request")
    assert system_turn(recorded) == an.system_prompt(PROMPT)
    assert user_turn(recorded) == masking.augment(an.render(context()), retrieved()), "not the current render"
    assert masking.PASSAGES in user_turn(recorded)


def test_a_retrieval_arm_replays_the_recorded_request_and_its_claims_stay_valid(tmp_path):
    """The passages are citable rows without a number, so claims_valid keeps all 12 recorded claims."""
    recorded = load("analyze3.request")
    ctx, want = context(), retrieved()
    item = an.item_for(ctx)
    arm = experiment.Arm("bm25-3", PROMPT, recorded["model"],
                         retrieval=store.Knob(want.mode, want.k, want.index_digest, want.query_template))
    config = experiment.Config("week6", (ctx.ticker,), (ctx.session,), ("claims_valid",), (arm,), 0.10)
    sent: list[dict] = []
    provider = masking.Augmented(replaying(load("analyze3.reply"), sent),
                                 {item.prompt: masking.augment(item.prompt, want)})
    run = experiment.run_masked(config, arm, Dataset.of(config.name, [item]), provider,
                                evals.graders(["claims_valid"]), prices(arm.model), tmp_path, {item.id: expected()})
    assert sent == [recorded]
    assert [(s.grader_id, s.value) for s in run.scores] == [("claims_valid", 1.0)]
    assert len(recorded_parsed()["claims"]) == 12


# ---------- the citation_accuracy grader ----------

def sample_of(parsed: dict | None) -> Sample:
    """A succeeded sample of `parsed` (None: a reply that did not parse)."""
    return Sample(trace_id="trace_week6", run_id="run_week6", item_id="FAKEA:2026-11-13", item_version="1",
                  cluster_id="FAKEA", repeat_index=0, input=(), output_text=json.dumps(parsed) if parsed else "nope",
                  output_parsed=parsed, parse_status="ok" if parsed is not None else "not_json",
                  outcome="succeeded", error=None, spans=(), recorded_at=T0)


def citation():
    """The learner's grader, built as an experiment arm builds it."""
    if GRADER not in evals.GRADERS:
        pytest.fail(f"learner part missing: the {GRADER} grader (evals.py, @grader, id {GRADER!r}, kind 'code'; "
                    "contract in tests/test_week6.py)", pytrace=False)
    [grader] = evals.graders([GRADER])
    return grader


def cites(cid: str, *chunks: str, value: float | None = None) -> dict:
    """A fact citing passages by chunk id; no digit in its text."""
    return dict(id=cid, tag="fact", text="The filing reports {value}." if value is not None else "FakeA recalled Gizmos.",
                value=value, unit="USD" if value is not None else None, source_ids=list(chunks), derived_from=[],
                steps=None)


def grade(*claims: dict, view: dict | None = None):
    """The grader on the recorded claims (none cites a passage) plus `claims`."""
    parsed = {"claims": recorded_parsed()["claims"] + list(claims)}
    return citation().grade(sample_of(parsed), expected() if view is None else view)


def test_citation_accuracy_is_a_registered_code_grader():
    grader = citation()
    assert evaluate.citation_grader() is type(grader)
    assert (grader.id, grader.kind) == (GRADER, "code")


@pytest.mark.parametrize("chunks, value", [
    ((EX991,), 701.0),  # Net income $701
    ((EX991,), 703.0),  # within 0.5% of 701
    ((EX991,), 3210.0),  # $3,210: the thousands separator is ignored
    ((EX991,), -45.0),  # (45): the sign is ignored
    ((EX991,), 1.23),  # diluted EPS
    ((TENQ, EX991), 2980.0),  # in one of the cited passages
    ((RECALL,), None),  # no number to check
], ids=["exact", "rounded", "separator", "parenthesised", "decimal", "second_passage", "no_value"])
def test_a_claim_is_supported_when_its_passages_were_retrieved_and_hold_its_value(chunks, value):
    score = grade(cites("p1", *chunks, value=value))
    assert score.value == 1.0, score


@pytest.mark.parametrize("chunks, value", [((EX991,), 750.0), ((EX991,), 2980.0), ((RECALL,), 701.0)],
                         ids=["wrong", "in_an_uncited_passage", "not_in_the_passage"])
def test_a_value_no_cited_passage_holds_is_number_mismatch(chunks, value):
    score = grade(cites("p1", *chunks, value=value))
    assert score.value == 0.0
    assert (score.explanation or "").startswith("number_mismatch"), score


@pytest.mark.parametrize("chunks, value", [((UNSEEN,), None), ((EX991, UNSEEN), 701.0)],
                         ids=["unseen", "one_of_two_unseen"])
def test_citing_a_chunk_that_was_not_retrieved_is_not_retrieved(chunks, value):
    score = grade(cites("p1", *chunks, value=value))
    assert score.value == 0.0
    assert (score.explanation or "").startswith("not_retrieved"), score


def test_the_score_is_the_supported_share_with_the_sorted_reasons_first():
    score = grade(cites("p1", EX991, value=701.0), cites("p2", EX991, value=750.0), cites("p3", UNSEEN))
    assert score.value == pytest.approx(1 / 3)
    assert (score.explanation or "").startswith("not_retrieved, number_mismatch"), score


def test_an_arm_without_passages_finds_every_cited_chunk_not_retrieved():
    score = grade(cites("p1", EX991, value=701.0), view=an.item_for(context()).expected)
    assert score.value == 0.0
    assert (score.explanation or "").startswith("not_retrieved"), score


@pytest.mark.parametrize("parsed", [None, {"claims": []}, "recorded"], ids=["not_parsed", "no_claims", "recorded"])
def test_no_claim_citing_a_passage_cannot_be_graded(parsed):
    """The recorded reply cites no passage: no score, never 1.0."""
    grader = citation()
    parsed = recorded_parsed() if parsed == "recorded" else parsed
    with pytest.raises(CannotGrade) as raised:
        grader.grade(sample_of(parsed), expected())
    if parsed is not None:
        assert str(raised.value).startswith("no_claims"), raised.value


# ---------- learner documents and config ----------

def sections(text: str, level: str = "##") -> dict[str, str]:
    """Heading text (lower case) -> the body under it, for headings of exactly `level`."""
    found, current = {}, None
    for line in text.splitlines():
        heading = re.match(rf"{level}\s+(.+)", line)
        if heading and not line.startswith(level + "#"):
            current = heading.group(1).strip().lower()
            found[current] = ""
        elif current is not None:
            found[current] += line + "\n"
    return found


def test_the_scoping_doc_covers_corpus_permissions_freshness_scope_and_threats():
    text = learner(SCOPING, "the retrieval scoping doc")
    assert text.startswith("# "), "start with a # title"
    found = sections(text)
    for topic in ("corpus", "permission", "freshness", "out of scope", "threat model"):
        assert any(topic in heading for heading in found), f"no ## section for {topic}: {sorted(found)}"
    for heading, body in found.items():
        assert body.strip(), f"section {heading!r} is empty"
    threats = next(body for heading, body in found.items() if "threat model" in heading)
    assert "injection" in threats.lower(), "the threat model names prompt injection"


def query_rows() -> list[dict]:
    learner(QUERIES, f"at least 30 labelled queries, schema {QUERIES.with_suffix('.schema.md').name}")
    return evaluate.read(QUERIES)


def test_the_query_set_holds_30_valid_rows_over_at_least_two_kinds():
    rows = query_rows()
    assert len(rows) >= 30, f"{len(rows)} rows, at least 30"
    problems, kinds, ids = [], Counter(), Counter()
    for n, row in enumerate(rows, start=1):
        try:
            query = evaluate.parse(row)
        except (ValueError, TypeError) as error:
            problems.append(f"line {n}: {error}")
            continue
        ids[query.id] += 1
        kinds[query.kind] += 1
        if query.kind not in evaluate.KINDS:
            problems.append(f"line {n}: kind {query.kind!r} is not one of {evaluate.KINDS}")
        if not sessions.is_session(query.as_of):
            problems.append(f"line {n}: {query.as_of} is not an NYSE session")
    problems += [f"id {qid!r} appears {count} times" for qid, count in ids.items() if count > 1]
    assert not problems, "\n".join(problems)
    assert sum(count >= 5 for count in kinds.values()) >= 2, f"two kinds need 5 rows or more: {dict(kinds)}"


def test_every_gold_quote_resolves_in_the_local_index():
    rows = query_rows()
    root = ROOT / settings().data_dir / "retrieval"
    if not list(root.glob("*/manifest.json")):
        tickers = " ".join(sorted({str(row.get("ticker")) for row in rows}))
        pytest.fail(f"no retrieval index under {root}: run `uv run tr retrieval build --ticker {tickers}`",
                    pytrace=False)
    index = manifest.load(root)
    _, problems = evaluate.validate(rows, index)
    golds = sum(len(row.get("gold") or []) for row in rows)
    unresolved = [p for p in problems if "gold doc" in p or "in no chunk" in p]
    assert not problems, (f"{len(unresolved)} of {golds} gold quotes do not resolve in index {index.digest}:\n"
                          + "\n".join(problems))


def test_the_citation_accuracy_spec_says_what_counts_as_supported():
    text = learner(SPEC, "the eval spec of citation_accuracy")
    assert text.startswith("# Eval spec") and GRADER in text.splitlines()[0], text[:60]
    for label in ("**Question it answers:**", "**Unit and score:**", "**What counts as supported:**",
                  "**Tolerance:**", "**What is not checked:**", "**Judge variant:**", "**Inputs:**", "**Tests:**"):
        assert label in text, label
    for term in ("CannotGrade", "not_retrieved", "number_mismatch", "no_claims"):
        assert term in text, term
    assert "0.5%" in text or "0.005" in text, "state the tolerance"


def test_the_retrieval_experiment_compares_no_passages_with_hybrid_k5():
    learner(CONFIG, "the none vs hybrid experiment")
    config = experiment.load(CONFIG)
    assert len(config.arms) == 2, [arm.name for arm in config.arms]
    assert {(arm.prompt, arm.model, json.dumps(arm.provider, sort_keys=True, default=str), arm.mode, arm.drop)
            for arm in config.arms} == {(PROMPT, config.arms[0].model,
                                         json.dumps(config.arms[0].provider, sort_keys=True, default=str), "fixed", ())}
    knobs = sorted((arm.retrieval.mode, arm.retrieval.k) if arm.retrieval else ("none", 0) for arm in config.arms)
    assert knobs == [("hybrid", 5), ("none", 0)]
    assert config.cluster == "ticker"
    assert len(config.tickers) * len(config.sessions) >= 20, "at least 20 ticker-days"
    for name in ("claims_valid", "all_claims_valid", GRADER):
        assert name in config.graders, name


# ---------- ADR-009 (structure only) ----------

def tables(text: str) -> list[list[list[str]]]:
    """The cells of every markdown table, separator rows dropped."""
    found, block = [], []
    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            block.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif block:
            found.append([cells for cells in block if not set("".join(cells)) <= set("-: ")])
            block = []
    return found


def cell_ok(cell: str) -> bool:
    return bool(NUMBER.fullmatch(cell)) or cell.lower() in AWAITING


def test_adr_009_records_the_options_the_decision_and_the_readings():
    text = learner(ADR_009, "the retrieval design ADR")
    assert text.startswith("# ADR-009"), text[:40]
    for label in ("**Status:**", "**Options considered.**", "**Decision.**", "**Consequences.**", "**Readings.**"):
        assert label in text, label
    options = re.split(r"\n\*\*", text.split("**Options considered.**", 1)[1], maxsplit=1)[0]
    listed = [line for line in options.splitlines() if re.match(r"\s*(?:[-*]|\d+\.)\s+\S", line)]
    assert len(listed) >= 2, "list at least two options, one per bullet or numbered line"
    assert "retrieval.toml" in text
    assert re.search(r"https?://", text.split("**Readings.**", 1)[1]), "readings need a link"


def test_adr_009_has_a_recall_table_per_retriever():
    text = learner(ADR_009, "the retrieval design ADR")
    found = [t for t in tables(text) if t and any("recall_any@1" in cell.lower() for cell in t[0])]
    assert found, "no table with recall_any@1/5/10/20 columns"
    header, *body = found[0]
    for k in evaluate.KS:
        assert any(cell.lower().strip("`") == f"recall_any@{k}" for cell in header), f"no recall_any@{k} column"
    names = [cells[0].strip("`").lower() for cells in body]
    for retriever in evaluate.RETRIEVERS:
        assert retriever in names, f"no row for {retriever}: {names}"
    values = [cell for cells in body for cell in cells[1:]]
    for cell in values:
        assert cell_ok(cell), f"not a number or {AWAITING}: {cell!r}"
    if any(NUMBER.fullmatch(cell) for cell in values):
        assert re.search(DIGEST, text), "a measured recall needs the index digest it came from"


def test_adr_009_has_the_paired_experiment_table():
    text = learner(ADR_009, "the retrieval design ADR")
    found = [t for t in tables(text) if t and {"none", "hybrid"} <= {w for cell in t[0][1:]
                                                                    for w in re.findall(r"[a-z]+", cell.lower())}]
    assert found, "no table with a none column and a hybrid column"
    header, *body = found[0]
    for metric in ("claims_valid", "all_claims_valid", GRADER, "cost"):
        assert [cells for cells in body if metric in cells[0].lower()], f"no table row for {metric}"
    values = []
    for cells in body:
        for cell in cells[1:]:
            assert cell_ok(cell) or (GRADER in cells[0] and cell.lower() == "n/a"), f"not a number: {cell!r}"
            values.append(cell)
    if any(NUMBER.fullmatch(cell) for cell in values):
        assert re.search(RUN_ID, text), "a measured number needs the run id it came from"

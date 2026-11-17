"""The `mode`, `drop`, `guards`, `kind`, `inject` and `thesis_prompt` arm knobs (REPO-PLAN §2.4 week 4, §2.5 week 5,
GUARDS-SPIKE §8.2 week 7), checked at config load, and a guards arm run at $0. tests/test_week4.py runs a tools arm,
tests/test_masking.py two drop arms, tests/test_injection.py the pipeline arm."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from test_guards import make, registry  # noqa: F401
from test_headlines import reply as headline_reply, stored, week, with_news
from test_masking import TICKERS, keyed, pinned_tokens, served, ten, user_turn  # noqa: F401
from test_teacher import context as teacher_context
from test_thesis import ALL, ANALYSIS
from test_week4 import MODEL, context, prices
from tradingresearch import analyze as an, experiment, guards, journal, news, thesis as th
from tradingresearch.retrieval.store import Passage, Retrieved

CONFIG = """name = "modes"
model = "openai/gpt-4.1-nano"
max_usd_per_arm = 0.01
tickers = ["AAPL"]
sessions = ["2026-11-13"]
graders = ["parsed"]

[[arms]]
name = "baseline"
prompt = "analyze-1"
"""


def config(tmp_path: Path, mode: str | None) -> Path:
    path = tmp_path / "modes.toml"
    path.write_text(CONFIG + (f'mode = "{mode}"\n' if mode else ""))
    return path


def test_mode_defaults_to_fixed_and_accepts_tools(tmp_path):
    assert experiment.load(config(tmp_path, None)).arms[0].mode == "fixed"
    assert experiment.load(config(tmp_path, "tools")).arms[0].mode == "tools"


def test_an_unknown_mode_is_refused_at_load(tmp_path):
    path = config(tmp_path, "agentic")
    with pytest.raises(SystemExit, match=r"arm baseline: mode must be one of fixed, tools, not 'agentic'"):
        experiment.load(path)


def with_drop(tmp_path: Path, line: str) -> Path:
    path = tmp_path / "drop.toml"
    path.write_text(CONFIG + line + "\n")
    return path


def test_drop_defaults_to_empty_and_takes_section_names(tmp_path):
    assert experiment.load(config(tmp_path, None)).arms[0].drop == ()
    assert experiment.load(with_drop(tmp_path, "drop = []")).arms[0].drop == ()
    assert experiment.load(with_drop(tmp_path, 'drop = ["edgar", "levels"]')).arms[0].drop == ("edgar", "levels")


@pytest.mark.parametrize(("line", "why"), [
    ('drop = ["news"]', "unknown section(s) news; sections: indicators, levels, edgar, headlines"),
    ('drop = ["headlines"]', "prompt analyze-1 renders no headlines; dropping them needs a prompt that shows them"),
    ('drop = "edgar"', "must be a list of section names"),
    ("drop = [1]", "must be a list of section names"),
    ('drop = ["edgar", "edgar"]', "names a section twice"),
    ('drop = ["indicators", "levels", "edgar"]', "names every section"),
    ('mode = "tools"\ndrop = ["edgar"]', "a tools arm has none"),
])
def test_a_bad_drop_is_refused_at_load(tmp_path, line, why):
    with pytest.raises(SystemExit, match=r"arm baseline: drop.*" + re.escape(why)):
        experiment.load(with_drop(tmp_path, line))


# input_hash values computed at the G14a commit (efb756d), before the guards, injection and dropped joins existed
PINNED = {
    "analyze-1": "sha256:9c6107fbda021092856d181f9bd6e90746cf8db4a77c04eeb55f554304788a2d",
    "analyze-3": "sha256:501764cab5e3bf27ea8abb57e8aea00044349816c67005602172a43347299803",
    "drop-edgar": "sha256:35af00205eab299c56dc95b6b53da4e07f8f3a2796171d64571d86d1e0cf3789",
    "teacher": "sha256:342567c15d797b2023e480e544d661771e4ba76708328f765f9b1e536b2a80e4",
    "retrieval": "sha256:2c064f9dced34bdcb8fa93baf0eb8f30c340385f552d8cc5c646b5ef37ccdc15",
    "headlines": "sha256:ff8c05903109ef356fe9efc0b5a367797ae6d2517e7c5e340d9af48efa4bad10",
    "thesis-swing": "sha256:d1f397f638a6755a115a0420bb3cb8a445c3def9cd7375603249cd5d6b28b671",
    "thesis-playbook": "sha256:b174e021a41ba00878a5cea3df5551955fefa2c9ce72d936a7d69667a8bef2d1",
}
RETRIEVED = Retrieved("FAKEA", date(2026, 11, 13), "bm25", 2, "sha256:" + "a" * 64, "q", "{ticker}",
                      (Passage("ch_1", "sha256:" + "b" * 64, 1.0, "t"),), 0)


def test_input_hashes_without_guards_or_injection_are_unchanged(tmp_path):
    ctx = context()
    found = {
        "analyze-1": an.input_hash(ctx, "analyze-1", guard_ids=(), injection=None, dropped=frozenset()),
        "analyze-3": an.input_hash(ctx, "analyze-3"),
        "drop-edgar": an.input_hash(ctx, "analyze-1", drop=("edgar",)),
        "teacher": an.input_hash(teacher_context(), "analyze-1"),
        "retrieval": an.input_hash(ctx, "analyze-1", retrieval=RETRIEVED),
        "headlines": an.input_hash(with_news(tmp_path), "analyze-3"),
        "thesis-swing": th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=()),
        "thesis-playbook": th.input_hash(ANALYSIS, ALL, "thesis-1", "sha256:" + "0" * 64),
    }
    assert found == PINNED
    joined = {an.input_hash(ctx, "analyze-1", guard_ids=("plain_text",)),
              an.input_hash(ctx, "analyze-1", injection={"id": "x", "sha256": "sha256:" + "c" * 64}),
              an.input_hash(ctx, "analyze-1", dropped=frozenset({"src_x"}))}
    assert len(joined) == 3 and PINNED["analyze-1"] not in joined  # each join is its own input
    assert th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=("plain_text",)) != PINNED["thesis-swing"]


def test_a_guard_rules_version_is_part_of_both_hashes(monkeypatch):
    ctx, ids = context(), ("plain_text",)
    before = (an.input_hash(ctx, "analyze-1", guard_ids=ids), th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=ids))
    monkeypatch.setattr(guards.RULES["plain_text"], "version", "2")  # a rule edit bumps its version
    after = (an.input_hash(ctx, "analyze-1", guard_ids=ids), th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=ids))
    assert before[0] != after[0] and before[1] != after[1]


GUARDED = """name = "guards-pair"
model = "{model}"
max_usd_per_arm = 1.0
tickers = {tickers}
sessions = ["2026-11-13"]
graders = ["parsed", "all_claims_valid", "inferences_grounded"]

[[arms]]
name = "full"
prompt = "analyze-3"

[[arms]]
name = "guarded"
prompt = "{prompt}"
"""


def guarded(tmp_path: Path, lines: str, prompt: str = "analyze-3") -> Path:
    path = tmp_path / "guards.toml"
    path.write_text(GUARDED.format(model=MODEL, tickers=json.dumps(list(TICKERS)), prompt=prompt) + lines + "\n")
    return path


@pytest.fixture
def fake_rules(registry):  # noqa: F811
    guards.rule(make("fakea_fetched", "fetched", "drop"))
    guards.rule(make("fakea_thesis", "thesis", "flag"))


def test_guards_default_to_none_and_take_registered_ids(tmp_path, fake_rules):
    assert experiment.load(guarded(tmp_path, "")).arms[1].guards == ()
    assert experiment.load(guarded(tmp_path, 'guards = ["fakea_fetched"]')).arms[1].guards == ("fakea_fetched",)
    pipeline = experiment.load(guarded(tmp_path, 'kind = "pipeline"\nguards = ["fakea_fetched", "fakea_thesis"]'))
    assert (pipeline.arms[1].kind, pipeline.arms[1].guards) == ("pipeline", ("fakea_fetched", "fakea_thesis"))
    assert pipeline.arms[1].thesis_prompt == th.DEFAULT_PROMPT and pipeline.arms[0].kind == "analyze"


@pytest.mark.parametrize(("lines", "prompt", "why"), [
    ('guards = ["nope"]', "analyze-3", "guards: unknown rule(s) nope; registered:"),
    ('guards = "fakea_fetched"', "analyze-3", "guards must be a list of rule ids"),
    ('guards = ["fakea_fetched", "fakea_fetched"]', "analyze-3", "guards names a rule twice"),
    ('guards = ["thesis_rules"]', "analyze-3", "guards: thesis_rules always runs"),
    ('mode = "tools"\nguards = ["fakea_fetched"]', "analyze-3", "fetched rule(s) fakea_fetched scan headlines"),
    ('drop = ["headlines"]\nguards = ["fakea_fetched"]', "analyze-3", "fetched rule(s) fakea_fetched scan headlines"),
    ('guards = ["fakea_fetched"]', "analyze-1", "fetched rule(s) fakea_fetched scan headlines"),
    ('guards = ["fakea_thesis"]', "analyze-3", "thesis rule(s) fakea_thesis check theses"),
    ('guards = ["plain_text"]', "analyze-3", "thesis rule(s) plain_text check theses"),
    ('kind = "nope"', "analyze-3", "kind must be one of analyze, pipeline"),
    ('kind = "pipeline"\nmode = "tools"', "analyze-3", "a tools arm has none"),
    ("inject = 1", "analyze-3", "inject must be true or false"),
    ("inject = true", "analyze-3", "only a pipeline arm"),
    ('thesis_prompt = "thesis-1"', "analyze-3", "only a pipeline arm"),
    ('kind = "pipeline"\nthesis_prompt = "thesis-2"', "analyze-3", "without the journal's playbook"),
    ('kind = "pipeline"\ninject = true', "analyze-3", "the config names no injections file"),
])
def test_a_bad_guards_kind_or_inject_knob_is_refused_at_load(tmp_path, fake_rules, lines, prompt, why):
    with pytest.raises(SystemExit, match=re.escape(why)):
        experiment.load(guarded(tmp_path, lines, prompt))


@pytest.mark.parametrize("lines", ['guards = ["nope"]', 'mode = "tools"\nguards = ["fakea_fetched"]'])
def test_a_bad_guards_id_or_a_fetched_rule_on_a_tools_arm_exits_before_any_call(tmp_path, fake_rules, lines):
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    with pytest.raises(SystemExit, match="arm guarded: guards"):
        experiment.run_arms(conn, experiment.load(guarded(tmp_path, lines)), ten(), keyed({}, sent), prices(),
                            tmp_path)
    assert sent == []
    assert not (tmp_path / "runs").exists()
    assert conn.execute("SELECT count(*) FROM analysis").fetchone() == (0,)


def test_a_guards_arm_sends_the_guarded_turn_and_audits_and_hashes_the_drop(tmp_path, registry,  # noqa: F811
                                                                          pinned_tokens):  # noqa: F811
    newest = week()[7]  # the latest headline in the window: the one the rule drops
    guards.rule(make("fakea_drop", "fetched", "drop",
                     hits=lambda row: row.kind == "headline" and row.text == newest.headline))
    for ticker in TICKERS:
        stored(tmp_path, ticker)
    cite = news.source_ref(newest).source_id
    contexts = [an.with_headlines(ctx, tmp_path, "analyze-3") for ctx in ten()]
    full_text = [an.render(ctx) for ctx in contexts]
    guarded_text = ["\n".join(line for line in text.split("\n") if not line.startswith(cite)) for text in full_text]
    replies = ({p: served(headline_reply(cite), "Google") for p in full_text}
               | {p: served(headline_reply(cite), "DeepInfra") for p in guarded_text})
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    config = experiment.load(guarded(tmp_path, 'guards = ["fakea_drop"]'))
    full, kept = experiment.run_arms(conn, config, ten(), keyed(replies, sent), prices(), tmp_path)
    assert [user_turn(body) for body in sent] == full_text + guarded_text
    assert [user_turn(body).count("| headline 2026-11-13 ") for body in sent] == [5] * 10 + [4] * 10
    assert experiment.means(full.run)["all_claims_valid"] == (1.0, 10)
    assert experiment.means(kept.run)["all_claims_valid"] == (0.0, 10)  # the claim citing the dropped row

    text = (tmp_path / guards.AUDIT_FILE).read_text()
    audit = [json.loads(line) for line in text.splitlines()]
    assert newest.headline not in text  # the digest only
    assert len(audit) == 10 and {(a["stage"], a["decision"], a["rule"], a["subject"]["kind"], a["subject"]["id"],
                                  a["arm"], tuple(a["guards"]), a["run_id"]) for a in audit} == {
        ("fetched", "drop", "fakea_drop", "headline", cite, "guarded", ("fakea_drop",), kept.run.record.run_id)}
    expected = {an.input_hash(ctx, "analyze-3", guard_ids=("fakea_drop",), dropped=frozenset({cite}))
                for ctx in contexts}
    assert {a["input_hash"] for a in audit} == expected
    rows = conn.execute("SELECT json_extract(body, '$.input_hash'), json_extract(body, '$.provider_route') "
                        "FROM analysis WHERE json_extract(body, '$.run_id') = ?", (kept.run.record.run_id,)).fetchall()
    assert {h for h, _ in rows} == expected and {r for _, r in rows} == {"openrouter:DeepInfra"}
    assert not expected & {an.input_hash(ctx, "analyze-3") for ctx in contexts}


def test_the_guarded_provider_never_sends_a_prompt_it_has_no_view_of():
    wrapper = experiment.Guarded(object(), {"item prompt": "guarded view"})
    assert wrapper.guarded("item prompt") == "guarded view"
    assert wrapper.guarded("guarded view") == "guarded view"  # guarding twice is a no-op
    with pytest.raises(ValueError, match="no guarded view"):
        wrapper.guarded("some other text")

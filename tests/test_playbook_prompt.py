"""The playbook in the thesis-2 prompt (G12c): the PLAYBOOK block and its computed sources, citations checked by code,
thesis-1 byte-identical. No model call: the real adapter answers a recorded reply through an httpx MockTransport."""

import copy
import hashlib
import json
from datetime import UTC, date, datetime

import pytest
from gigai_core import Dataset

from test_daily import TEACHER, TEACHER_ANALYSIS, TEACHER_PRICES, TEACHER_THESIS_REPLY, answering
from test_playbook import add_thesis, conn, wilson  # noqa: F401  (conn is a fixture)
from test_thesis import ALL, ANALYSIS, swing, written
from tradingresearch import analyze as an, journal, playbook, thesis as th
from tradingresearch.hashing import digest

SESSION = date(2026, 11, 16)
CLOSE = datetime(2026, 11, 16, 21, 0, tzinfo=UTC)  # 16:00 New York
SCOPE = "champion theses graded and closed by 2026-11-16"
CLOSING = 'Write the JSON with the keys "theses" and "no_trade".'
# thesis-1 on the recorded AAPL analysis, pinned at f60b629 before thesis-2 existed
THESIS_1_INPUT_HASH = "sha256:d153d1596bdc4eb90c2e9b228f61887886234328eb0209ea5cc0d95f585b92b7"
THESIS_1_PROMPT_SHA = "242a1b3ef1e9f2dd8b3a698c3932f5a9de9d3c04ec0e547a2728ad05c5c4d4f2"
THESIS_1_DATASET_SHA = "6eccce65af67780d90354d1d30d11c47e25b854ccab923e2ea6d323d26ed1a2a"


def stock(conn) -> None:
    """Five closed short breakouts on five sessions (3 wins) and two closed swing pullbacks (thin)."""
    for day, r in zip((2, 3, 4, 5, 6), (1.0, -0.5, 2.0, 1.0, -1.0), strict=True):
        add_thesis(conn, date(2026, 11, day), r_net=r, p1="pass" if r > 0 else "fail")
    for day in (9, 10):
        add_thesis(conn, date(2026, 11, day), horizon="swing", setup="pullback_to_level", r_net=0.5)


def test_a_cell_with_enough_trades_is_a_row_with_a_computed_source(conn):
    stock(conn)
    pb = playbook.compute(conn, SESSION)
    text, [src] = playbook.prompt_block(pb)
    lo, hi = wilson(3, 5)
    short = next(f for f in playbook.as_facts(pb) if f["horizon"] == "short")
    assert (src.kind, src.feed, src.retrieved_at, src.content_sha256) == ("computed", None, CLOSE, digest(short))
    assert src.source_id == "pb_" + digest(short).removeprefix("sha256:")[:16]
    assert src.uri == f"{playbook.SOURCE_URI}?arm=champion&session=2026-11-16&horizon=short&setup_type=breakout_20d"
    assert text.splitlines() == [
        f"PLAYBOOK ({SCOPE}; one row per horizon and setup_type, never pooled; base rates of this system's own "
        "trades, not predictions)",
        "source_id | horizon | setup_type | n closed | win rate [95% Wilson CI] | mean r_net R [95% CI] | "
        "real - shadow | P1 | median MFE / MAE R",
        f"{src.source_id} | short | breakout_20d | 5 | 3/5 = 60.0% [{lo:.1%}, {hi:.1%}] | insufficient (5 sessions "
        "< 10) | no shadow outcome yet | P1 met 3/5 = 60.0%; 0 unknown excluded | +1.00 / -0.50",
        "insufficient (n < 5, no rate shown): swing pullback_to_level n 2",  # no rate, no id to cite
    ]


def test_no_closed_trades_is_one_line_and_no_source(conn):
    assert playbook.prompt_block(playbook.compute(conn, SESSION)) == (f"PLAYBOOK: no closed trades yet ({SCOPE})", [])


def test_the_same_rows_give_the_same_block_and_sources(conn):
    stock(conn)
    assert playbook.prompt_block(playbook.compute(conn, SESSION)) == playbook.prompt_block(
        playbook.compute(conn, SESSION))


def test_thesis_1_is_byte_identical():
    item = th.item_for(ANALYSIS, ALL, "champion")
    assert th.input_hash(ANALYSIS, ALL, "thesis-1") == THESIS_1_INPUT_HASH
    assert hashlib.sha256(item.prompt.encode()).hexdigest() == THESIS_1_PROMPT_SHA
    assert Dataset.of("thesis", [item]).ref.sha256 == THESIS_1_DATASET_SHA
    assert "playbook" not in item.expected and "PLAYBOOK" not in item.prompt
    assert th.call_settings("m").json_schema == th.call_settings("m", "thesis-1").json_schema == th.OUTPUT_SCHEMA


def test_thesis_2_shows_the_block_before_the_closing_line_and_binds_it(conn):
    stock(conn)
    shown = th.playbook_for(conn, ANALYSIS, "thesis-2", None)  # computed from the journal as of the session
    block, sources = shown
    item = th.item_for(ANALYSIS, ALL, "champion", shown)
    assert item.prompt.endswith(f"\n\n{block}\n\n{CLOSING}")
    assert item.prompt.replace(f"\n\n{block}", "") == th.render(ANALYSIS, ALL)
    assert item.expected["playbook"] == [s.source_id for s in sources]
    assert th.input_hash(ANALYSIS, ALL, "thesis-2", digest(block)) != th.input_hash(ANALYSIS, ALL, "thesis-2")
    required = th.call_settings("m", "thesis-2").json_schema["properties"]["theses"]["items"]["required"]
    assert required == [*th.THESIS_ITEM["required"], "playbook"]


def test_a_playbook_is_refused_for_a_prompt_without_the_block(conn):
    assert th.playbook_for(conn, ANALYSIS, "thesis-1", None) is None
    with pytest.raises(ValueError, match="thesis-1 shows no playbook"):
        th.playbook_for(conn, ANALYSIS, "thesis-1", playbook.compute(conn, SESSION))


@pytest.mark.parametrize(("cited", "reason"), [
    (["pb_known"], None),
    ([], None),
    (["pb_known", "pb_made_up"], "unknown_playbook_row"),
])
def test_a_cited_row_must_be_one_the_block_showed(cited, reason):
    checked = th.validate({"theses": [swing(playbook=cited)], "no_trade": []}, ANALYSIS, ("swing",), written(),
                          frozenset({"pb_known"}))
    assert [r.reason for r in checked.rejected] == ([] if reason is None else [reason])
    assert len(checked.theses) == (reason is None)


def test_a_thesis_2_reply_without_the_playbook_field_is_rejected():
    checked = th.validate({"theses": [swing()], "no_trade": []}, ANALYSIS, ("swing",), written(), frozenset())
    assert [r.reason for r in checked.rejected] == ["not_a_thesis"]


def replied(cited: list[str]) -> dict:
    """The recorded DeepSeek thesis reply with each thesis citing `cited` in its playbook field."""
    body = copy.deepcopy(TEACHER_THESIS_REPLY)
    message = body["choices"][0]["message"]
    content = json.loads(message["content"])
    message["content"] = json.dumps({**content, "theses": [{**t, "playbook": cited} for t in content["theses"]]})
    return body


@pytest.mark.parametrize("known", [True, False])
def test_a_thesis_2_call_sends_the_block_and_checks_the_citation(conn, tmp_path, known):
    stock(conn)
    journal.add_analysis(conn, TEACHER_ANALYSIS, [])
    block, [src] = playbook.prompt_block(playbook.compute(conn, SESSION))
    sent: list[dict] = []
    provider = answering(200, replied([src.source_id if known else "pb_made_up"]), sent, TEACHER.routing)
    result = th.thesis(conn, TEACHER_ANALYSIS, provider, asked=ALL, arm="teacher", model=TEACHER.model,
                       max_usd=1.0, prices=TEACHER_PRICES, data_dir=tmp_path, prompt_version="thesis-2",
                       terms=TEACHER.terms_class)
    [request] = sent
    assert request["messages"][0]["content"] == an.system_prompt("thesis-2")
    assert request["messages"][1]["content"] == th.render(TEACHER_ANALYSIS, ALL, block)
    assert "playbook" in json.dumps(request["response_format"])
    if known:
        [t] = result.checked.theses
        assert t.input_hash == th.input_hash(TEACHER_ANALYSIS, ALL, "thesis-2", digest(block))
    else:
        assert result.checked.theses == []
        assert [r.reason for r in result.checked.rejected] == ["unknown_playbook_row"]

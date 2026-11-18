"""Key and token scrubbing (redact.py, GUARDS-SPIKE §5.3, ADR-004 Gaps): the patterns, the configured keys' exact
values, the repo-written trace path, `tr guards scan`, and a grep of tests/fixtures/ for keys and real headlines.

Every key here is invented and built at run time, so no file in the repo holds a key-shaped string."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from gigai_core import CoreModel

from test_week4 import LIVE_CONTEXT_TOKENS, MODEL, PROMPT, context, prices, replaying
from tradingresearch import analyze as an, experiment, guards, journal, redact
from tradingresearch.cli import main
from tradingresearch.config import Secret, Settings

FIXTURES = Path(__file__).parent / "fixtures"
OR_KEY = "sk-or-v1-" + "0f" * 32  # an OpenRouter key's shape: the prefix and 64 hex
ANT_KEY = "sk-ant-api03-" + "Fa_k3-" * 15
KEY_ID = "PK" + "FAKEA0123456789XYZ"  # an Alpaca key id's shape: PK and 18 upper-case letters or digits
ALPACA_SECRET = "FakeA" + "s3cr3t" * 6  # an Alpaca secret has no prefix: only the configured value catches it
# OpenRouter's error body as `_post` reads it (a 200 with an error object, code 401), here echoing the key: the worst
# case, the text `OpenRouterError` carries into `str(exc)` and so into a span's CallError message
ERROR_401 = json.dumps({"error": {"code": 401, "message": f"FAKEA: no user for key {OR_KEY}"}})
# a real headline row as analyze-3 renders it; the invented FAKEA rows use the source `fakewire`
HEADLINE_ROW = re.compile(r"headline \d{4}-\d{2}-\d{2} \d{2}:\d{2}Z (?!fakewire\b)[A-Za-z0-9.-]+")


@pytest.fixture(autouse=True)
def no_configured_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path / "data"))
    yield
    redact.forget()


# ---------- the patterns ----------

@pytest.mark.parametrize(("text", "name", "secret"), [
    (f"auth failed for {OR_KEY}.", "sk_or_key", OR_KEY),
    (f"cut at 300: ...{OR_KEY[:20]}", "sk_or_key", OR_KEY[:20]),
    (f"x-api-key: {ANT_KEY}", "sk_ant_key", ANT_KEY),
    (f'{{"Authorization": "Bearer {OR_KEY[9:]}"}}', "bearer_token", OR_KEY[9:]),
    (f"APCA-API-SECRET-KEY: {ALPACA_SECRET}", "apca_header", ALPACA_SECRET),
    (f'{{"APCA-API-KEY-ID": "{KEY_ID}"}}', "apca_header", KEY_ID),
    (f"APCA_API_SECRET_KEY={ALPACA_SECRET}", "apca_header", ALPACA_SECRET),
    (f"key id {KEY_ID} rejected", "pk_key_id", KEY_ID),
    (f"rejected\n{KEY_ID} at the start of a line", "pk_key_id", KEY_ID),
    (f"repr: 'rejected\\n{KEY_ID}'", "pk_key_id", KEY_ID),  # after an escaped newline in a non-JSON log line
    (f"Bearer\n{OR_KEY[9:]}", "bearer_token", OR_KEY[9:]),
    (f'"Authorization":\n"Bearer {OR_KEY[9:]}"', "bearer_token", OR_KEY[9:]),
    (f'header {{"APCA-API-SECRET-KEY": "{ALPACA_SECRET}"}} sent', "apca_header", ALPACA_SECRET),
    ("x-api-key: plain-value-of-any-shape", "x_api_key_header", "plain-value-of-any-shape"),
    ("OPENAI_KEY=sk-proj-" + "Fa_k3" * 8, "sk_proj_key", "sk-proj-" + "Fa_k3" * 8),
], ids=["openrouter", "openrouter_cut", "anthropic", "bearer", "alpaca_header", "alpaca_header_json", "alpaca_env",
        "alpaca_key_id", "alpaca_key_id_line_start", "alpaca_key_id_escaped_newline", "bearer_newline",
        "bearer_line_start", "alpaca_header_quoted_json", "x_api_key", "openai_project"])
def test_each_pattern_replaces_the_key_with_its_name(text, name, secret):
    clean, names = redact.scrubbed(text)
    assert secret not in clean and redact.marker(name) in clean
    assert names == [name]


@pytest.mark.parametrize("text", [
    'src_0123456789abcdef | headline 2026-11-13 12:40Z fakewire | "FakeA Corp unveils robots" | -',
    "sha256:" + "0f" * 32,
    "the bearer of bad news",
    "OpenRouter 402: insufficient credits",
    "PKG and AKA are words",
    "the task-ant-colony and risk-or-v1-0abc",  # no left boundary: not a key
    "bearer bond-equivalent-yield-curve, Bearer counterintelligence",  # no digit: not a token
])
def test_ordinary_text_is_left_alone(text):
    assert redact.scrubbed(text) == (text, [])


def test_a_configured_key_is_caught_by_its_exact_value_and_named_by_its_field():
    cfg = Settings(data_dir=Path("data"), alpaca_key_id=Secret(KEY_ID), alpaca_secret=Secret(ALPACA_SECRET),
                   openrouter_key=Secret(""), sec_user_agent="FakeA research fakea@example.com", feed="sip")
    assert redact.scrub(f"secret {ALPACA_SECRET} sent") == f"secret {ALPACA_SECRET} sent", "no pattern knows it"
    redact.configure(cfg)
    assert redact.scrubbed(f"secret {ALPACA_SECRET} sent") == ("secret [REDACTED:alpaca_secret] sent",
                                                               ["alpaca_secret"])
    assert redact.scrub(KEY_ID) == "[REDACTED:alpaca_key_id]", "the field's name, ahead of the pattern's"
    assert redact.scrubbed(f"APCA-API-SECRET-KEY: {ALPACA_SECRET}") == (
        "APCA-API-SECRET-KEY: [REDACTED:alpaca_secret]", ["alpaca_secret"]), "a marker is not matched again"


def test_a_key_after_bearer_is_one_hit_named_by_its_pattern():
    assert redact.scrubbed(f"Authorization: Bearer {OR_KEY}") == ("Authorization: Bearer [REDACTED:sk_or_key]",
                                                                  ["sk_or_key"])


def test_a_short_configured_value_is_not_matched():
    redact.remember("openrouter_key", "abc")
    assert redact.scrub("abc abc") == "abc abc"


# ---------- the FAKEA 401 error text, through redact directly ----------

def test_the_401_error_body_keeps_its_message_and_loses_the_key():
    clean = redact.scrub(ERROR_401)
    assert OR_KEY not in clean and "sk-or-v1-" not in clean
    assert json.loads(clean)["error"] == {"code": 401, "message": "FAKEA: no user for key [REDACTED:sk_or_key]"}
    assert redact.clip(ERROR_401) == clean


def test_clip_scrubs_before_the_cut_so_no_part_of_a_key_survives():
    body = "x" * (redact.CLIP - 30) + f" key {OR_KEY} tail"
    assert OR_KEY[:24] in body[:redact.CLIP], "the provider's plain cut keeps a key fragment"
    clipped = redact.clip(body)
    assert len(clipped) == redact.CLIP and "0f0f" not in clipped and "sk-or" not in clipped


# ---------- records: string values and dict keys, decoded ----------

class Held(CoreModel):
    text: str
    parsed: dict[str, Any] | None = None


def test_a_record_is_scrubbed_by_its_decoded_strings_so_a_key_after_a_newline_is_caught():
    text = f"reply\n{KEY_ID} rejected\nBearer abcDEF0123456789ghiJKL"
    clean, names = redact.model(Held(text=text))
    assert clean.text == "reply\n[REDACTED:pk_key_id] rejected\n[REDACTED:bearer_token]"
    assert sorted(names) == ["bearer_token", "pk_key_id"]


def test_a_dict_keyed_by_a_header_keeps_its_keys_and_rebuilds_a_valid_record():
    record = Held(text="ok", parsed={"APCA-API-KEY-ID": KEY_ID, "APCA-API-SECRET-KEY": ALPACA_SECRET,
                                     "x-api-key": "plain-value-of-any-shape", "nested": [{"note": OR_KEY}]})
    clean, names = redact.model(record)
    assert clean.parsed == {"APCA-API-KEY-ID": "[REDACTED:pk_key_id]", "APCA-API-SECRET-KEY": "[REDACTED:apca_header]",
                            "x-api-key": "[REDACTED:x_api_key_header]", "nested": [{"note": "[REDACTED:sk_or_key]"}]}
    assert sorted(names) == ["apca_header", "pk_key_id", "sk_or_key", "x_api_key_header"]
    assert redact.model(clean) == (clean, []), "a scrubbed record has nothing left to scrub"


def test_scan_reads_a_json_line_by_its_decoded_strings(tmp_path):
    span = json.dumps({"text": f"reply\n{KEY_ID} rejected\nBearer abcDEF0123456789ghiJKL",
                       "result": {"APCA-API-SECRET-KEY": ALPACA_SECRET}})
    assert "\\n" in span and ALPACA_SECRET in span
    (tmp_path / "run.jsonl").write_text(span + "\n")
    _, hits = redact.scan(tmp_path)
    assert [(name, count) for _, _, name, count in hits] == [("apca_header", 1), ("bearer_token", 1),
                                                             ("pk_key_id", 1)]


# ---------- the repo-written trace path (experiment.run_items) ----------

TOOLS_ARM = f"""name = "redact-fakea"
model = "{MODEL}"
max_usd_per_arm = 1.0
tickers = ["FAKEA", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO"]
sessions = ["2026-11-13"]
graders = ["parsed"]

[[arms]]
name = "tools"
prompt = "{PROMPT}"
mode = "tools"
"""


def test_a_key_in_a_provider_error_never_reaches_the_trace_or_the_run(tmp_path, monkeypatch):
    """The unwired adapter carries the key into the span's error; the trace sink and the sample scrub take it out,
    and one audit line names the pattern, never the key."""
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: LIVE_CONTEXT_TOKENS)
    config_path = tmp_path / "redact.toml"
    config_path.write_text(TOOLS_ARM)
    data = tmp_path / "data"
    conn = journal.connect(data / "journal.db")
    [result] = experiment.run_arms(conn, experiment.load(config_path), [context()],
                                   replaying([json.loads(ERROR_401)], []), prices(), data)
    [sample] = result.run.samples
    assert sample.outcome == "failed" and sample.error.message == "OpenRouter 401: FAKEA: no user for key " \
                                                                  "[REDACTED:sk_or_key]"
    trace = Path(result.run.record.trace_path).read_text()
    assert OR_KEY not in trace and trace.count("[REDACTED:sk_or_key]") == 2, "the model span and the trial span"
    assert all(OR_KEY not in path.read_text(errors="replace") for path in data.rglob("*") if path.is_file())
    records, bad = guards.read_audit(data)
    assert bad == 0 and [(r.stage, r.decision, r.rule, r.subject.kind) for r in records] == [
        ("redact", "redact", "sk_or_key", "span")] * 2
    assert all(r.run_id == result.run.record.run_id and r.arm == "tools" and "hit" in r.detail for r in records)


# ---------- tr guards scan ----------

def test_scan_names_the_file_line_and_pattern_and_exits_1(tmp_path, capsys):
    root = tmp_path / "logs"
    (root / "traces").mkdir(parents=True)
    (root / "traces" / "run_x.jsonl").write_text(f"clean line\n{ERROR_401}\n")
    (root / "notes.txt").write_text("nothing here\n")
    with pytest.raises(SystemExit) as exit_:
        main(["guards", "scan", "--dir", str(root)])
    out = capsys.readouterr().out
    assert exit_.value.code == 1 and OR_KEY not in out
    assert out.splitlines()[0].startswith(f"key scan {root}: 2 file(s), 1 hit(s)")
    assert re.search(r"traces/run_x\.jsonl\s+2\s+sk_or_key\s+1", out)


def test_scan_of_a_clean_directory_reports_0_hits(tmp_path, capsys):
    root = tmp_path / "clean"
    root.mkdir()
    (root / "a.jsonl").write_text(ERROR_401.replace(OR_KEY, "[REDACTED:sk_or_key]") + "\n")
    main(["guards", "scan", "--dir", str(root)])
    assert capsys.readouterr().out == (f"key scan {root}: 1 file(s), 0 hit(s) (patterns "
                                       f"{', '.join(redact.PATTERNS)}, and the configured keys by exact value)\n")


def test_scan_refuses_a_missing_directory_rather_than_report_0(tmp_path):
    with pytest.raises(SystemExit, match="is not a directory"):
        main(["guards", "scan", "--dir", str(tmp_path / "absent")])


def test_scan_help(monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "80")
    with pytest.raises(SystemExit):
        main(["guards", "scan", "--help"])
    assert "usage: tr guards scan [-h] [--dir DIR]" in capsys.readouterr().out


# ---------- the fixtures (GUARDS-SPIKE §9 decision 5) ----------

def test_no_fixture_holds_a_key_or_a_real_headline_row():
    """Fetched content stays out of the repo: a recorded fixture keeps invented FAKEA rows only."""
    files, hits = redact.scan(FIXTURES)
    assert files > 0 and hits == []
    rows = [f"{path.relative_to(FIXTURES)}:{number}" for path in sorted(FIXTURES.rglob("*")) if path.is_file()
            for number, line in redact.lines(path) if HEADLINE_ROW.search(line)]
    assert rows == []

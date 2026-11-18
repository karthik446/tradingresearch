"""The batch judge (`tr grade --judge --batch` / `--collect`, G15-SPIKE §1.3) on fake HTTP only: the batch body is the
sync body under the normal slug, custom_ids are checked before any request, an empty key exits 2 before grading,
results map by custom_id in any order, an entry without a custom_id is skipped, an error entry is a failed call, a
collected answer stores what the sync judge stores, and the derived cost is reconciled against the batch's own
`usage.cost`. Nothing here reaches OpenRouter; what only a paid run shows is in docs/providers.md, "Batch judge"."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import httpx
import pytest
from gigai_core import CallSettings
from gigai_core.budget import Price
from gigai_core.providers import ModelRequest, Turn, request_sha256

from test_grade import D1, Bars, settle
from test_week3 import MODEL, alpaca_daily, closed, load, recorded_verdict, written
from tradingresearch import grade, journal, providers, trace
from tradingresearch.cli import main
from tradingresearch.commands import grade as grade_command
from tradingresearch.providers import openrouter

BATCH_ID = "batch_test_1"
BATCH_PRICE = Price(model=f"{MODEL}:batch", prompt_usd_per_token=0.000001, completion_usd_per_token=0.000005,
                    fetched_at=datetime(2026, 11, 17, tzinfo=UTC), source=f"{openrouter.API}/models")
USAGE = load("judge_reply")["usage"]
CLIENT = httpx.Client  # the real class: a second Fake in one test must not wrap the first one's
DERIVED = USAGE["prompt_tokens"] * 0.000001 + USAGE["completion_tokens"] * 0.000005  # 0.002193


def models() -> dict:
    """The recorded /models list plus the judge's `:batch` row at half the sync price."""
    listing = load("models")
    row = copy.deepcopy(listing["data"][0])
    row["id"], row["pricing"]["prompt"], row["pricing"]["completion"] = f"{MODEL}:batch", "0.000001", "0.000005"
    listing["data"].append(row)
    return listing


def answered(custom_id: str) -> dict:
    return {"id": f"req_{custom_id}", "custom_id": custom_id, "error": None,
            "response": {"status_code": 200, "request_id": "r1", "body": load("judge_reply")}}


def refused(custom_id: str) -> dict:
    return {"id": f"req_{custom_id}", "custom_id": custom_id, "response": None,
            "error": {"type": "invalid_request_error", "message": "max_tokens is greater than the model limit",
                      "param": "max_tokens", "error_type": "invalid_request"}}


def completed(results: list[dict], cost: float | None) -> dict:
    return {"id": BATCH_ID, "object": "batch", "status": "completed", "provider": "OpenAI",
            "request_counts": {"total": len(results)}, "results": results, "error": None,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cost": cost, "is_byok": False}}


class Fake:
    """Every httpx client answers from here: Alpaca daily bars, /models, the sync judge reply, POST /batches (202)
    and GET /batches/{id} (`self.batch`). `requests` logs every request; `submitted` and `sent` keep the bodies."""

    def __init__(self, monkeypatch) -> None:
        self.requests: list[str] = []
        self.submitted: list[dict] = []
        self.sent: list[dict] = []
        self.batch: dict = {"id": BATCH_ID, "status": "in_progress", "results": None}
        transport = httpx.MockTransport(self.handle)
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: CLIENT(*a, **(k | {"transport": transport})))
        monkeypatch.setattr(httpx, "get", lambda url, **k: CLIENT(transport=transport).get(url, **k))

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.requests.append(f"{request.method} {url.host}{url.path}")
        if (url.host, url.path) == ("data.alpaca.markets", "/v2/stocks/bars"):
            return httpx.Response(200, json=alpaca_daily(url.params))
        if (url.host, url.path) == ("openrouter.ai", "/api/v1/models"):
            return httpx.Response(200, json=models())
        if (url.host, url.path) == ("openrouter.ai", "/api/v1/chat/completions"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json=load("judge_reply"))
        if (request.method, url.host, url.path) == ("POST", "openrouter.ai", "/api/v1/batches"):
            self.submitted.append(json.loads(request.content))
            return httpx.Response(202, json={"id": BATCH_ID, "status": "validating", "results": None})
        if (request.method, url.host, url.path) == ("GET", "openrouter.ai", f"/api/v1/batches/{BATCH_ID}"):
            return httpx.Response(200, json=self.batch)
        raise AssertionError(f"unexpected request {request.method} {url}")


def workspace(tmp_path, monkeypatch, key: str = "not-a-real-key", filled: bool = False):
    """A data dir holding the closed, graded, unjudged FAKEA thesis (`filled`: filled on D1, open and not graded), with
    keys in an env file: (thesis, fake)."""
    keys = tmp_path / "keys.env"
    keys.write_text(f"OPENROUTER_API_KEY={key}\nAPCA_API_KEY_ID=not-a-real-id\nAPCA_API_SECRET_KEY=not-a-real-secret\n")
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(keys))
    conn = journal.connect(tmp_path / "journal.db")
    if filled:
        t = written(conn)
        settle(conn, Bars(), D1)
    else:
        t, _ = closed(conn)
    conn.close()
    return t, Fake(monkeypatch)


def judge_record(tmp_path, thesis_id: str):
    """The thesis's judge verdict row and its ScoreRecord, or (None, None)."""
    conn = journal.connect(tmp_path / "journal.db")
    try:
        verdict = journal.judge_verdict(conn, thesis_id)
        records = [r for r in journal.scores_for(conn, thesis_id) if r.judge_model]
    finally:
        conn.close()
    return verdict, (records[0] if records else None)


def request_for(item_id: str, prompt: str = "judge this") -> ModelRequest:
    return ModelRequest(settings=CallSettings(model=MODEL, max_output_tokens=4000),
                        turns=(Turn(role="user", content=prompt),), metadata={"item_id": item_id, "repeat_index": 0})


# ---------- submit ----------

def test_the_batch_body_is_the_sync_body_under_the_normal_slug_and_stores_nothing(tmp_path, monkeypatch, capsys):
    t, fake = workspace(tmp_path, monkeypatch)
    main(["grade", "--judge", "--batch"])
    out = capsys.readouterr().out
    [batch] = fake.submitted
    assert batch["model"] == MODEL and batch["endpoint"] == "/v1/chat/completions"  # no `:batch` on the wire
    [entry] = batch["requests"]
    assert entry["custom_id"] == t.thesis_id and BATCH_ID in out and fake.sent == []
    assert judge_record(tmp_path, t.thesis_id) == (None, None)  # nothing stored before --collect
    record = json.loads((tmp_path / "batches" / f"{BATCH_ID}.json").read_text())
    assert list(record["items"]) == [t.thesis_id] and record["model"] == MODEL and "not-a-real-key" not in str(record)
    main(["grade", "--judge"])  # the sync judge on the same thesis: its body is the batch entry's body
    assert fake.sent == [entry["body"]]


@pytest.mark.parametrize("ids", [["th_ok", "th.dot"], ["th_ok", "th_ok"], ["x" * 65], []])
def test_a_bad_repeated_or_missing_custom_id_is_refused_before_any_request(ids, monkeypatch):
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(202, json={"id": "b"}))
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: CLIENT(*a, **(k | {"transport": transport})))
    with pytest.raises(ValueError, match="custom_id"):
        openrouter.submit_batch("not-a-real-key", MODEL, [request_for(i) for i in ids])
    assert seen == []


@pytest.mark.parametrize("flag", [["--batch"], ["--collect", BATCH_ID]])
def test_an_empty_key_exits_2_naming_the_variable_before_any_request(flag, tmp_path, monkeypatch, capsys):
    _, fake = workspace(tmp_path, monkeypatch, key="")
    with pytest.raises(SystemExit) as exc:
        main(["grade", "--judge", *flag])
    assert exc.value.code == 2 and "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert fake.requests == []


@pytest.mark.parametrize("flag", [["--batch"], ["--collect", BATCH_ID]])
def test_an_empty_key_exits_2_before_grading_a_filled_thesis(flag, tmp_path, monkeypatch, capsys):
    """A filled thesis makes `grade.run` open the Alpaca client and write a grade; the key check comes before both."""
    t, fake = workspace(tmp_path, monkeypatch, key="", filled=True)
    conn = journal.connect(tmp_path / "journal.db")
    assert [(u.thesis_id, state) for u, state in journal.ungraded_theses(conn)] == [(t.thesis_id, "OPEN")]
    conn.close()

    def no_alpaca(cfg):
        raise AssertionError("the Alpaca client was opened before the key check")

    monkeypatch.setattr(grade_command, "alpaca_client", no_alpaca)
    with pytest.raises(SystemExit) as exc:
        main(["grade", "--judge", *flag])
    assert exc.value.code == 2 and "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert fake.requests == []
    conn = journal.connect(tmp_path / "journal.db")
    assert [u.thesis_id for u, _ in journal.ungraded_theses(conn)] == [t.thesis_id]  # no grade written
    conn.close()


# ---------- replay ----------

def test_results_map_by_custom_id_in_any_order_and_failures_raise():
    prompts = {"th_a": "judge a", "th_b": "judge b", "th_c": "judge c"}
    digests = {i: request_sha256(request_for(i, p)) for i, p in prompts.items()}
    replay = providers.BatchReplay([refused("th_b"), answered("th_a")], BATCH_PRICE, digests)  # unordered
    result = replay.invoke(request_for("th_a", "judge a"))
    assert result.text == load("judge_reply")["choices"][0]["message"]["content"]
    assert result.cost_status == "derived" and result.cost_usd == pytest.approx(DERIVED)
    assert result.usage.input_tokens == USAGE["prompt_tokens"]
    with pytest.raises(providers.BatchEntryFailed, match="invalid_request_error"):
        replay.invoke(request_for("th_b", "judge b"))
    with pytest.raises(providers.BatchEntryFailed, match="no result"):
        replay.invoke(request_for("th_c", "judge c"))
    with pytest.raises(providers.BatchEntryFailed, match="not the one submitted"):
        replay.invoke(request_for("th_a", "a prompt edited since submit"))


def test_an_entry_without_a_custom_id_is_skipped_and_the_good_ones_still_answer():
    digests = {i: request_sha256(request_for(i, f"judge {i}")) for i in ("th_a", "th_b")}
    malformed = {"id": "req_lost", "error": {"type": "server_error", "message": "lost"}, "response": None}
    replay = providers.BatchReplay([answered("th_a"), malformed, answered("th_b")], BATCH_PRICE, digests)
    for i in ("th_a", "th_b"):
        assert replay.invoke(request_for(i, f"judge {i}")).cost_usd == pytest.approx(DERIVED)


def test_collect_with_a_malformed_entry_still_stores_the_good_one(tmp_path, monkeypatch, capsys):
    t, fake = workspace(tmp_path, monkeypatch)
    main(["grade", "--judge", "--batch"])
    malformed = {"id": "req_lost", "error": {"type": "server_error", "message": "lost"}, "response": None}
    fake.batch = completed([malformed, answered(t.thesis_id)], cost=round(DERIVED, 6))
    main(["grade", "--judge", "--collect", BATCH_ID])  # costs agree: no SystemExit
    out = capsys.readouterr().out
    assert judge_record(tmp_path, t.thesis_id)[0] is not None, out


def test_a_collected_answer_stores_what_the_sync_judge_stores(tmp_path, monkeypatch, capsys):
    """Same rubric digest, model, kind, value, explanation and verdict as a sync judge of the same thesis; the run
    file carries the derived `:batch` cost and the two sums agree."""
    sync_dir, batch_dir = tmp_path / "sync", tmp_path / "batch"
    sync_dir.mkdir(), batch_dir.mkdir()
    synced, _ = workspace(sync_dir, monkeypatch)
    main(["grade", "--judge"])
    sync_verdict, sync_record = judge_record(sync_dir, synced.thesis_id)
    t, fake = workspace(batch_dir, monkeypatch)
    main(["grade", "--judge", "--batch"])
    fake.batch = completed([answered(t.thesis_id)], cost=round(DERIVED, 6))
    before = grade.run_files(batch_dir)
    capsys.readouterr()
    main(["grade", "--judge", "--collect", BATCH_ID])  # costs agree: no SystemExit
    out = capsys.readouterr().out
    verdict, record = judge_record(batch_dir, t.thesis_id)
    assert verdict is not None, out
    assert (verdict["verdict"], verdict["reason"]) == (sync_verdict["verdict"], sync_verdict["reason"])
    assert verdict["verdict"] == recorded_verdict()[0]
    fields = ("grader_id", "grader_version", "kind", "value", "explanation", "judge_model", "judge_prompt_sha256")
    assert {f: getattr(record, f) for f in fields} == {f: getattr(sync_record, f) for f in fields}
    [run] = grade.run_files(batch_dir) - before
    assert trace.header(run).spent_usd == pytest.approx(DERIVED, abs=1e-6)
    assert f"${DERIVED:.6f}" in out and fake.sent == []
    main(["grade", "--judge", "--collect", BATCH_ID])  # already stored: a second collect stores nothing new
    assert len([r for r in journal.scores_for(journal.connect(batch_dir / "journal.db"), t.thesis_id)
                if r.judge_model]) == 1


def test_an_error_entry_is_a_failed_call_and_stores_nothing(tmp_path, monkeypatch, capsys):
    t, fake = workspace(tmp_path, monkeypatch)
    main(["grade", "--judge", "--batch"])
    fake.batch = completed([refused(t.thesis_id)], cost=0.0)
    main(["grade", "--judge", "--collect", BATCH_ID])
    assert "batch_entry_failed" in capsys.readouterr().out
    assert judge_record(tmp_path, t.thesis_id) == (None, None)


# ---------- polling and cost ----------

@pytest.mark.parametrize(("batch", "code", "said"), [
    ({"id": BATCH_ID, "status": "in_progress", "results": None}, 0, "still in_progress"),
    ({"id": BATCH_ID, "status": "completed", "results": None}, 0, "still completed"),
    ({"id": BATCH_ID, "status": "failed", "results": None, "error": {"message": "upstream gone"}}, 1, "upstream gone"),
    ({"id": BATCH_ID, "status": "expired", "results": None}, 1, "expired"),
])
def test_collect_before_the_end_says_still_and_a_failed_batch_exits_1(batch, code, said, tmp_path, monkeypatch,
                                                                      capsys):
    t, fake = workspace(tmp_path, monkeypatch)
    main(["grade", "--judge", "--batch"])
    fake.batch = batch
    if code:
        with pytest.raises(SystemExit) as exc:
            main(["grade", "--judge", "--collect", BATCH_ID])
        assert exc.value.code == code
    else:
        main(["grade", "--judge", "--collect", BATCH_ID])
    assert said in capsys.readouterr().out
    assert judge_record(tmp_path, t.thesis_id) == (None, None)


def test_a_derived_cost_off_the_batch_usage_cost_exits_1(tmp_path, monkeypatch, capsys):
    t, fake = workspace(tmp_path, monkeypatch)
    main(["grade", "--judge", "--batch"])
    fake.batch = completed([answered(t.thesis_id)], cost=DERIVED + 0.002)
    with pytest.raises(SystemExit) as exc:
        main(["grade", "--judge", "--collect", BATCH_ID])
    assert exc.value.code == 1 and "differ by more than $0.001" in capsys.readouterr().out
    assert judge_record(tmp_path, t.thesis_id)[0] is not None  # the verdict is kept; the cost line flags the gap

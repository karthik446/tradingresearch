"""w3l3.1 keep the run file: the judge's one call lands in data_dir/runs, and a failed call says so and names it.

The closed FAKEA trade through the real adapter, replayed (tools/fakea.py). `recorded` is the real reply; `failed` is an
HTTP 400, a rejected request, and `credits` an HTTP 402, an account out of credits: no reply, nothing to read. Reading
the verdict and storing it is w3l3.2: until then p1_judge stops with NotImplementedError after the run file is kept,
which these checks allow.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

COST = fakea.load("judge_reply")["usage"]["cost"]  # what the recorded reply cost: $0.0051635


def files_under(data_dir: Path) -> list[str]:
    return [fakea.masked(str(p.relative_to(data_dir))) for p in sorted(data_dir.rglob("*")) if p.is_file()]


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> fakea.Judging:
    return fakea.judging(tmp_path_factory.mktemp("w3l3_1_recorded"))


@pytest.fixture(scope="module")
def failed(tmp_path_factory) -> fakea.Judging:
    return fakea.judging(tmp_path_factory.mktemp("w3l3_1_failed"), replies=("failed",))


def test_the_call_lands_in_one_run_file_with_its_cost(recorded):
    files = fakea.run_files(recorded.data_dir)
    assert len(recorded.sent) == 1, (
        f"p1_judge sent {len(recorded.sent)} requests on the closed FAKEA trade, expected 1 (w3l2's one call); it "
        f"ended with {fakea.shown(recorded.got)}"
    )
    assert files, (
        f"After the judge's one call, data_dir/runs holds no run file. The call cost ${COST:.6f}, and `tr usage` and "
        f"`tr grade --judge` read what a call cost from its run file only. Files under data_dir: "
        f"{', '.join(files_under(recorded.data_dir))}"
    )
    assert len(files) == 1, f"One call left {len(files)} run files under data_dir/runs, expected 1"
    assert abs(fakea.spent(files[0]) - COST) < 1e-6, (
        f"The run file says the call spent ${fakea.spent(files[0]):.6f}; the reply cost ${COST:.6f}"
    )


def test_a_failed_call_is_cannot_grade_naming_its_run_file(failed):
    from tradingresearch.evals import CannotGrade

    got = failed.got
    assert len(failed.sent) == 1, f"p1_judge sent {len(failed.sent)} requests, expected 1"
    assert isinstance(got, CannotGrade), (
        f"The judge's request was rejected (HTTP 400, no reply to read) and p1_judge ended with {fakea.shown(got)}. A "
        f"call that failed cannot grade the thesis: that is CannotGrade, which `tr grade --judge` reports on the "
        f"thesis while it goes on with the next one."
    )
    assert failed.raised, (
        f"p1_judge returned {fakea.shown(got)} instead of raising it. A returned CannotGrade is a value: the caller "
        f"(`tr grade --judge`) never sees it as an error and reads it as the thesis's result."
    )
    files = fakea.run_files(failed.data_dir)
    assert files, (
        f"The failed call left no run file under data_dir/runs (files: {', '.join(files_under(failed.data_dir))}): a "
        f"failed call is still a call, and a failed reply can still be paid; its run file is the record of it."
    )
    assert str(files[0]) in str(got), (
        f"CannotGrade says {fakea.shown(got)!r}: it should name the run file the failed call is in "
        f"({fakea.masked(str(files[0]))}), so whoever reads the error can open it."
    )
    assert "http_400" in str(got), (
        f"CannotGrade says {fakea.shown(got)!r}: it should name the error the run recorded for the call (http_400), "
        f"not only that it failed."
    )
    verdict, scores = fakea.stored(failed.conn, failed.thesis.thesis_id)
    assert verdict is None and not scores, (
        f"After the failed call the journal holds verdict {None if verdict is None else verdict['verdict']!r} and "
        f"{len(scores)} p1_judge ScoreRecord(s). There was no reply, so there is no verdict: a stored fail would grade "
        f"the thesis on an outage."
    )


def test_cannot_grade_names_the_code_this_run_recorded(tmp_path):
    from tradingresearch.evals import CannotGrade

    j = fakea.judging(tmp_path, replies=("credits",))
    files = fakea.run_files(j.data_dir)
    assert isinstance(j.got, CannotGrade) and files, f"On an HTTP 402 reply p1_judge ended with {fakea.shown(j.got)}"
    assert "insufficient_credits" in str(j.got), (
        f"On an HTTP 402 (out of credits) CannotGrade says {fakea.shown(j.got)!r}. It should name the error code this "
        f"run recorded for the call (insufficient_credits, in its run file), not a code written into the message."
    )

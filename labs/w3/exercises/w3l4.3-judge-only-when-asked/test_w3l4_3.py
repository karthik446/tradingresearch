"""w3l4.3 judge only when asked: `tr grade` makes no model call, `tr grade --judge` judges once and prints what it cost.

The CLI itself (`tr`, as tests/test_week3.py runs it) on a journal of two closed, graded FAKEA theses, a champion then a
challenger (tools/fakea.py `journal_of`), with fake keys and every HTTP request answered in-process (`fakea.cli`): the
Alpaca daily bars, the recorded /models row, and judge request i gets reply i. Each run reads the journal the run before
it left. One check records the order `tr grade --judge` grades and judges in. The last check calls grade.render_judged
on made-up outcomes and costs.
"""

import contextlib
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

PAID = "$0.005163"  # one reply's cost, as its run file has it (the recorded usage.cost is $0.0051635)


def costs(line: str) -> list[str]:
    """The dollar amounts a line prints, each whole: `$0.0051635` is not `$0.005163`."""
    return re.findall(r"\$\d+\.\d+", line)


def judge_part(out: str) -> list[str]:
    """What the judge part printed: a line per thesis (it names the thesis id) and the line starting `judge`."""
    return [line for line in out.splitlines() if "th_" in line or line.startswith("judge")]


def shown(out: str) -> str:
    return " | ".join(fakea.masked(line)[:110] for line in judge_part(out)) or "(no judge line)"


def journal(data_dir: Path) -> tuple[list[str], list[str]]:
    """Two closed, graded theses waiting for the judge: the `tr grade` argv for the session they closed in, and their
    ids (champion first)."""
    conn, theses, _ = fakea.journal_of(data_dir, ("champion", "challenger"))
    conn.close()
    return ["grade", "--session", fakea.SESSION], [t.thesis_id for t in theses]


def test_tr_grade_calls_the_judge_only_with_judge(tmp_path, monkeypatch):
    grade, _ = journal(tmp_path)
    capped = [*grade, "--judge-max-usd", "0.5"]  # not the default $0.25, so a changed cap is a cap that was given
    (plain, n_plain), (cap, n_cap), (dry, n_dry), (judge_dry, n_judge_dry) = fakea.cli(
        monkeypatch, tmp_path, [grade, capped, [*grade, "--dry-run"], [*grade, "--judge", "--dry-run"]])
    for argv, out, sent in (("tr grade", plain, n_plain), ("tr grade --judge-max-usd 0.5", cap, n_cap),
                            ("tr grade --dry-run", dry, n_dry)):
        assert sent == 0 and not judge_part(out), (
            f"`{argv}` sent {sent} judge request(s) and printed: {shown(out)}. The judge is the one paid step of tr "
            f"grade: it runs only with --judge (ADR-003: off by default), and without it there is nothing to show. "
            f"--judge-max-usd only sets the cap of a judge run; given alone, it asks for none."
        )
    assert n_judge_dry == 0 and "would judge 2" in judge_dry, (
        f"`tr grade --judge --dry-run` sent {n_judge_dry} request(s) and printed: {shown(judge_dry)}. A dry run "
        f"with --judge says what the judge would take (2 theses here) and calls nothing."
    )


def test_tr_grade_judge_prints_each_cost_and_never_pays_twice(tmp_path, monkeypatch):
    grade, (champion, challenger) = journal(tmp_path)
    (judged, n_judged), (again, n_again), (last, n_last) = fakea.cli(
        monkeypatch, tmp_path, [[*grade, "--judge"]] * 3, replies=("no_verdict", "recorded"))
    assert n_judged == 2, f"`tr grade --judge` sent {n_judged} request(s) for 2 waiting theses, expected 2"
    lines = judge_part(judged)
    for name, thesis_id in (("champion (its reply held no verdict)", champion), ("challenger (pass)", challenger)):
        line = next((line for line in lines if thesis_id in line), "")
        assert PAID in costs(line), (
            f"`tr grade --judge` printed: {shown(judged)}. The {name} line should show what its call cost as the "
            f"run file has it, {PAID}: a reply that judged nothing is paid like a pass."
        )
    assert any(line.startswith("judge") and "$0.010326" in costs(line) for line in lines), (
        f"`tr grade --judge` printed: {shown(judged)}. The last line should show what the run cost in all, "
        f"$0.010326, to the same precision."
    )
    assert n_again == 1 and "1 judged" in again, (
        f"A second `tr grade --judge` sent {n_again} request(s) and printed: {shown(again)}. The pass is stored, so "
        f"that thesis is never paid for twice; the reply with no verdict stored nothing, so that thesis waits, and "
        f"this run judges it (one request)."
    )
    assert n_last == 0 and "nothing to judge" in last, (
        f"A third `tr grade --judge` sent {n_last} request(s) and printed: {shown(last)}; both theses have a verdict "
        f"now, so nothing is sent."
    )


def test_each_line_shows_the_cost_it_is_given(tmp_path):
    """grade.render_judged on made-up outcomes and costs, so a cost copied from the recording cannot pass."""
    from tradingresearch import grade

    conn, (champion, challenger, free), _ = fakea.journal_of(tmp_path, ("champion", "challenger", "challenger"))
    conn.close()
    judged = [grade.Judged(champion, error="CannotGrade: a made-up failure", cost_usd=0.000123),
              grade.Judged(challenger, verdict="pass", reason="a made-up reason", cost_usd=0.0024),
              grade.Judged(free, error="CannotGrade: refused before any call", cost_usd=0.0)]
    lines = grade.render_judged(judged, dry_run=False, max_usd=0.25)
    want = ((champion, "$0.000123"), (challenger, "$0.002400"), (free, "$0.000000"))
    ok = all(cost in costs(next((line for line in lines if t.thesis_id in line), "")) for t, cost in want)
    assert ok and "$0.002523" in costs(lines[-1]), (
        f"render_judged printed {[fakea.masked(line) for line in lines]} for outcomes that cost $0.000123 (not "
        f"judged), $0.002400 (pass) and $0.000000 (not judged, refused before any call): each line shows its own "
        f"cost_usd, $0.000000 too (a missing cost reads as one nobody knows), and the last line their sum, $0.002523."
    )


def test_tr_grade_grades_before_it_judges(tmp_path, monkeypatch):
    from tradingresearch import grade as grading

    grade, _ = journal(tmp_path)
    events: list[str] = []
    run, answer = grading.run, fakea.answer
    monkeypatch.setattr(grading, "run", lambda *a, **k: events.append("grade") or run(*a, **k))
    monkeypatch.setattr(fakea, "answer", lambda *a, **k: events.append("judge") or answer(*a, **k))
    (_, sent), = fakea.cli(monkeypatch, tmp_path, [[*grade, "--judge"]])
    assert sent == 2 and events[:1] == ["grade"], (
        f"`tr grade --judge` did, in order: {events}. It grades first: a thesis that closes today gets its Grade in "
        f"this run, and the judge, which reads only graded theses, takes it in the same run instead of the next one."
    )


def test_a_run_that_calls_nothing_reads_no_prices(tmp_path, monkeypatch):
    grade, _ = journal(tmp_path)
    lookups: list[int] = []
    fakea.cli(monkeypatch, tmp_path, [[*grade, "--judge", "--dry-run"], [*grade, "--judge"], [*grade, "--judge"]],
              price_lookups=lookups)
    assert lookups[0] == 0 and lookups[2] == 0, (
        f"`tr grade --judge --dry-run`, then `--judge` twice, looked up model prices {lookups} time(s). A run that "
        f"calls no model (a dry run, or the third run, with nothing left to judge) reads no prices: it needs no "
        f"network and costs nothing."
    )


def test_the_cap_given_on_the_command_line_is_the_cap(tmp_path, monkeypatch):
    grade, _ = journal(tmp_path)
    (out, sent), = fakea.cli(monkeypatch, tmp_path, [[*grade, "--judge", "--judge-max-usd", "0.001"]])
    assert sent == 0, (
        f"`tr grade --judge --judge-max-usd 0.001` sent {sent} request(s) and printed: {shown(out)}. One call's worst "
        f"case is about $0.043, so a $0.001 cap covers none: the cap is the one given, not the default $0.25."
    )


def test_a_dry_run_needs_no_key(tmp_path, monkeypatch):
    from tradingresearch.cli import main

    grade, _ = journal(tmp_path)
    fakea.cli(monkeypatch, tmp_path, [])  # fake keys and the offline guard; then an env file with no OpenRouter key
    alpaca_only = tmp_path / "alpaca-only.env"
    alpaca_only.write_text("APCA_API_KEY_ID=not-a-real-id\nAPCA_API_SECRET_KEY=not-a-real-secret\n")
    monkeypatch.setenv("TR_ENV_FILE", str(alpaca_only))
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            main([*grade, "--judge", "--dry-run"])
        out = printed.getvalue()
    except (Exception, SystemExit) as exc:  # `require` exits when a key is missing
        out = f"raised {fakea.shown(exc)}"
    assert "would judge 2" in out, (
        f"With no OpenRouter key, `tr grade --judge --dry-run` gave {fakea.masked(out)[:200]!r}. A dry run calls "
        f"nothing, so it needs no key: it lists what the judge would take."
    )


def test_tr_grade_with_no_session_still_judges_only_with_judge(tmp_path, monkeypatch):
    journal(tmp_path)
    (out, sent), = fakea.cli(monkeypatch, tmp_path, [["grade"]])
    assert sent == 0 and not judge_part(out), (
        f"`tr grade` with no --session (today's) sent {sent} judge request(s) and printed: {shown(out)}. The judge "
        f"runs only with --judge, whatever else the command line gives or leaves out: a default session is still a "
        f"plain `tr grade`, and a plain `tr grade` pays for nothing."
    )


def test_a_fail_verdict_prints_as_fail(tmp_path):
    from tradingresearch import grade

    conn, (champion,), _ = fakea.journal_of(tmp_path, ("champion",))
    conn.close()
    judged = [grade.Judged(champion, verdict="fail", reason="The cited level broke.", cost_usd=0.0001)]
    line = grade.render_judged(judged, dry_run=False, max_usd=0.25)[0]
    assert "P1 fail" in line and "The cited level broke." in line, (
        f"render_judged printed {fakea.masked(line)!r} for a fail verdict with the reason 'The cited level broke.'. "
        f"Each line shows the verdict the judge gave, fail as well as pass, and its reason."
    )


def test_a_pass_shows_its_reason_and_a_fail_counts_as_judged(tmp_path):
    from tradingresearch import grade

    conn, (champion, challenger), _ = fakea.journal_of(tmp_path, ("champion", "challenger"))
    conn.close()
    judged = [grade.Judged(champion, verdict="pass", reason="The named break held.", cost_usd=0.0001),
              grade.Judged(challenger, verdict="fail", reason="The cited level broke.", cost_usd=0.0001)]
    lines = grade.render_judged(judged, dry_run=False, max_usd=0.25)
    assert "The named break held." in lines[0], (
        f"render_judged printed {fakea.masked(lines[0])!r} for a pass whose reason is 'The named break held.'. A pass "
        f"shows its reason like a fail does: the reason is what the operator reads to see whether the judge read "
        f"the trade right, and a pass is a judgement too."
    )
    assert "2 judged, 0 not judged" in lines[-1], (
        f"render_judged ended with {fakea.masked(lines[-1])!r} for a pass and a fail. Both were judged: a fail is a "
        f"verdict the judge gave, not a thesis it could not judge, so the last line counts 2 judged, 0 not judged."
    )


def test_the_run_cost_is_summed_before_it_is_rounded(tmp_path):
    from tradingresearch import grade

    conn, theses, _ = fakea.journal_of(tmp_path, ("champion", "challenger"))
    conn.close()
    judged = [grade.Judged(t, verdict="pass", reason="a made-up reason", cost_usd=0.0000004) for t in theses]
    last = grade.render_judged(judged, dry_run=False, max_usd=0.25)[-1]
    assert "$0.000001" in costs(last), (
        f"render_judged ended with {fakea.masked(last)!r} for two outcomes that each cost $0.0000004. The run's cost "
        f"is their sum, $0.0000008, shown to the millionth as $0.000001: each line may round its own cost away, but "
        f"a total made of rounded lines loses every sub-microdollar call, and a run of many cheap calls shows $0."
    )

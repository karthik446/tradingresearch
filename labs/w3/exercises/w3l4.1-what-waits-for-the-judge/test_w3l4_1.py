"""w3l4.1 what waits for the judge: grade.to_judge lists the theses `tr grade --judge` will pay to judge.

Each check builds a fresh journal of FAKEA theses from tests/test_week3.py's trade (tools/fakea.py `journal_of`),
written in the order given, then filled, closed at the target and graded by `tr grade`'s own code (a teacher thesis
closes but gets no Grade). No request is sent here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

ORDINAL = ("1st", "2nd", "3rd", "4th")


def labels(listed: list, theses: list) -> list[str]:
    """Each listed thesis as `<arm> (written <n>th)`, so a message shows which ones without their random ids."""
    order = {t.thesis_id: n for n, t in enumerate(theses)}
    return [f"{t.arm} (written {ORDINAL[order[t.thesis_id]]})" if t.thesis_id in order else fakea.masked(t.thesis_id)
            for t in listed]


def test_graded_champion_and_challenger_theses_wait_oldest_first(tmp_path):
    from tradingresearch import grade

    for attempt in range(40):  # thesis ids are random: keep the journal whose newer thesis has the smaller id
        conn, theses, _ = fakea.journal_of(tmp_path / str(attempt), ("challenger", "champion", "teacher"))
        if theses[0].thesis_id > theses[1].thesis_id:
            break
        conn.close()
    got = labels(grade.to_judge(conn), theses)
    want = labels(theses[:2], theses)
    assert got == want, (
        f"With a challenger, a champion and a teacher thesis written in that order and closed, to_judge lists {got}; "
        f"it should list {want}: graded champion and challenger theses, oldest first (a capped run leaves the "
        f"newest for the next one). A teacher thesis is never judged."
    )


def test_a_thesis_without_a_grade_does_not_wait(tmp_path):
    from tradingresearch import grade

    for case, settled, graded in (("never entered (PROPOSED)", False, False), ("closed, not graded yet", True, False)):
        data_dir = tmp_path / case.split()[0]
        data_dir.mkdir()
        conn, theses, _ = fakea.journal_of(data_dir, ("champion",), settled=settled, graded=graded)
        got = labels(grade.to_judge(conn), theses)
        assert got == [], (
            f"With one champion thesis {case}, to_judge lists {got}; it should list nothing: the judge reads the "
            f"post-trade summary, which needs the thesis's Grade."
        )


def test_a_thesis_with_a_verdict_is_not_judged_again(tmp_path):
    from tradingresearch import grade, journal

    conn, theses, _ = fakea.journal_of(tmp_path, ("champion", "challenger"))
    journal.add_judge_verdict(conn, theses[0].thesis_id, "fail", "unknown: the summary cannot tell (stored by hand)")
    got = labels(grade.to_judge(conn), theses)
    want = labels(theses[1:], theses)
    assert got == want, (
        f"With the champion's verdict stored (fail, an unknown) and the challenger's not, to_judge lists {got}; it "
        f"should list {want}. Any stored verdict, pass or fail, means that thesis was judged and paid for once."
    )
    journal.add_judge_verdict(conn, theses[1].thesis_id, "pass", "the break held (stored by hand)")
    got = labels(grade.to_judge(conn), theses)
    assert got == [], f"With both verdicts stored, to_judge lists {got}; it should list nothing."


def test_the_order_is_the_order_written_not_the_order_graded(tmp_path):
    from tradingresearch import grade

    conn, theses, _ = fakea.journal_of(tmp_path, ("champion", "challenger", "champion"), graded_in=(2, 1, 0))
    got = labels(grade.to_judge(conn), theses)
    want = labels(theses, theses)
    assert got == want, (
        f"With three theses written in the order {want} and graded in the reverse order, to_judge lists {got}; it "
        f"should list all three as written. Oldest first is the order the theses were written, not the order "
        f"`tr grade` happened to grade them, and every waiting thesis is listed (the cap, not the list, stops a run)."
    )

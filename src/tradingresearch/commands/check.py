"""`tr check`: every claim of a stored analysis beside the source values it cites (SPIKE §7)."""

from __future__ import annotations

from gigai_core import open_run

from .. import analyze as an, journal
from ..records import Analysis


def source_table(prompt: str) -> dict[str, tuple[str, str, str]]:
    """source_id -> (name, value as shown, unit), read back from the SOURCES table in the stored prompt."""
    rows = {}
    for line in prompt.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 4 and cells[0].startswith("src_"):
            rows[cells[0]] = (cells[1], cells[2], cells[3])
    return rows


def cmd_check(args, cfg) -> None:
    """Every claim the model wrote, kept or rejected, beside the source values it cites."""
    conn = journal.connect(cfg.db_path)
    a = journal.get(conn, Analysis, args.analysis_id)
    run = open_run(cfg.data_dir / "runs" / f"{a.run_id}.jsonl")
    sample = next(s for s in run.samples if s.trace_id == a.sample_trace_id)
    item = run.items[sample.item_id]
    table = source_table(item.prompt)
    _, rejected = an.validate_claims(sample.output_parsed, item.expected["values"], "an_check")
    why = {r.claim: f"REJECTED {r.reason}: {r.detail}" for r in rejected}
    print(f"{a.analysis_id}  {a.ticker} {a.session}  prompt={a.prompt_version}  run={a.run_id}  "
          f"trace={a.sample_trace_id}")
    for raw in (sample.output_parsed or {}).get("claims", []):
        value = "" if raw.get("value") is None else f"  value={an.plain(raw['value'])} {raw.get('unit') or ''}"
        print(f"{raw.get('id')} [{raw.get('tag')}] {why.get(raw.get('id'), 'ok')}")
        print(f"    text: {raw.get('text')}{value}")
        for sid in raw.get("source_ids") or []:
            name, shown, unit = table.get(sid, ("NOT IN TABLE", "-", ""))
            print(f"    src:  {sid} {name} = {shown} {unit}".rstrip())
        if raw.get("derived_from"):
            print(f"    from: {', '.join(raw['derived_from'])} ({raw.get('steps')})")
    print(f"kept {len(a.claims)}, rejected {len(rejected)}")


def register(sub) -> None:
    p = sub.add_parser("check", help="every claim of an analysis beside the source values it cites")
    p.add_argument("analysis_id")
    p.set_defaults(func=cmd_check)

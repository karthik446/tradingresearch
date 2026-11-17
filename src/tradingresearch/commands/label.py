"""`tr label`: blind P1 labels of graded theses and judge agreement (SPIKE §7.3, ADR-003). No model call; `show`
reads daily bars from Alpaca."""

from __future__ import annotations

from .. import journal, label, reconcile_run
from .common import alpaca_client


def cmd_label_list(args, cfg) -> None:
    print("\n".join(label.render_list(journal.connect(cfg.db_path))))


def cmd_label_show(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    try:
        label.labelable(conn, args.thesis_id)  # refuse before asking Alpaca for anything
        with alpaca_client(cfg) as http:
            lines = label.show(conn, reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed),
                               args.thesis_id)
    except label.Refused as refused:
        raise SystemExit(str(refused)) from None
    print("\n".join(lines))


def cmd_label_add(args, cfg) -> None:
    try:
        record = label.add(journal.connect(cfg.db_path), args.thesis_id, args.verdict, note=args.note,
                           relabel=args.relabel)
    except label.Refused as refused:
        raise SystemExit(str(refused)) from None
    replaces = f", replaces {record.relabel_of}" if record.relabel_of else ""
    print(f"stored {record.label_id}: {record.item_id} {record.label} (blind{replaces})")


def cmd_label_agree(args, cfg) -> None:
    print("\n".join(label.render_agree(label.pairing(journal.connect(cfg.db_path)))))


def register(sub) -> None:
    p = sub.add_parser("label", help="blind P1 labels of graded theses and judge agreement (no model call)")
    actions = p.add_subparsers(dest="label_command", required=True)
    p = actions.add_parser("list", help="graded champion/challenger theses without a label")
    p.set_defaults(func=cmd_label_list)
    p = actions.add_parser("show", help="thesis, cited claims and post-trade summary; never a judge verdict")
    p.add_argument("thesis_id")
    p.set_defaults(func=cmd_label_show)
    p = actions.add_parser("add", help="store a blind label (P1 rubric: met, not met, unknown)")
    p.add_argument("thesis_id")
    p.add_argument("verdict", choices=tuple(label.VERDICTS))
    p.add_argument("--note", help="why, in a sentence (stored as the label's critique)")
    p.add_argument("--relabel", action="store_true", help="replace the thesis's latest label; the new one points at it")
    p.set_defaults(func=cmd_label_add)
    p = actions.add_parser("agree", help="Cohen's kappa of your latest labels against stored judge verdicts")
    p.set_defaults(func=cmd_label_agree)

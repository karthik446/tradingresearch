"""`tr label`: blind P1 labels of graded theses and judge agreement (SPIKE §7.3, ADR-003); with `--claims`, blind
claim labels of teacher claims (TRAINING-SPIKE §7.2 row 5). No model call; only P1 `show` reads daily bars from
Alpaca."""

from __future__ import annotations

from .. import journal, label, reconcile_run
from .common import alpaca_client


def cmd_label_list(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    print("\n".join(label.render_claims_list(conn) if args.claims else label.render_list(conn)))


def cmd_label_show(args, cfg) -> None:
    conn = journal.connect(cfg.db_path)
    try:
        if args.claims:
            lines = label.show_claim(conn, args.item_id)
        else:
            label.labelable(conn, args.item_id)  # refuse before asking Alpaca for anything
            with alpaca_client(cfg) as http:
                lines = label.show(conn, reconcile_run.AlpacaBars(http, cfg.data_dir / "bars_1m", cfg.feed),
                                   args.item_id)
    except label.Refused as refused:
        raise SystemExit(str(refused)) from None
    print("\n".join(lines))


def claim_add(args, cfg) -> None:
    if args.verdict or args.note or args.relabel:
        raise SystemExit("--claims add takes --tag, --supported/--unsupported and --labeller, not a P1 verdict, "
                         "--note or --relabel")
    if args.tag is None or args.labeller is None:
        raise SystemExit("--claims add needs --tag fact|inference|opinion and --labeller NAME")
    try:
        record = label.add_claim_label(journal.connect(cfg.db_path), args.item_id, args.tag, args.labeller,
                                       supported=args.supported)
    except label.Refused as refused:
        raise SystemExit(str(refused)) from None
    supported = {True: "supported", False: "unsupported", None: "support not judged"}[record.supported]
    print(f"stored {record.claim_label_id}: {record.claim_id} {record.tag}, {supported} by {record.labeller} (blind)")


def cmd_label_add(args, cfg) -> None:
    if args.claims:
        claim_add(args, cfg)
        return
    if args.tag or args.labeller or args.supported is not None:
        raise SystemExit("--tag, --supported/--unsupported and --labeller are for --claims")
    if args.verdict is None:
        raise SystemExit(f"a P1 label needs a verdict: {', '.join(label.VERDICTS)}")
    try:
        record = label.add(journal.connect(cfg.db_path), args.item_id, args.verdict, note=args.note,
                           relabel=args.relabel)
    except label.Refused as refused:
        raise SystemExit(str(refused)) from None
    replaces = f", replaces {record.relabel_of}" if record.relabel_of else ""
    print(f"stored {record.label_id}: {record.item_id} {record.label} (blind{replaces})")


def cmd_label_agree(args, cfg) -> None:
    if args.claims:
        raise SystemExit("--claims has list, show and add; the tagger's kappa against these labels is the evals "
                         "lane's (TRAINING-SPIKE §7.3)")
    print("\n".join(label.render_agree(label.pairing(journal.connect(cfg.db_path)))))


def register(sub) -> None:
    p = sub.add_parser("label", help="blind P1 labels of graded theses and judge agreement (no model call)")
    p.add_argument("--claims", action="store_true", help="blind fact/inference/opinion labels of teacher claims "
                   "instead (list, show CLAIM_ID, add CLAIM_ID)")
    actions = p.add_subparsers(dest="label_command", required=True)
    p = actions.add_parser("list", help="graded champion/challenger theses without a label")
    p.set_defaults(func=cmd_label_list)
    p = actions.add_parser("show", help="thesis, cited claims and post-trade summary; never a judge verdict")
    p.add_argument("item_id", metavar="ID", help="a thesis id (a claim id with --claims)")
    p.set_defaults(func=cmd_label_show)
    p = actions.add_parser("add", help="store a blind label (P1 rubric: met, not met, unknown)")
    p.add_argument("item_id", metavar="ID", help="a thesis id (a claim id with --claims)")
    p.add_argument("verdict", nargs="?", choices=tuple(label.VERDICTS), help="P1 verdict (not with --claims)")
    p.add_argument("--note", help="why, in a sentence (stored as the label's critique)")
    p.add_argument("--relabel", action="store_true", help="replace the thesis's latest label; the new one points at it")
    p.add_argument("--tag", choices=label.TAGS, help="--claims: the claim's kind")
    support = p.add_mutually_exclusive_group()
    support.add_argument("--supported", action="store_true", default=None, help="--claims: its sources support it")
    support.add_argument("--unsupported", dest="supported", action="store_false", default=None,
                         help="--claims: its sources do not support it")
    p.add_argument("--labeller", metavar="NAME", help="--claims: who labelled it")
    p.set_defaults(func=cmd_label_add)
    p = actions.add_parser("agree", help="Cohen's kappa of your latest labels against stored judge verdicts")
    p.set_defaults(func=cmd_label_agree)

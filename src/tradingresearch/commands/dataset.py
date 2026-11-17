"""`tr dataset`: cut the teacher analyses into a release and refill a public one (TRAINING-SPIKE §7.4). No model
call, no GitHub call, no tag: the release directory is built locally and published by hand."""

from __future__ import annotations

from pathlib import Path

from .. import dataset, journal, split
from .common import alpaca_client


def cmd_dataset_publish(args, cfg) -> None:
    out = Path(args.out) if args.out else cfg.data_dir / "release" / args.name
    conn = journal.connect(cfg.db_path)
    try:
        release = dataset.publish(conn, cfg.data_dir, out, args.name, args.form, split_id=args.split,
                                  teacher_model=args.teacher)
    except (split.Refused, dataset.Refused) as refused:
        raise SystemExit(str(refused)) from None
    print("\n".join(dataset.summary(release)))


def cmd_dataset_hydrate(args, cfg) -> None:
    with alpaca_client(cfg) as http:
        try:
            written = dataset.hydrate(Path(args.path), Path(args.out), dataset.AlpacaSource(http, cfg.data_dir))
        except dataset.Refused as refused:
            raise SystemExit(str(refused)) from None
    print(f"hydrated to {args.out}, private digests match: "
          + ", ".join(f"{fname} {n} items" for fname, n in written.items()))


def register(sub) -> None:
    p = sub.add_parser("dataset", help="cut teacher analyses into a release; refill a public one (no model call)")
    actions = p.add_subparsers(dest="dataset_command", required=True)
    p = actions.add_parser("publish", help="write the train/val release of the split's teacher analyses")
    p.add_argument("--form", choices=dataset.FORMS, required=True, help="public: Alpaca prices and headlines as "
                   "placeholders; private: verbatim (personal use)")
    p.add_argument("--name", default="teacher-sft", help="file stem (default: teacher-sft)")
    p.add_argument("--out", metavar="DIR", help="an empty or new directory (default: <TR_DATA_DIR>/release/<name>)")
    p.add_argument("--split", metavar="SPLIT_ID", help="default: the latest registered split")
    p.add_argument("--teacher", metavar="MODEL", help="only this teacher's analyses (default: every pinned teacher)")
    p.set_defaults(func=cmd_dataset_publish)
    p = actions.add_parser("hydrate", help="refill a public release from your Alpaca data; check the private digest")
    p.add_argument("path", metavar="PATH", help="the public release directory")
    p.add_argument("--out", metavar="DIR", required=True, help="an empty or new directory for the hydrated files")
    p.set_defaults(func=cmd_dataset_hydrate)

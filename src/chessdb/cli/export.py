import argparse
from pathlib import Path

from chessdb.db.export import (
    DEFAULT_COLUMN_GROUPS,
    ExportError,
    ExportSpec,
    MetricFilters,
    run_export,
)
from chessdb.metrics import METRIC_VERSION


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "export", help="export a filtered, flat parquet table (DuckDB COPY)"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--columns", default=",".join(DEFAULT_COLUMN_GROUPS))
    parser.add_argument("--metric-version", type=int, default=METRIC_VERSION)
    parser.add_argument("--engine-id", type=int, default=None)
    parser.add_argument("--min-sign-flips", type=int, default=None)
    parser.add_argument("--min-cp-range", type=int, default=None)
    parser.add_argument("--max-settle-dev", type=int, default=None)
    parser.add_argument("--min-top-rung", type=int, default=None)
    parser.add_argument("--has-mate", type=int, default=None)
    parser.add_argument("--min-mate-found-rung", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be > 0")
    if not args.db.exists():
        raise SystemExit(f"--db does not exist: {args.db}")
    if not args.out.parent.exists():
        raise SystemExit(f"--out parent directory does not exist: {args.out.parent}")
    columns = tuple(g.strip() for g in args.columns.split(",") if g.strip())

    spec = ExportSpec(
        db=args.db,
        out=args.out,
        force=args.force,
        column_groups=columns,
        filters=MetricFilters(
            metric_version=args.metric_version,
            engine_id=args.engine_id,
            min_sign_flips=args.min_sign_flips,
            min_cp_range=args.min_cp_range,
            max_settle_dev=args.max_settle_dev,
            min_top_rung=args.min_top_rung,
            has_mate=args.has_mate,
            min_mate_found_rung=args.min_mate_found_rung,
        ),
        limit=args.limit,
    )
    try:
        rows, out_columns = run_export(spec)
    except ExportError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"rows={rows} columns={len(out_columns)} file={args.out}")

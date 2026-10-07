import argparse
from pathlib import Path

from chessdb.db import connect
from chessdb.db.merge import MergeError, merge_into


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "merge", help="merge one or more shard checkpoints into a canonical DB"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument(
        "--from", dest="sources", action="append", required=True, type=Path
    )
    parser.set_defaults(func=_run)


def _print_tripwires(conn) -> None:
    for engine_id, name, version in conn.execute(
        "SELECT id, name, version FROM engines ORDER BY id"
    ):
        count = conn.execute(
            "SELECT COUNT(*) FROM evals WHERE engine_id = ?", (engine_id,)
        ).fetchone()[0]
        print(f"tripwire engine={name}/{version}#{engine_id} evals={count}")
    n_configs = conn.execute(
        "SELECT COUNT(DISTINCT sampler_config_json) FROM games"
    ).fetchone()[0]
    print(f"tripwire distinct_sampler_configs={n_configs}")


def _run(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        for source_path in args.sources:
            try:
                stats = merge_into(conn, source_path)
            except MergeError as exc:
                raise SystemExit(str(exc)) from exc
            print(
                f"source={source_path} games_added={stats.games_added} "
                f"positions_added={stats.positions_added} "
                f"attributions_updated={stats.attributions_updated} "
                f"evals_added={stats.evals_added} "
                f"evals_ignored={stats.evals_ignored}"
            )
        _print_tripwires(conn)
        print(f"now run: chessdb metrics --db {args.db}")
    finally:
        conn.close()

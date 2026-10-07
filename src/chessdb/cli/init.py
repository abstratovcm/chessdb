import argparse
from pathlib import Path

from chessdb.db import connect
from chessdb.db.api import count_rows, schema_version

_TABLES = ("engines", "games", "positions", "evals", "position_metrics")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("init", help="create or migrate the database")
    parser.add_argument("--db", required=True, type=Path)
    parser.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    print(f"user_version={schema_version(conn)}")
    for table in _TABLES:
        print(f"{table}={count_rows(conn, table)}")
    conn.close()

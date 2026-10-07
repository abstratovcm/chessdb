import argparse
from pathlib import Path

from chessdb.db import connect
from chessdb.db.api import ensure_engine
from chessdb.db.model import EngineSpec
from chessdb.engine.fetch import compute_sha256, fetch_engine


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "fetch-engine", help="download and cache a pinned Stockfish release"
    )
    parser.add_argument("--version", default="17.1")
    parser.add_argument("--variant", default="x86-64-avx2")
    parser.add_argument("--db", type=Path, default=None)
    parser.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    binary = fetch_engine(args.version, args.variant)
    sha256 = compute_sha256(binary)
    print(f"binary={binary}")
    print(f"sha256={sha256}")

    if args.db is None:
        return

    conn = connect(args.db)
    spec = EngineSpec(
        name="stockfish",
        version=args.version,
        binary_sha256=sha256,
        threads=1,
        hash_mb=16,
        options={},
    )
    print(f"engine_id={ensure_engine(conn, spec)}")
    conn.close()

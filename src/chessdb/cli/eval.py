import argparse
from pathlib import Path

import chess

from chessdb.db import connect
from chessdb.db.api import ensure_engine, ensure_position, insert_evals
from chessdb.db.model import EngineSpec, EvalRow, LimitKind, normalize_epd
from chessdb.engine.fetch import cached_engine_path, compute_sha256
from chessdb.engine.ladder import NODE_LADDER
from chessdb.engine.runner import analyse_position, open_engine

_LIMIT_KINDS = {
    "nodes": LimitKind.NODES,
    "depth": LimitKind.DEPTH,
    "movetime": LimitKind.MOVETIME_MS,
}


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "eval", help="run laddered Stockfish evals over given positions"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--epd", action="append", default=[])
    parser.add_argument("--epd-file", type=Path, default=None)
    parser.add_argument("--version", default="17.1")
    parser.add_argument("--variant", default="x86-64-avx2")
    parser.add_argument("--limit-kind", choices=sorted(_LIMIT_KINDS), default=None)
    parser.add_argument("--limit-values", default=None)
    parser.set_defaults(func=_run)


def _read_epd_file(path: Path) -> list[str]:
    positions = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        positions.append(line)
    return positions


def _resolve_positions(args: argparse.Namespace) -> list[str]:
    positions = list(args.epd)
    if args.epd_file is not None:
        positions.extend(_read_epd_file(args.epd_file))
    if not positions:
        raise SystemExit("no positions given: use --epd and/or --epd-file")
    return positions


def _resolve_ladder(args: argparse.Namespace) -> tuple[LimitKind, list[int]]:
    if args.limit_kind is None and args.limit_values is None:
        return LimitKind.NODES, list(NODE_LADDER)
    if args.limit_kind is None or args.limit_values is None:
        raise SystemExit("--limit-kind and --limit-values must be given together")
    values = [int(v) for v in args.limit_values.split(",")]
    return _LIMIT_KINDS[args.limit_kind], values


def _run(args: argparse.Namespace) -> None:
    positions = _resolve_positions(args)
    limit_kind, limit_values = _resolve_ladder(args)
    try:
        binary = cached_engine_path(args.version, args.variant)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    sha256 = compute_sha256(binary)

    conn = connect(args.db)
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version=args.version,
            binary_sha256=sha256,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )

    engine = open_engine(binary)
    inserted = ignored = 0
    try:
        for raw_position in positions:
            epd = normalize_epd(raw_position)
            position_id = ensure_position(conn, epd)
            rows = [
                build_eval_row(engine, epd, position_id, engine_id, limit_kind, value)
                for value in limit_values
            ]
            n = insert_evals(conn, rows)
            conn.commit()
            inserted += n
            ignored += len(rows) - n
    finally:
        engine.quit()
        conn.close()

    print(f"positions={len(positions)} inserted={inserted} ignored={ignored}")


def build_eval_row(
    engine, epd: str, position_id: int, engine_id: int, kind: LimitKind, value: int
) -> EvalRow:
    result = analyse_position(engine, chess.Board(epd), kind, value)
    return EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=kind,
        limit_value=value,
        score_kind=result.score_kind,
        score=result.score,
        depth=result.depth,
        seldepth=result.seldepth,
        nodes=result.nodes,
        time_ms=result.time_ms,
        bestmove=result.bestmove,
    )

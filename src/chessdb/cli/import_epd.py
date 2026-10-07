import argparse
from pathlib import Path

import chess

from chessdb.db import connect
from chessdb.db.api import ensure_position, get_position
from chessdb.db.model import ScoreKind, normalize_epd
from chessdb.engine.fetch import cached_engine_path, compute_sha256
from chessdb.engine.runner import analyse_multipv, open_engine
from chessdb.gen.sampler import SamplerConfig, is_harvestable

# External positions pass the same screen as generated ones (no mate, |cp| <= 800
# at 4k nodes) and are stored without a source game.


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "import-epd",
        help="triage external EPDs with the harvest rule and insert them as source-less positions",
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--epd-file", required=True, type=Path)
    parser.add_argument("--version", default="17.1")
    parser.add_argument("--variant", default="x86-64-avx2")
    parser.set_defaults(func=_run)


def _read_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _run(args: argparse.Namespace) -> None:
    try:
        binary = cached_engine_path(args.version, args.variant)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    config = SamplerConfig(
        engine_version=args.version,
        engine_variant=args.variant,
        engine_sha256=compute_sha256(binary),
    )
    counts = {
        "read": 0,
        "invalid": 0,
        "gameover": 0,
        "dup": 0,
        "kept": 0,
        "dropped_mate": 0,
        "dropped_cp": 0,
    }
    conn = connect(args.db)
    engine = open_engine(binary)
    try:
        for raw in _read_lines(args.epd_file):
            counts["read"] += 1
            try:
                epd = normalize_epd(raw)
            except ValueError:
                counts["invalid"] += 1
                continue
            board = chess.Board(epd)
            if board.is_game_over(claim_draw=True):
                counts["gameover"] += 1
                continue
            if get_position(conn, epd) is not None:
                counts["dup"] += 1
                continue
            lines = analyse_multipv(engine, board, config.nodes, config.multipv)
            if not is_harvestable(lines, config):
                key = (
                    "dropped_mate"
                    if lines[0].score_kind is ScoreKind.MATE
                    else "dropped_cp"
                )
                counts[key] += 1
                continue
            ensure_position(conn, epd)
            counts["kept"] += 1
        conn.commit()
    finally:
        engine.quit()
        conn.close()
    print(" ".join(f"{k}={v}" for k, v in counts.items()))

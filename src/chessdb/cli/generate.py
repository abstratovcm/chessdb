import argparse
from pathlib import Path

from chessdb.db import connect
from chessdb.db.api import ensure_position, get_position, insert_game
from chessdb.db.model import GameRecord
from chessdb.engine.fetch import cached_engine_path, compute_sha256
from chessdb.engine.runner import open_engine
from chessdb.gen.game import play_game
from chessdb.gen.sampler import SamplerConfig

# No eval rows here: MultiPV scores are not comparable to single PV evals.
# Evals come only from `chessdb eval` and `chessdb run`.


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "generate", help="generate seeded semi-random games and harvest positions"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--version", default="17.1")
    parser.add_argument("--variant", default="x86-64-avx2")
    parser.add_argument("--max-ply", type=int, default=80)
    parser.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    try:
        binary = cached_engine_path(args.version, args.variant)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc

    config = SamplerConfig(
        engine_version=args.version,
        engine_variant=args.variant,
        engine_sha256=compute_sha256(binary),
        max_ply=args.max_ply,
    )

    conn = connect(args.db)
    engine = open_engine(binary)
    plies = harvested = dup = 0
    try:
        for i in range(args.games):
            seed = args.seed + i
            game = play_game(engine, config, seed)
            plies += game.ply_count
            game_id = insert_game(
                conn,
                GameRecord(
                    seed=seed,
                    sampler_config_json=config.to_json(),
                    moves_uci=game.moves_uci,
                    result=game.result,
                    ply_count=game.ply_count,
                ),
            )
            for harvest in game.harvested:
                if get_position(conn, harvest.epd) is not None:
                    dup += 1
                else:
                    harvested += 1
                ensure_position(conn, harvest.epd, game_id, harvest.ply)
            conn.commit()
    finally:
        engine.quit()
        conn.close()

    print(f"games={args.games} plies={plies} harvested={harvested} dup={dup}")

"""Seeded semi-random game loop, replayable from (seed, config)."""

from __future__ import annotations

import random
from dataclasses import dataclass

import chess

from chessdb.engine.runner import analyse_multipv
from chessdb.gen.sampler import SamplerConfig, choose_move, is_harvestable


@dataclass(frozen=True)
class Harvest:
    epd: str
    ply: int


@dataclass(frozen=True)
class GeneratedGame:
    seed: int
    moves_uci: str
    result: str | None
    ply_count: int
    harvested: tuple[Harvest, ...]


def play_game(engine, config: SamplerConfig, seed: int) -> GeneratedGame:
    rng = random.Random(seed)
    board = chess.Board()
    moves: list[str] = []
    harvested: list[Harvest] = []

    opening_plies = rng.randint(config.opening_min_ply, config.opening_max_ply)
    for _ in range(opening_plies):
        if board.is_game_over(claim_draw=True):
            break
        legal = list(board.legal_moves)
        move = legal[rng.randrange(len(legal))]
        board.push(move)
        moves.append(move.uci())

    ply = len(moves)
    while ply < config.max_ply and not board.is_game_over(claim_draw=True):
        lines = analyse_multipv(engine, board, config.nodes, config.multipv)
        if ply >= config.harvest_min_ply and is_harvestable(lines, config):
            harvested.append(Harvest(board.epd(), ply))
        move_uci = choose_move(lines, config, rng)
        board.push_uci(move_uci)
        moves.append(move_uci)
        ply += 1

    game_over = board.is_game_over(claim_draw=True)
    result = board.result(claim_draw=True) if game_over else None

    return GeneratedGame(
        seed=seed,
        moves_uci=" ".join(moves),
        result=result,
        ply_count=len(moves),
        harvested=tuple(harvested),
    )

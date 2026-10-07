from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import chess


class LimitKind(IntEnum):
    NODES = 0
    DEPTH = 1
    MOVETIME_MS = 2


class ScoreKind(IntEnum):
    CP = 0
    MATE = 1


def normalize_epd(fen_or_epd: str) -> str:
    try:
        board = chess.Board(fen_or_epd)
    except ValueError as exc:
        raise ValueError(f"illegal position: {fen_or_epd!r}") from exc
    return board.epd()


@dataclass(frozen=True)
class EngineSpec:
    name: str
    version: str
    binary_sha256: str
    threads: int
    hash_mb: int
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EngineRow:
    id: int
    name: str
    version: str
    binary_sha256: str
    threads: int
    hash_mb: int
    options_json: str


@dataclass(frozen=True)
class GameRecord:
    seed: int
    sampler_config_json: str
    moves_uci: str
    result: str | None
    ply_count: int


@dataclass(frozen=True)
class GameRow:
    id: int
    seed: int
    sampler_config_json: str
    moves_uci: str
    result: str | None
    ply_count: int


@dataclass(frozen=True)
class PositionRow:
    id: int
    epd: str
    source_game_id: int | None
    source_ply: int | None


@dataclass(frozen=True)
class PendingLadder:
    position_id: int
    epd: str
    missing_rungs: tuple[int, ...]


@dataclass(frozen=True)
class EvalRow:
    position_id: int
    engine_id: int
    limit_kind: LimitKind
    limit_value: int
    score_kind: ScoreKind
    score: int
    depth: int
    seldepth: int | None
    nodes: int
    time_ms: int
    bestmove: str | None


@dataclass(frozen=True)
class LadderTrajectory:
    position_id: int
    scores: tuple[tuple[ScoreKind, int], ...]


@dataclass(frozen=True)
class LadderPrefixTrajectory:
    """Raw evals for whichever `rungs` a (position, engine) pair has. Picking
    the anchor rung is left to the metrics code."""

    position_id: int
    rung_scores: tuple[tuple[int, ScoreKind, int], ...]


@dataclass(frozen=True)
class PositionMetricsRow:
    position_id: int
    engine_id: int
    metric_version: int
    top_rung: int
    sign_flips: int
    cp_range: int
    settle_dev: int
    version_disagreement: int | None
    mate_found_rung: int | None = None

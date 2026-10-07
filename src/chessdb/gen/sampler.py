"""Pure MultiPV temperature move sampler: no engine, no DB, no I/O."""

from __future__ import annotations

import dataclasses
import json
import math
import random

from chessdb.db.model import ScoreKind
from chessdb.engine.runner import MultiPVLine


@dataclasses.dataclass(frozen=True)
class SamplerConfig:
    engine_version: str
    engine_variant: str
    engine_sha256: str
    opening_min_ply: int = 4
    opening_max_ply: int = 8
    multipv: int = 4
    nodes: int = 4000
    temperature_cp: int = 100
    max_delta_cp: int = 250
    max_ply: int = 80
    harvest_min_ply: int = 8
    harvest_max_abs_cp: int = 800

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> SamplerConfig:
        return cls(**json.loads(raw))


def choose_move(
    lines: list[MultiPVLine], config: SamplerConfig, rng: random.Random
) -> str:
    if lines[0].score_kind is ScoreKind.MATE:
        return lines[0].move

    best_cp = lines[0].score_stm
    candidates = [
        line
        for line in lines
        if line.score_kind is ScoreKind.CP
        and best_cp - line.score_stm <= config.max_delta_cp
    ]
    moves = [line.move for line in candidates]
    # exp is deterministic per platform; rare cross-platform ties are accepted.
    weights = [
        math.exp((line.score_stm - best_cp) / config.temperature_cp)
        for line in candidates
    ]
    return rng.choices(moves, weights=weights, k=1)[0]


def is_harvestable(lines: list[MultiPVLine], config: SamplerConfig) -> bool:
    rank1 = lines[0]
    if rank1.score_kind is ScoreKind.MATE:
        return False
    return abs(rank1.score_stm) <= config.harvest_max_abs_cp

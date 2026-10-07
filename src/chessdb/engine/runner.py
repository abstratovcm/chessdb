"""UCI wrapper built on python-chess."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

from chessdb.db.model import LimitKind, ScoreKind


@dataclass(frozen=True)
class EvalResult:
    score_kind: ScoreKind
    score: int
    depth: int
    seldepth: int | None
    nodes: int
    time_ms: int
    bestmove: str | None


@dataclass(frozen=True)
class MultiPVLine:
    rank: int
    move: str
    score_kind: ScoreKind
    score_stm: int  # side to move POV, used for sampling and never stored


def open_engine(
    binary: Path, threads: int = 1, hash_mb: int = 16
) -> chess.engine.SimpleEngine:
    engine = chess.engine.SimpleEngine.popen_uci(str(binary))
    engine.configure({"Threads": threads, "Hash": hash_mb})
    return engine


def _limit(kind: LimitKind, value: int) -> chess.engine.Limit:
    if kind is LimitKind.NODES:
        return chess.engine.Limit(nodes=value)
    if kind is LimitKind.DEPTH:
        return chess.engine.Limit(depth=value)
    if kind is LimitKind.MOVETIME_MS:
        return chess.engine.Limit(time=value / 1000)
    raise ValueError(f"unknown limit kind: {kind!r}")


def analyse_position(
    engine: chess.engine.SimpleEngine, board: chess.Board, kind: LimitKind, value: int
) -> EvalResult:
    if board.is_game_over():
        raise ValueError(f"position is game over: {board.epd()}")

    info = engine.analyse(
        board, _limit(kind, value), game=object(), info=chess.engine.INFO_ALL
    )

    for required in ("depth", "nodes", "time"):
        if required not in info:
            raise RuntimeError(f"engine did not report {required!r}: {info!r}")

    pov = info["score"].white()
    if pov.is_mate():
        score_kind, score = ScoreKind.MATE, pov.mate()
    else:
        score_kind, score = ScoreKind.CP, pov.score()

    pv = info.get("pv")
    bestmove = pv[0].uci() if pv else None

    return EvalResult(
        score_kind=score_kind,
        score=score,
        depth=info["depth"],
        seldepth=info.get("seldepth"),
        nodes=info["nodes"],
        time_ms=round(info["time"] * 1000),
        bestmove=bestmove,
    )


def analyse_multipv(
    engine: chess.engine.SimpleEngine, board: chess.Board, nodes: int, multipv: int
) -> list[MultiPVLine]:
    if board.is_game_over():
        raise ValueError(f"position is game over: {board.epd()}")

    infos = engine.analyse(
        board,
        chess.engine.Limit(nodes=nodes),
        multipv=multipv,
        game=object(),
        info=chess.engine.INFO_ALL,
    )

    lines = []
    for info in infos:
        pv = info.get("pv")
        if "score" not in info or not pv:
            continue
        pov = info["score"].relative
        if pov.is_mate():
            score_kind, score_stm = ScoreKind.MATE, pov.mate()
        else:
            score_kind, score_stm = ScoreKind.CP, pov.score()
        lines.append(
            MultiPVLine(
                rank=info.get("multipv", 1),
                move=pv[0].uci(),
                score_kind=score_kind,
                score_stm=score_stm,
            )
        )

    if not lines:
        raise RuntimeError(f"no usable multipv lines: {infos!r}")

    return sorted(lines, key=lambda line: line.rank)

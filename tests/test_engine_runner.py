import chess
import chess.engine
import pytest

from chessdb.db.model import LimitKind, ScoreKind
from chessdb.engine import runner
from chessdb.engine.ladder import NODE_LADDER

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
MATE_IN_1_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 2 3"


class _FakeEngine:
    def __init__(self, info):
        self._info = info

    def analyse(self, board, limit, game=None, info=None):
        return self._info


class _FakeMultiPVEngine:
    """Scores legal moves by UCI string with a fixed cp spread."""

    def __init__(self, cp_spread=(40, 20, 0, -400), score_kind=ScoreKind.CP):
        self._cp_spread = cp_spread
        self._score_kind = score_kind

    def analyse(self, board, limit, multipv=1, game=None, info=None):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())[: len(self._cp_spread)]
        infos = []
        for rank, (move, cp) in enumerate(zip(moves, self._cp_spread), start=1):
            score = (
                chess.engine.Mate(cp)
                if self._score_kind is ScoreKind.MATE
                else chess.engine.Cp(cp)
            )
            infos.append(
                {
                    "multipv": rank,
                    "score": chess.engine.PovScore(score, board.turn),
                    "pv": [move],
                }
            )
        return infos


class _MissingFieldsMultiPVEngine:
    def analyse(self, board, limit, multipv=1, game=None, info=None):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())
        return [
            {
                "multipv": 1,
                "score": chess.engine.PovScore(chess.engine.Cp(10), board.turn),
                "pv": [moves[0]],
            },
            {"multipv": 2, "pv": [moves[1]]},  # missing score
            {
                "multipv": 3,
                "score": chess.engine.PovScore(chess.engine.Cp(-5), board.turn),
            },  # missing pv
        ]


class _NoUsableLinesMultiPVEngine:
    def analyse(self, board, limit, multipv=1, game=None, info=None):
        return [{"multipv": 1}]


def test_node_ladder_exact_value():
    assert NODE_LADDER == (
        1_000,
        4_000,
        16_000,
        64_000,
        256_000,
        1_000_000,
        4_000_000,
    )


@pytest.mark.parametrize(
    "kind,value,attr,expected",
    [
        (LimitKind.NODES, 1234, "nodes", 1234),
        (LimitKind.DEPTH, 10, "depth", 10),
        (LimitKind.MOVETIME_MS, 500, "time", 0.5),
    ],
)
def test_limit_mapping(kind, value, attr, expected):
    limit = runner._limit(kind, value)
    assert getattr(limit, attr) == expected


@pytest.mark.parametrize("side_to_move", [chess.WHITE, chess.BLACK])
def test_pov_conversion_cp_white_pov(side_to_move):
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(37), side_to_move),
        "depth": 8,
        "nodes": 1000,
        "time": 0.01,
    }
    result = runner.analyse_position(
        _FakeEngine(info), chess.Board(START_FEN), LimitKind.NODES, 1000
    )
    expected = 37 if side_to_move == chess.WHITE else -37
    assert result.score_kind == ScoreKind.CP
    assert result.score == expected


@pytest.mark.parametrize("side_to_move", [chess.WHITE, chess.BLACK])
def test_pov_conversion_mate_white_pov(side_to_move):
    info = {
        "score": chess.engine.PovScore(chess.engine.Mate(3), side_to_move),
        "depth": 8,
        "nodes": 1000,
        "time": 0.01,
    }
    result = runner.analyse_position(
        _FakeEngine(info), chess.Board(START_FEN), LimitKind.NODES, 1000
    )
    expected = 3 if side_to_move == chess.WHITE else -3
    assert result.score_kind == ScoreKind.MATE
    assert result.score == expected


def test_analyse_position_game_over_raises():
    board = chess.Board(MATE_IN_1_FEN)
    board.push(chess.Move.from_uci("f3f7"))
    assert board.is_game_over()
    with pytest.raises(ValueError, match="game over"):
        runner.analyse_position(_FakeEngine({}), board, LimitKind.NODES, 1000)


def test_analyse_position_missing_actual_raises():
    info = {"score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE), "depth": 5}
    with pytest.raises(RuntimeError, match="nodes"):
        runner.analyse_position(
            _FakeEngine(info), chess.Board(START_FEN), LimitKind.NODES, 1000
        )


@pytest.mark.parametrize("side_to_move", [chess.WHITE, chess.BLACK])
def test_analyse_multipv_stm_pov_and_rank_order(side_to_move):
    board = chess.Board(START_FEN)
    if side_to_move == chess.BLACK:
        board.push(chess.Move.from_uci("e2e4"))
    lines = runner.analyse_multipv(_FakeMultiPVEngine(), board, nodes=4000, multipv=4)
    assert [line.rank for line in lines] == [1, 2, 3, 4]
    assert [line.score_stm for line in lines] == [40, 20, 0, -400]
    assert lines[0].move == min(board.legal_moves, key=lambda m: m.uci()).uci()


def test_analyse_multipv_missing_pv_or_score_skipped():
    board = chess.Board(START_FEN)
    lines = runner.analyse_multipv(
        _MissingFieldsMultiPVEngine(), board, nodes=4000, multipv=3
    )
    assert [line.rank for line in lines] == [1]


def test_analyse_multipv_zero_usable_lines_raises():
    board = chess.Board(START_FEN)
    with pytest.raises(RuntimeError, match="no usable multipv"):
        runner.analyse_multipv(
            _NoUsableLinesMultiPVEngine(), board, nodes=4000, multipv=1
        )


def test_analyse_multipv_game_over_raises():
    board = chess.Board(MATE_IN_1_FEN)
    board.push(chess.Move.from_uci("f3f7"))
    assert board.is_game_over()
    with pytest.raises(ValueError, match="game over"):
        runner.analyse_multipv(_FakeMultiPVEngine(), board, nodes=4000, multipv=4)


@pytest.mark.engine
def test_startpos_nodes_analysis_actuals(engine_binary):
    engine = runner.open_engine(engine_binary)
    try:
        result = runner.analyse_position(
            engine, chess.Board(START_FEN), LimitKind.NODES, 1000
        )
    finally:
        engine.quit()
    assert result.nodes > 0
    assert result.depth > 0
    assert result.time_ms >= 0
    assert result.bestmove is not None


@pytest.mark.engine
def test_mate_in_1_reports_mate_score(engine_binary):
    engine = runner.open_engine(engine_binary)
    try:
        result = runner.analyse_position(
            engine, chess.Board(MATE_IN_1_FEN), LimitKind.DEPTH, 10
        )
    finally:
        engine.quit()
    assert result.score_kind == ScoreKind.MATE
    assert result.score == 1
    assert result.bestmove == "f3f7"


@pytest.mark.engine
def test_startpos_analyse_multipv_four_distinct_moves(engine_binary):
    engine = runner.open_engine(engine_binary)
    try:
        lines = runner.analyse_multipv(
            engine, chess.Board(START_FEN), nodes=4000, multipv=4
        )
    finally:
        engine.quit()
    assert len(lines) == 4
    assert len({line.move for line in lines}) == 4
    assert lines[0].rank == 1
    assert [line.rank for line in lines] == sorted(line.rank for line in lines)

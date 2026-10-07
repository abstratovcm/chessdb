import chess
import chess.engine

from chessdb.gen.game import play_game
from chessdb.gen.sampler import SamplerConfig

CONFIG = SamplerConfig(
    engine_version="17.1",
    engine_variant="x86-64-avx2",
    engine_sha256="a" * 64,
    max_ply=24,
)

# n drawn for seed 3534 is 7, but the opening ends in checkmate at ply 5.
EARLY_MATE_SEED = 3534


class _FakeMultiPVEngine:
    """Scores legal moves by UCI string with a fixed cp spread."""

    _CP_SPREAD = (40, 20, 0, -400)

    def analyse(self, board, limit, multipv=1, game=None, info=None):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())[: len(self._CP_SPREAD)]
        return [
            {
                "multipv": rank,
                "score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn),
                "pv": [move],
            }
            for rank, (move, cp) in enumerate(zip(moves, self._CP_SPREAD), start=1)
        ]


class _NeverCalledEngine:
    def analyse(self, *args, **kwargs):
        raise AssertionError("engine should not be called")


def test_play_game_same_seed_is_identical():
    a = play_game(_FakeMultiPVEngine(), CONFIG, seed=1)
    b = play_game(_FakeMultiPVEngine(), CONFIG, seed=1)
    assert a == b


def test_play_game_different_seeds_diverge():
    a = play_game(_FakeMultiPVEngine(), CONFIG, seed=1)
    b = play_game(_FakeMultiPVEngine(), CONFIG, seed=2)
    assert a.moves_uci != b.moves_uci


def test_play_game_opening_length_between_four_and_eight():
    short_config = SamplerConfig(
        engine_version="17.1",
        engine_variant="x86-64-avx2",
        engine_sha256="a" * 64,
        max_ply=4,  # <= opening_min_ply so the sampling loop never runs
    )
    for seed in range(50):
        game = play_game(_NeverCalledEngine(), short_config, seed=seed)
        assert 4 <= game.ply_count <= 8


def test_play_game_harvest_plies_within_bounds():
    game = play_game(_FakeMultiPVEngine(), CONFIG, seed=1)
    for harvest in game.harvested:
        assert CONFIG.harvest_min_ply <= harvest.ply <= game.ply_count - 1


def test_play_game_forced_early_game_over_short_empty_harvest():
    game = play_game(_NeverCalledEngine(), CONFIG, seed=EARLY_MATE_SEED)
    assert game.ply_count == 5
    assert game.harvested == ()
    assert game.result == "1-0"

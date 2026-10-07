import random

import pytest

from chessdb.db.model import ScoreKind
from chessdb.engine.runner import MultiPVLine
from chessdb.gen.sampler import SamplerConfig, choose_move, is_harvestable

CONFIG = SamplerConfig(
    engine_version="17.1", engine_variant="x86-64-avx2", engine_sha256="a" * 64
)

CP_LINES = [
    MultiPVLine(rank=1, move="e2e4", score_kind=ScoreKind.CP, score_stm=40),
    MultiPVLine(rank=2, move="d2d4", score_kind=ScoreKind.CP, score_stm=20),
    MultiPVLine(rank=3, move="g1f3", score_kind=ScoreKind.CP, score_stm=0),
    MultiPVLine(rank=4, move="a2a4", score_kind=ScoreKind.CP, score_stm=-400),
]

MATE_LINES = [
    MultiPVLine(rank=1, move="f3f7", score_kind=ScoreKind.MATE, score_stm=1),
    MultiPVLine(rank=2, move="d2d4", score_kind=ScoreKind.CP, score_stm=20),
]


def test_sampler_config_json_round_trips_byte_stably():
    payload = CONFIG.to_json()
    assert payload == CONFIG.to_json()
    assert SamplerConfig.from_json(payload) == CONFIG


def test_choose_move_mate_is_deterministic_no_rng_consumed():
    rng = random.Random(0)
    state_before = rng.getstate()
    move = choose_move(MATE_LINES, CONFIG, rng)
    assert move == "f3f7"
    assert rng.getstate() == state_before


def test_choose_move_never_picks_line_outside_delta_window():
    for seed in range(500):
        rng = random.Random(seed)
        move = choose_move(CP_LINES, CONFIG, rng)
        assert move != "a2a4"


def test_is_harvestable_drops_mate():
    assert is_harvestable(MATE_LINES, CONFIG) is False


@pytest.mark.parametrize(
    "score_stm,expected",
    [(800, True), (-800, True), (801, False), (-801, False)],
)
def test_is_harvestable_cp_threshold(score_stm, expected):
    lines = [
        MultiPVLine(rank=1, move="e2e4", score_kind=ScoreKind.CP, score_stm=score_stm)
    ]
    assert is_harvestable(lines, CONFIG) is expected

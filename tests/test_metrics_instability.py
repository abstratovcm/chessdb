from chessdb.db.model import ScoreKind
from chessdb.metrics.instability import (
    anchor_rung,
    clamp_score,
    clamp_sequence,
    clamped_by_rung,
    common_rung_disagreement,
    cp_range,
    mate_found_rung,
    prefix_scores,
    settle_dev,
    sign_flips,
    version_disagreement,
)

CP = ScoreKind.CP
MATE = ScoreKind.MATE


def test_clamp_score_cp_within_range_unchanged():
    assert clamp_score(ScoreKind.CP, 500) == 500
    assert clamp_score(ScoreKind.CP, -500) == -500


def test_clamp_score_cp_clamped_to_thousand():
    assert clamp_score(ScoreKind.CP, 1500) == 1000
    assert clamp_score(ScoreKind.CP, -1500) == -1000


def test_clamp_score_mate_clamped_by_sign():
    assert clamp_score(ScoreKind.MATE, 3) == 1000
    assert clamp_score(ScoreKind.MATE, -3) == -1000


def test_clamp_sequence_round_trips_kinds():
    scores = ((ScoreKind.CP, 50), (ScoreKind.MATE, -2), (ScoreKind.CP, 2000))
    assert clamp_sequence(scores) == (50, -1000, 1000)


def test_sign_flips_zeros_do_not_flip_or_reset():
    assert sign_flips((50, 0, -50, 0, 30)) == 2


def test_sign_flips_leading_zero_is_skipped_not_a_baseline():
    assert sign_flips((0, 10, -10)) == 1


def test_sign_flips_same_sign_throughout_is_zero():
    assert sign_flips((10, 20, 30)) == 0


def test_sign_flips_all_zero_is_zero():
    assert sign_flips((0, 0, 0)) == 0


def test_cp_range_max_minus_min():
    assert cp_range((100, 1000, -50)) == 1050


def test_settle_dev_single_rung_ladder_is_zero():
    assert settle_dev((42,)) == 0


def test_settle_dev_max_abs_deviation_from_top():
    assert settle_dev((100, 1000, -50)) == 1050


def test_version_disagreement_none_when_no_other_engine():
    assert version_disagreement(-50, ()) is None


def test_version_disagreement_max_abs_diff_is_symmetric():
    assert version_disagreement(-50, (1000,)) == 1050
    assert version_disagreement(1000, (-50,)) == 1050


# metric_version 2


def test_anchor_rung_full_prefix_is_deepest_rung():
    rung_scores = ((1, CP, 0), (2, CP, 0), (3, CP, 0))
    assert anchor_rung(rung_scores, (1, 2, 3)) == 3


def test_anchor_rung_hole_stops_at_deepest_complete_prefix():
    rung_scores = ((1, CP, 0), (2, CP, 0), (4, CP, 0))  # 3 missing
    assert anchor_rung(rung_scores, (1, 2, 3, 4)) == 2


def test_anchor_rung_missing_first_rung_is_none():
    rung_scores = ((2, CP, 0), (3, CP, 0))
    assert anchor_rung(rung_scores, (1, 2, 3)) is None


def test_anchor_rung_no_evals_is_none():
    assert anchor_rung((), (1, 2, 3)) is None


def test_prefix_scores_drops_rungs_above_anchor():
    rung_scores = ((1, CP, 10), (2, CP, 20), (3, CP, 30))
    assert prefix_scores(rung_scores, 2) == ((CP, 10), (CP, 20))


def test_clamped_by_rung_keys_by_rung_up_to_anchor():
    rung_scores = ((1, CP, 1500), (2, MATE, -3), (3, CP, 0))
    assert clamped_by_rung(rung_scores, 2) == {1: 1000, 2: -1000}


def test_mate_found_rung_shallowest_mate_within_anchor():
    rung_scores = ((1, CP, 10), (2, CP, 20), (3, MATE, 2), (4, CP, 5))
    assert mate_found_rung(rung_scores, 4) == 3


def test_mate_found_rung_none_when_mate_only_above_anchor():
    rung_scores = ((1, CP, 10), (2, CP, 20), (3, MATE, 2))
    assert mate_found_rung(rung_scores, 2) is None


def test_mate_found_rung_none_when_no_mate_at_all():
    rung_scores = ((1, CP, 10), (2, CP, 20))
    assert mate_found_rung(rung_scores, 2) is None


def test_common_rung_disagreement_none_when_no_other_engine():
    assert common_rung_disagreement({1: 10}, 1, ()) is None


def test_common_rung_disagreement_uses_min_of_the_two_anchors_symmetric():
    # engine E anchors at 4 (shallower); engine O anchors at 16 but both
    # have data at 4 (O's anchor implies a complete prefix through 4).
    e_clamped = {1: 5, 4: 20}
    o_clamped = {1: 8, 4: 25, 16: 1000}
    assert common_rung_disagreement(e_clamped, 4, ((16, o_clamped),)) == 5
    assert common_rung_disagreement(o_clamped, 16, ((4, e_clamped),)) == 5

"""Instability metrics as pure functions. A released version is never edited."""

from __future__ import annotations

from chessdb.db.model import ScoreKind

CLAMP = 1000


def clamp_score(score_kind: ScoreKind, score: int) -> int:
    if score_kind is ScoreKind.MATE:
        return CLAMP if score > 0 else -CLAMP
    return max(-CLAMP, min(CLAMP, score))


def clamp_sequence(scores: tuple[tuple[ScoreKind, int], ...]) -> tuple[int, ...]:
    return tuple(clamp_score(kind, score) for kind, score in scores)


def sign_flips(clamped: tuple[int, ...]) -> int:
    flips = 0
    last_sign = 0
    for value in clamped:
        sign = (value > 0) - (value < 0)
        if sign == 0:
            continue
        if last_sign != 0 and sign != last_sign:
            flips += 1
        last_sign = sign
    return flips


def cp_range(clamped: tuple[int, ...]) -> int:
    return max(clamped) - min(clamped)


def settle_dev(clamped: tuple[int, ...]) -> int:
    if len(clamped) <= 1:
        return 0
    top = clamped[-1]
    return max(abs(rung - top) for rung in clamped[:-1])


def version_disagreement(
    self_clamped_top: int, other_clamped_tops: tuple[int, ...]
) -> int | None:
    if not other_clamped_tops:
        return None
    return max(abs(self_clamped_top - other) for other in other_clamped_tops)


# metric_version 2: per-engine anchor, mate-aware, engines compared at a common rung.


def anchor_rung(
    rung_scores: tuple[tuple[int, ScoreKind, int], ...], rungs: tuple[int, ...]
) -> int | None:
    """Deepest rung r in `rungs` (ascending) with evals present for
    every rung <= r; None if even `rungs[0]` is missing."""
    present = {r for r, _, _ in rung_scores}
    anchor = None
    for r in rungs:
        if r not in present:
            break
        anchor = r
    return anchor


def prefix_scores(
    rung_scores: tuple[tuple[int, ScoreKind, int], ...], anchor: int
) -> tuple[tuple[ScoreKind, int], ...]:
    return tuple((kind, score) for r, kind, score in rung_scores if r <= anchor)


def clamped_by_rung(
    rung_scores: tuple[tuple[int, ScoreKind, int], ...], anchor: int
) -> dict[int, int]:
    return {
        r: clamp_score(kind, score) for r, kind, score in rung_scores if r <= anchor
    }


def mate_found_rung(
    rung_scores: tuple[tuple[int, ScoreKind, int], ...], anchor: int
) -> int | None:
    """Shallowest rung <= anchor with a raw mate score; from raw kinds,
    never from clamped values (the clamp erases mate-ness)."""
    for r, kind, _ in rung_scores:
        if r > anchor:
            break
        if kind is ScoreKind.MATE:
            return r
    return None


def common_rung_disagreement(
    self_clamped: dict[int, int],
    self_anchor: int,
    other_anchors_clamped: tuple[tuple[int, dict[int, int]], ...],
) -> int | None:
    """Max abs diff to each other engine at min(self_anchor, other_anchor);
    None if no other engine evaluated this position."""
    if not other_anchors_clamped:
        return None
    diffs = []
    for other_anchor, other_clamped in other_anchors_clamped:
        c = min(self_anchor, other_anchor)
        diffs.append(abs(self_clamped[c] - other_clamped[c]))
    return max(diffs)

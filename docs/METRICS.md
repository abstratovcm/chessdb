# Metrics

Definitions of the `position_metrics` columns computed by `chessdb metrics`
(`src/chessdb/metrics/instability.py`) and exposed unchanged by `/api/query`,
`/api/export` and `chessdb export`. `metric_version` selects the formula. Every
version is computed on each `chessdb metrics` run, and a released formula is
never edited: changes ship as a new version.

All scores are **clamped** to `[-1000, 1000]` before any metric reads them. A
mate clamps to `+1000` (mating) or `-1000` (mated), and a cp score is clipped to
the same range. Mate distance is ignored, so mate in 1 and mate in 30 both clamp
to `±1000`.

## Versions

- **v1** scores only positions with a **complete** ladder up to
  `min(--top-rung, 1_000_000)`. `top_rung` is that cap, the same for every row
  in a run. Mates count only through the clamp.
- **v2** anchors each `(position, engine)` pair at the deepest **complete
  ladder prefix** it actually has, including the 4M rung, so rows can anchor at
  different rungs. Engines are compared at their **common** rung, the lower of
  the two anchors. Mates are detected from the raw `score_kind`, never from the
  clamped value.

## Columns

### `top_rung`

The node rung the other metrics are computed through.
- v1: `min(--top-rung, 1_000_000)`, fixed per run.
- v2: the deepest rung `r` such that every rung `<= r` has an eval for this
  `(position, engine)` pair. No row if even the first rung is missing.

### `sign_flips`

Number of sign changes in the clamped score sequence up to `top_rung`, skipping
exact zeros. It counts how often the verdict switched between white and black
as the search deepened.

### `cp_range`

`max(clamped) - min(clamped)` over the same sequence: the total spread of the
evaluation across the ladder.

### `settle_dev`

`max(abs(score - top_rung_score))` over every rung before `top_rung`: how far
the shallow reads were from the final evaluation. `0` for a single rung.

### `version_disagreement`

Largest absolute difference to any other engine; `NULL` when no other engine
has a row for this position.
- v1: compares each engine's own top rung score.
- v2: compares both engines at `min(self_anchor, other_anchor)`, a rung both
  actually reached.

### `mate_found_rung`

v2 only. The shallowest rung `<= top_rung` whose raw eval is a mate; `NULL` if
none. Filterable with `has_mate {0,1}` and `min_mate_found_rung` on
`/api/query`, `/api/export` and `chessdb export --has-mate/--min-mate-found-rung`.

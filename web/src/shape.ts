import { SCORE_KIND_MATE, type DistributionBucket, type Trajectory } from './api'

// Pure data shaping for the charts, testable without a DOM.

export interface BarRow {
  label: string
  count: number
}

export function bucketsToBarRows(
  buckets: DistributionBucket[],
  width: number,
): BarRow[] {
  return buckets.map((b) => ({
    label: width <= 1 ? String(b.start) : `${b.start}–${b.start + width}`,
    count: b.count,
  }))
}

// One row per rung of any engine, with `engine_<id>` (clamped cp or null) and
// `engine_<id>_mate`, since a clamped cp cannot tell a mate from a big score.
export type TrajectoryRow = { rung: number } & Record<string, number | boolean | null>

export function trajectoryToChartRows(trajectory: Trajectory): TrajectoryRow[] {
  const rungs = Array.from(
    new Set(trajectory.engines.flatMap((e) => e.series.map((p) => p.limit_value))),
  ).sort((a, b) => a - b)

  return rungs.map((rung) => {
    const row: TrajectoryRow = { rung }
    for (const engine of trajectory.engines) {
      const point = engine.series.find((p) => p.limit_value === rung)
      row[`engine_${engine.engine_id}`] = point ? point.clamped : null
      row[`engine_${engine.engine_id}_mate`] = point ? point.score_kind === SCORE_KIND_MATE : false
    }
    return row
  })
}

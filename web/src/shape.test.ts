import { describe, expect, it } from 'vitest'
import type { Trajectory } from './api'
import { bucketsToBarRows, trajectoryToChartRows } from './shape'

describe('bucketsToBarRows', () => {
  it('labels width-1 buckets by their single value', () => {
    const rows = bucketsToBarRows(
      [
        { start: 0, count: 2 },
        { start: 1, count: 3 },
      ],
      1,
    )
    expect(rows).toEqual([
      { label: '0', count: 2 },
      { label: '1', count: 3 },
    ])
  })

  it('labels wide buckets as a start–end range', () => {
    const rows = bucketsToBarRows([{ start: 50, count: 4 }], 50)
    expect(rows).toEqual([{ label: '50–100', count: 4 }])
  })

  it('preserves bucket order and produces one row per bucket', () => {
    const buckets = [
      { start: 0, count: 1 },
      { start: 25, count: 2 },
      { start: 50, count: 3 },
    ]
    const rows = bucketsToBarRows(buckets, 25)
    expect(rows.map((r) => r.label)).toEqual(['0–25', '25–50', '50–75'])
  })

  it('returns an empty array for empty buckets', () => {
    expect(bucketsToBarRows([], 50)).toEqual([])
  })
})

function point(limit_value: number, clamped: number, scoreKind = 0) {
  return {
    limit_value,
    score_kind: scoreKind,
    score: clamped,
    clamped,
    depth: 10,
    bestmove: 'e2e4',
  }
}

describe('trajectoryToChartRows', () => {
  it('builds one row per rung with a value and mate flag per engine', () => {
    const trajectory: Trajectory = {
      position_id: 1,
      engines: [
        { engine_id: 1, series: [point(1000, 10), point(4000, 20)] },
        { engine_id: 2, series: [point(1000, -5), point(4000, 15)] },
      ],
    }
    expect(trajectoryToChartRows(trajectory)).toEqual([
      { rung: 1000, engine_1: 10, engine_1_mate: false, engine_2: -5, engine_2_mate: false },
      { rung: 4000, engine_1: 20, engine_1_mate: false, engine_2: 15, engine_2_mate: false },
    ])
  })

  it('unions rungs across engines and nulls out missing ones', () => {
    const trajectory: Trajectory = {
      position_id: 1,
      engines: [
        { engine_id: 1, series: [point(1000, 10), point(4000, 20)] },
        { engine_id: 2, series: [point(1000, -5)] },
      ],
    }
    expect(trajectoryToChartRows(trajectory)).toEqual([
      { rung: 1000, engine_1: 10, engine_1_mate: false, engine_2: -5, engine_2_mate: false },
      { rung: 4000, engine_1: 20, engine_1_mate: false, engine_2: null, engine_2_mate: false },
    ])
  })

  it('sorts rungs ascending regardless of input order', () => {
    const trajectory: Trajectory = {
      position_id: 1,
      engines: [{ engine_id: 1, series: [point(4000, 20), point(1000, 10)] }],
    }
    expect(trajectoryToChartRows(trajectory).map((r) => r.rung)).toEqual([1000, 4000])
  })

  it('returns an empty array when no engines have series data', () => {
    expect(trajectoryToChartRows({ position_id: 1, engines: [] })).toEqual([])
  })

  it('flags a mate point via score_kind, distinct from a large clamped cp', () => {
    const trajectory: Trajectory = {
      position_id: 1,
      engines: [
        {
          engine_id: 1,
          series: [point(1000, 1000, /* CP */ 0), point(4000, 1000, /* MATE */ 1)],
        },
      ],
    }
    const rows = trajectoryToChartRows(trajectory)
    expect(rows[0]).toEqual({ rung: 1000, engine_1: 1000, engine_1_mate: false })
    expect(rows[1]).toEqual({ rung: 4000, engine_1: 1000, engine_1_mate: true })
  })

  it('flags a missing point as not-mate rather than leaving the key unset', () => {
    const trajectory: Trajectory = {
      position_id: 1,
      engines: [
        { engine_id: 1, series: [point(4000, 20)] },
        { engine_id: 2, series: [point(1000, 5)] },
      ],
    }
    expect(trajectoryToChartRows(trajectory)[0]).toEqual({
      rung: 1000,
      engine_1: null,
      engine_1_mate: false,
      engine_2: 5,
      engine_2_mate: false,
    })
  })
})

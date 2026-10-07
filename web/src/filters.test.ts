import { describe, expect, it } from 'vitest'
import {
  decodeBrowseQuery,
  decodeFilters,
  encodeBrowseQuery,
  encodeFilters,
  filtersEqual,
  loadSavedFilters,
  saveSavedFilters,
  type StorageLike,
} from './filters'

describe('encodeFilters / decodeFilters', () => {
  it('round-trips every MetricFilters field', () => {
    const filters = {
      metric_version: 1,
      engine_id: 3,
      min_sign_flips: 2,
      min_cp_range: 100,
      max_settle_dev: 50,
      min_top_rung: 64_000,
      has_mate: 1,
      min_mate_found_rung: 4_000,
    }
    expect(decodeFilters(encodeFilters(filters))).toEqual(filters)
  })

  it('omits undefined fields when encoding', () => {
    const params = encodeFilters({ metric_version: 1 })
    expect(Array.from(params.keys())).toEqual(['metric_version'])
  })

  it('ignores unknown keys when decoding', () => {
    const params = new URLSearchParams('metric_version=1&bogus=zzz')
    expect(decodeFilters(params)).toEqual({ metric_version: 1 })
  })

  it('drops non-integer values instead of throwing', () => {
    const params = new URLSearchParams('metric_version=abc&min_sign_flips=1.5')
    expect(decodeFilters(params)).toEqual({})
  })

  it('accepts negative integers', () => {
    const params = new URLSearchParams('min_cp_range=-10')
    expect(decodeFilters(params)).toEqual({ min_cp_range: -10 })
  })
})

describe('encodeBrowseQuery / decodeBrowseQuery', () => {
  it('round-trips filters plus order_by/descending', () => {
    const query = {
      filters: { metric_version: 1, min_sign_flips: 2 },
      orderBy: 'version_disagreement',
      descending: true,
    }
    expect(decodeBrowseQuery(encodeBrowseQuery(query))).toEqual(query)
  })

  it('defaults descending to false and orderBy to undefined when absent', () => {
    const params = new URLSearchParams('metric_version=1')
    expect(decodeBrowseQuery(params)).toEqual({
      filters: { metric_version: 1 },
      orderBy: undefined,
      descending: false,
    })
  })
})

describe('filtersEqual', () => {
  it('treats identical filter sets as equal regardless of object identity', () => {
    expect(filtersEqual({ metric_version: 1, min_sign_flips: 2 }, { metric_version: 1, min_sign_flips: 2 })).toBe(
      true,
    )
  })

  it('is insensitive to key order', () => {
    expect(filtersEqual({ min_sign_flips: 2, metric_version: 1 }, { metric_version: 1, min_sign_flips: 2 })).toBe(
      true,
    )
  })

  it('detects a changed value', () => {
    expect(filtersEqual({ metric_version: 1 }, { metric_version: 2 })).toBe(false)
  })

  it('detects an added or removed key', () => {
    expect(filtersEqual({ metric_version: 1 }, { metric_version: 1, has_mate: 1 })).toBe(false)
  })

  it('treats two empty filter sets as equal', () => {
    expect(filtersEqual({}, {})).toBe(true)
  })
})

function memoryStorage(initial: Record<string, string> = {}): StorageLike {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value)
    },
  }
}

describe('saved filters codec', () => {
  it('returns an empty map when nothing has been saved yet', () => {
    expect(loadSavedFilters(memoryStorage())).toEqual({})
  })

  it('round-trips a named filter set', () => {
    const storage = memoryStorage()
    saveSavedFilters(storage, { sharp: { min_sign_flips: 2 } })
    expect(loadSavedFilters(storage)).toEqual({ sharp: { min_sign_flips: 2 } })
  })

  it('resets instead of crashing on corrupt JSON', () => {
    const storage = memoryStorage({ 'chessdb.savedFilters.v1': '{not json' })
    expect(loadSavedFilters(storage)).toEqual({})
  })

  it('resets instead of crashing on an unversioned/unexpected shape', () => {
    const storage = memoryStorage({
      'chessdb.savedFilters.v1': JSON.stringify({ sharp: { min_sign_flips: 2 } }),
    })
    expect(loadSavedFilters(storage)).toEqual({})
  })
})

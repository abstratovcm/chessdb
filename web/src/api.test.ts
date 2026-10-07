import { describe, expect, it } from 'vitest'
import {
  distributionPath,
  exportPath,
  metaPath,
  positionByEpdPath,
  positionByIdPath,
  queryPath,
  trajectoryPath,
} from './api'

describe('api URL building', () => {
  it('metaPath is a fixed relative path', () => {
    expect(metaPath()).toBe('/api/meta')
  })

  it('positionByIdPath interpolates the numeric id', () => {
    expect(positionByIdPath(42)).toBe('/api/positions/42')
  })

  it('positionByEpdPath URL-encodes the epd query param', () => {
    const epd = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -'
    const path = positionByEpdPath(epd)
    expect(path.startsWith('/api/positions/by-epd?epd=')).toBe(true)
    expect(new URL(path, 'http://x').searchParams.get('epd')).toBe(epd)
  })

  it('trajectoryPath nests under the position id', () => {
    expect(trajectoryPath(7)).toBe('/api/positions/7/trajectory')
  })

  it('queryPath omits undefined filters and includes limit/offset', () => {
    const path = queryPath({ metric_version: 1 }, 50, 100)
    const params = new URL(path, 'http://x').searchParams
    expect(params.get('metric_version')).toBe('1')
    expect(params.get('limit')).toBe('50')
    expect(params.get('offset')).toBe('100')
    expect(params.has('engine_id')).toBe(false)
  })

  it('queryPath includes only the provided optional filters', () => {
    const path = queryPath({ metric_version: 1, engine_id: 3, min_sign_flips: 2 }, 10, 0)
    const params = new URL(path, 'http://x').searchParams
    expect(params.get('engine_id')).toBe('3')
    expect(params.get('min_sign_flips')).toBe('2')
    expect(params.has('min_cp_range')).toBe(false)
  })

  it('distributionPath omits engine_id/width when not given', () => {
    const path = distributionPath('cp_range', 1)
    const params = new URL(path, 'http://x').searchParams
    expect(params.get('metric')).toBe('cp_range')
    expect(params.get('metric_version')).toBe('1')
    expect(params.has('engine_id')).toBe(false)
    expect(params.has('width')).toBe(false)
  })

  it('distributionPath includes engine_id/width when given', () => {
    const path = distributionPath('cp_range', 1, 5, 25)
    const params = new URL(path, 'http://x').searchParams
    expect(params.get('engine_id')).toBe('5')
    expect(params.get('width')).toBe('25')
  })

  it('exportPath composes filters and an optional columns string', () => {
    const path = exportPath({ metric_version: 1 }, 'core,metrics')
    const params = new URL(path, 'http://x').searchParams
    expect(params.get('columns')).toBe('core,metrics')
  })
})

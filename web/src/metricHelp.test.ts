import { describe, expect, it } from 'vitest'
import { METRIC_HELP } from './metricHelp'

// Same filter and column keys as Browse.tsx, so every tooltip has help text.
const BROWSE_FILTER_KEYS = [
  'metric_version',
  'engine_id',
  'has_mate',
  'min_sign_flips',
  'min_cp_range',
  'max_settle_dev',
  'min_top_rung',
  'min_mate_found_rung',
]

const SORTABLE_COLUMN_KEYS = [
  'position_id',
  'epd',
  'top_rung',
  'sign_flips',
  'cp_range',
  'settle_dev',
  'version_disagreement',
  'mate_found_rung',
]

describe('METRIC_HELP', () => {
  it('covers every Browse filter key', () => {
    for (const key of BROWSE_FILTER_KEYS) {
      expect(METRIC_HELP[key], `missing METRIC_HELP entry for filter ${key}`).toBeTruthy()
    }
  })

  it('covers every sortable column', () => {
    for (const key of SORTABLE_COLUMN_KEYS) {
      expect(METRIC_HELP[key], `missing METRIC_HELP entry for column ${key}`).toBeTruthy()
    }
  })
})

// Filter codecs for the URL hash and for saved filters in localStorage,
// since the server is read-only.

import type { QueryFilters } from './api'

const INT_FILTER_KEYS = [
  'metric_version',
  'engine_id',
  'min_sign_flips',
  'min_cp_range',
  'max_settle_dev',
  'min_top_rung',
  'has_mate',
  'min_mate_found_rung',
] as const satisfies readonly (keyof QueryFilters)[]

const ORDER_BY_KEY = 'order_by'
const DESCENDING_KEY = 'descending'

export interface BrowseQuery {
  filters: QueryFilters
  orderBy?: string
  descending: boolean
}

function parseIntStrict(value: string): number | undefined {
  if (!/^-?\d+$/.test(value)) return undefined
  return Number(value)
}

export function encodeFilters(filters: QueryFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const key of INT_FILTER_KEYS) {
    const value = filters[key]
    if (value !== undefined) params.set(key, String(value))
  }
  return params
}

// Compares encoded strings because every route parse yields a new filters object.
export function filtersEqual(a: QueryFilters, b: QueryFilters): boolean {
  return encodeFilters(a).toString() === encodeFilters(b).toString()
}

export function decodeFilters(params: URLSearchParams): QueryFilters {
  const filters: QueryFilters = {}
  for (const key of INT_FILTER_KEYS) {
    const raw = params.get(key)
    if (raw === null) continue
    const value = parseIntStrict(raw)
    if (value !== undefined) filters[key] = value
  }
  return filters
}

export function encodeBrowseQuery(query: BrowseQuery): URLSearchParams {
  const params = encodeFilters(query.filters)
  if (query.orderBy !== undefined) params.set(ORDER_BY_KEY, query.orderBy)
  if (query.descending) params.set(DESCENDING_KEY, '1')
  return params
}

export function decodeBrowseQuery(params: URLSearchParams): BrowseQuery {
  return {
    filters: decodeFilters(params),
    orderBy: params.get(ORDER_BY_KEY) ?? undefined,
    descending: params.get(DESCENDING_KEY) === '1',
  }
}

export interface SavedFiltersStore {
  v: 1
  filters: Record<string, QueryFilters>
}

// Minimal Storage interface so tests can use an in-memory fake.
export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

const SAVED_FILTERS_KEY = 'chessdb.savedFilters.v1'

function isSavedFiltersStore(value: unknown): value is SavedFiltersStore {
  if (typeof value !== 'object' || value === null) return false
  const obj = value as Record<string, unknown>
  return obj.v === 1 && typeof obj.filters === 'object' && obj.filters !== null
}

export function loadSavedFilters(storage: StorageLike): Record<string, QueryFilters> {
  const raw = storage.getItem(SAVED_FILTERS_KEY)
  if (raw === null) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    return isSavedFiltersStore(parsed) ? parsed.filters : {}
  } catch {
    return {}
  }
}

export function saveSavedFilters(
  storage: StorageLike,
  filters: Record<string, QueryFilters>,
): void {
  const store: SavedFiltersStore = { v: 1, filters }
  storage.setItem(SAVED_FILTERS_KEY, JSON.stringify(store))
}

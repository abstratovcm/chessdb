// The only file that calls `fetch`. Types mirror src/chessdb/api/app.py and the
// enum values in src/chessdb/db/model.py.

export const SCORE_KIND_CP = 0
export const SCORE_KIND_MATE = 1

export const LIMIT_KIND_NODES = 0
export const LIMIT_KIND_DEPTH = 1
export const LIMIT_KIND_MOVETIME_MS = 2

export interface Position {
  id: number
  epd: string
  source_game_id: number | null
  source_ply: number | null
}

export interface EvalRow {
  engine_id: number
  limit_kind: number
  limit_value: number
  score_kind: number
  score: number
  depth: number
  seldepth: number | null
  nodes: number
  time_ms: number
  bestmove: string | null
}

export interface MetricsRow {
  engine_id: number
  metric_version: number
  top_rung: number
  sign_flips: number
  cp_range: number
  settle_dev: number
  version_disagreement: number | null
}

export interface EngineRow {
  id: number
  name: string
  version: string
  binary_sha256: string
  threads: number
  hash_mb: number
  options_json: string
}

export interface PositionDetail {
  position: Position
  evals: EvalRow[]
  metrics: MetricsRow[]
}

export interface Meta {
  schema_version: number
  row_counts: Record<string, number>
  engines: EngineRow[]
  metric_versions: number[]
}

export interface TrajectoryPoint {
  limit_value: number
  score_kind: number
  score: number
  clamped: number
  depth: number
  bestmove: string | null
}

export interface TrajectorySeries {
  engine_id: number
  series: TrajectoryPoint[]
}

export interface Trajectory {
  position_id: number
  engines: TrajectorySeries[]
}

export interface QueryRow {
  position_id: number
  epd: string
  engine_id: number
  engine_name: string
  engine_version: string
  metric_version: number
  top_rung: number
  sign_flips: number
  cp_range: number
  settle_dev: number
  version_disagreement: number | null
  mate_found_rung: number | null
}

export interface QueryPage {
  total: number
  limit: number
  offset: number
  rows: QueryRow[]
}

export interface QueryFilters {
  metric_version?: number
  engine_id?: number
  min_sign_flips?: number
  min_cp_range?: number
  max_settle_dev?: number
  min_top_rung?: number
  has_mate?: number
  min_mate_found_rung?: number
}

export interface DistributionBucket {
  start: number
  count: number
}

export interface Distribution {
  metric: string
  width: number
  buckets: DistributionBucket[]
  null_count: number
}

export interface DepthByRungRow {
  engine_id: number
  engine_name: string
  engine_version: string
  limit_value: number
  n: number
  avg_depth: number
  min_depth: number
  avg_seldepth: number | null
  mate_count: number
}

export interface DepthByRungPage {
  rows: DepthByRungRow[]
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`)
    this.status = status
    this.detail = detail
  }
}

function buildQuery(
  params: Record<string, string | number | boolean | undefined>,
): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

// Path builders are separate so `useApi(path)` can use them and tests need no network.
export const metaPath = (): string => '/api/meta'

export const positionByIdPath = (id: number): string => `/api/positions/${id}`

export const positionByEpdPath = (epd: string): string =>
  `/api/positions/by-epd${buildQuery({ epd })}`

export const trajectoryPath = (positionId: number): string =>
  `/api/positions/${positionId}/trajectory`

export const depthByRungPath = (): string => '/api/depth-by-rung'

export const queryPath = (
  filters: QueryFilters,
  limit: number,
  offset: number,
  orderBy?: string,
  descending?: boolean,
): string =>
  `/api/query${buildQuery({
    ...filters,
    order_by: orderBy,
    descending: descending || undefined,
    limit,
    offset,
  })}`

export const distributionPath = (
  metric: string,
  metricVersion: number,
  engineId?: number,
  width?: number,
): string =>
  `/api/distributions${buildQuery({
    metric,
    metric_version: metricVersion,
    engine_id: engineId,
    width,
  })}`

export const exportPath = (filters: QueryFilters, columns?: string): string =>
  `/api/export${buildQuery({ ...filters, columns })}`

// Keep in sync with COLUMN_GROUPS and DEFAULT_COLUMN_GROUPS in db/export.py.
export const COLUMN_GROUPS = [
  'core',
  'metrics',
  'cp',
  'raw',
  'bestmove',
  'actuals',
] as const

export const DEFAULT_COLUMN_GROUPS: readonly string[] = ['core', 'metrics', 'cp']

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(path, { signal })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // non-JSON error body, use statusText
    }
    throw new ApiError(resp.status, detail)
  }
  return (await resp.json()) as T
}

export const getMeta = (): Promise<Meta> => apiGet<Meta>(metaPath())

export const getPositionById = (id: number): Promise<PositionDetail> =>
  apiGet<PositionDetail>(positionByIdPath(id))

export const getPositionByEpd = (epd: string): Promise<PositionDetail> =>
  apiGet<PositionDetail>(positionByEpdPath(epd))

export const getTrajectory = (positionId: number): Promise<Trajectory> =>
  apiGet<Trajectory>(trajectoryPath(positionId))

export const getDepthByRung = (): Promise<DepthByRungPage> =>
  apiGet<DepthByRungPage>(depthByRungPath())

export const queryPositions = (
  filters: QueryFilters,
  limit: number,
  offset: number,
  orderBy?: string,
  descending?: boolean,
): Promise<QueryPage> =>
  apiGet<QueryPage>(queryPath(filters, limit, offset, orderBy, descending))

export const getDistribution = (
  metric: string,
  metricVersion: number,
  engineId?: number,
  width?: number,
): Promise<Distribution> =>
  apiGet<Distribution>(distributionPath(metric, metricVersion, engineId, width))

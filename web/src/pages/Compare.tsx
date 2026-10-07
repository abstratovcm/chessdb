import {
  distributionPath,
  metaPath,
  queryPath,
  type Distribution,
  type Meta,
  type QueryPage,
} from '../api'
import Histogram from '../components/Histogram'
import { isApiError, useApi } from '../useApi'
import { ResultsTable } from './Browse'

const TOP_N = 50

function errorMessage(error: unknown): string {
  return isApiError(error) ? error.detail : (error as Error).message
}

function EngineHistogram({
  engine,
  metricVersion,
}: {
  engine: Meta['engines'][number]
  metricVersion: number
}) {
  const { data, loading, error } = useApi<Distribution>(
    distributionPath('version_disagreement', metricVersion, engine.id),
  )
  if (loading) return <div className="card">Loading…</div>
  if (error)
    return (
      <div className="card">
        <p className="error">{errorMessage(error)}</p>
      </div>
    )
  if (!data) return null
  return <Histogram title={`${engine.name} ${engine.version}`} distribution={data} />
}

export default function Compare() {
  const { data: meta, loading, error } = useApi<Meta>(metaPath())

  const hasComparison = meta !== null && meta.engines.length >= 2
  const metricVersion =
    meta && meta.metric_versions.length > 0 ? Math.max(...meta.metric_versions) : undefined
  const query =
    hasComparison && metricVersion !== undefined
      ? {
          filters: { metric_version: metricVersion },
          orderBy: 'version_disagreement',
          descending: true,
        }
      : null
  const path = query ? queryPath(query.filters, TOP_N, 0, query.orderBy, query.descending) : null
  const {
    data: page,
    loading: pageLoading,
    error: pageError,
  } = useApi<QueryPage>(path)

  if (loading) return <p>Loading…</p>
  if (error) return <p className="error">{errorMessage(error)}</p>
  if (!meta) return null
  if (!hasComparison || !query || metricVersion === undefined) {
    return (
      <p className="muted">
        Cross-version comparison needs ≥ 2 engines — no cross-version data in this
        DB yet.
      </p>
    )
  }

  return (
    <div>
      <h2>Top {TOP_N} by cross-version disagreement</h2>
      {pageLoading && <p>Loading…</p>}
      {pageError && <p className="error">{errorMessage(pageError)}</p>}
      {page && (
        <ResultsTable
          page={{
            ...page,
            rows: page.rows.filter((row) => row.version_disagreement !== null),
          }}
          query={query}
        />
      )}

      <h2>version_disagreement by engine</h2>
      <div className="side-by-side">
        {meta.engines.slice(0, 2).map((engine) => (
          <EngineHistogram key={engine.id} engine={engine} metricVersion={metricVersion} />
        ))}
      </div>
    </div>
  )
}

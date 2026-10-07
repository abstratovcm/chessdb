import { useEffect, useState } from 'react'
import {
  depthByRungPath,
  distributionPath,
  metaPath,
  type DepthByRungPage,
  type DepthByRungRow,
  type Distribution,
  type Meta,
} from '../api'
import Histogram from '../components/Histogram'
import { METRIC_HELP } from '../metricHelp'
import { isApiError, useApi } from '../useApi'

function errorMessage(error: unknown): string {
  return isApiError(error) ? error.detail : (error as Error).message
}

const HISTOGRAM_METRICS: { key: string; title: string }[] = [
  { key: 'top_rung', title: 'Top rung' },
  { key: 'sign_flips', title: 'Sign flips' },
  { key: 'cp_range', title: 'CP range' },
  { key: 'settle_dev', title: 'Settle deviation' },
  { key: 'version_disagreement', title: 'Version disagreement' },
]

function MetaCards({ meta }: { meta: Meta }) {
  return (
    <div className="cards">
      <div className="card">
        <h2>Schema</h2>
        <p>schema_version {meta.schema_version}</p>
      </div>
      <div className="card">
        <h2>Row counts</h2>
        <table>
          <tbody>
            {Object.entries(meta.row_counts).map(([table, count]) => (
              <tr key={table}>
                <td>{table}</td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h2>Engines</h2>
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>name</th>
              <th>version</th>
              <th>threads</th>
              <th>hash_mb</th>
            </tr>
          </thead>
          <tbody>
            {meta.engines.map((e) => (
              <tr key={e.id}>
                <td>{e.id}</td>
                <td>{e.name}</td>
                <td>{e.version}</td>
                <td>{e.threads}</td>
                <td>{e.hash_mb}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h2>Metric versions</h2>
        <p>{meta.metric_versions.join(', ') || 'none'}</p>
      </div>
    </div>
  )
}

function groupByEngine(rows: DepthByRungRow[]): Map<number, DepthByRungRow[]> {
  const byEngine = new Map<number, DepthByRungRow[]>()
  for (const row of rows) {
    const engineRows = byEngine.get(row.engine_id) ?? []
    engineRows.push(row)
    byEngine.set(row.engine_id, engineRows)
  }
  return byEngine
}

// One table per engine, so shallow or mostly mate rungs stand out.
function DepthByRungPanel() {
  const { data, loading, error } = useApi<DepthByRungPage>(depthByRungPath())
  if (loading) return <p>Loading depth by rung…</p>
  if (error) return <p className="error">{errorMessage(error)}</p>
  if (!data || data.rows.length === 0) return null

  return (
    <div className="cards">
      {Array.from(groupByEngine(data.rows)).map(([engineId, rows]) => (
        <div className="card" key={engineId}>
          <h2>
            {rows[0].engine_name} {rows[0].engine_version} — depth by rung
          </h2>
          <table>
            <thead>
              <tr>
                <th title={METRIC_HELP.top_rung}>rung</th>
                <th>evals</th>
                <th>avg depth</th>
                <th>min depth</th>
                <th>avg seldepth</th>
                <th title={METRIC_HELP.mate_found_rung}>mates</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.limit_value}>
                  <td>{r.limit_value}</td>
                  <td>{r.n}</td>
                  <td>{r.avg_depth.toFixed(1)}</td>
                  <td>{r.min_depth}</td>
                  <td>{r.avg_seldepth === null ? '—' : r.avg_seldepth.toFixed(1)}</td>
                  <td>{r.mate_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

function HistogramSlot({
  metricKey,
  title,
  metricVersion,
  engineId,
}: {
  metricKey: string
  title: string
  metricVersion: number
  engineId: number | undefined
}) {
  const { data, loading, error } = useApi<Distribution>(
    distributionPath(metricKey, metricVersion, engineId),
  )
  if (loading) return <div className="card">Loading {title}…</div>
  if (error)
    return (
      <div className="card">
        <h2>{title}</h2>
        <p className="error">{errorMessage(error)}</p>
      </div>
    )
  if (!data) return null
  return <Histogram title={title} help={METRIC_HELP[metricKey]} distribution={data} />
}

export default function Dashboard() {
  const { data: meta, loading, error } = useApi<Meta>(metaPath())
  const [metricVersion, setMetricVersion] = useState<number | null>(null)
  const [engineId, setEngineId] = useState<number | ''>('')

  useEffect(() => {
    if (meta && metricVersion === null && meta.metric_versions.length > 0) {
      setMetricVersion(Math.max(...meta.metric_versions))
    }
  }, [meta, metricVersion])

  if (loading) return <p>Loading…</p>
  if (error) return <p className="error">{errorMessage(error)}</p>
  if (!meta) return null

  return (
    <div>
      <MetaCards meta={meta} />
      <DepthByRungPanel />

      {metricVersion !== null && (
        <>
          <div className="toolbar">
            <label>
              metric_version{' '}
              <select
                value={metricVersion}
                onChange={(e) => setMetricVersion(Number(e.target.value))}
              >
                {meta.metric_versions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label>
              engine{' '}
              <select
                value={engineId}
                onChange={(e) =>
                  setEngineId(e.target.value === '' ? '' : Number(e.target.value))
                }
              >
                <option value="">all engines</option>
                {meta.engines.map((eng) => (
                  <option key={eng.id} value={eng.id}>
                    {eng.name} {eng.version}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="cards">
            {HISTOGRAM_METRICS.map((m) => (
              <HistogramSlot
                key={m.key}
                metricKey={m.key}
                title={m.title}
                metricVersion={metricVersion}
                engineId={engineId === '' ? undefined : engineId}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

import { useState } from 'react'
import {
  LIMIT_KIND_DEPTH,
  LIMIT_KIND_MOVETIME_MS,
  LIMIT_KIND_NODES,
  SCORE_KIND_MATE,
  positionByEpdPath,
  positionByIdPath,
  trajectoryPath,
  type EvalRow,
  type PositionDetail,
  type Trajectory,
} from '../api'
import Board from '../components/Board'
import TrajectoryChart from '../components/TrajectoryChart'
import { navigate } from '../router'
import { isApiError, useApi } from '../useApi'

const LIMIT_KIND_LABEL: Record<number, string> = {
  [LIMIT_KIND_NODES]: 'nodes',
  [LIMIT_KIND_DEPTH]: 'depth',
  [LIMIT_KIND_MOVETIME_MS]: 'movetime_ms',
}

function errorMessage(error: unknown): string {
  return isApiError(error) ? error.detail : (error as Error).message
}

function parseRoute(route: string): { id: number | null; epd: string | null } {
  const [path, search] = route.split('?')
  const idMatch = path.match(/^\/position\/(\d+)$/)
  if (idMatch) return { id: Number(idMatch[1]), epd: null }
  const epd = search ? new URLSearchParams(search).get('epd') : null
  return { id: null, epd }
}

function groupEvalsByEngine(evals: EvalRow[]): [number, EvalRow[]][] {
  const byEngine = new Map<number, EvalRow[]>()
  for (const row of evals) {
    const bucket = byEngine.get(row.engine_id)
    if (bucket) bucket.push(row)
    else byEngine.set(row.engine_id, [row])
  }
  return Array.from(byEngine.entries())
}

function LookupForm({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial)
  return (
    <form
      className="toolbar"
      onSubmit={(e) => {
        e.preventDefault()
        const trimmed = value.trim()
        if (!trimmed) return
        navigate(
          /^\d+$/.test(trimmed)
            ? `/position/${trimmed}`
            : `/position?epd=${encodeURIComponent(trimmed)}`,
        )
      }}
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="position id or EPD"
        size={56}
      />
      <button type="submit">Look up</button>
    </form>
  )
}

function EvalsTable({ evals }: { evals: EvalRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>limit</th>
          <th>score</th>
          <th>depth</th>
          <th>seldepth</th>
          <th>nodes</th>
          <th>time_ms</th>
          <th>bestmove</th>
        </tr>
      </thead>
      <tbody>
        {evals.map((e, i) => (
          <tr key={i}>
            <td>
              {LIMIT_KIND_LABEL[e.limit_kind] ?? e.limit_kind}={e.limit_value}
            </td>
            <td>{e.score_kind === SCORE_KIND_MATE ? `mate ${e.score}` : `${e.score}cp`}</td>
            <td>{e.depth}</td>
            <td>{e.seldepth ?? '—'}</td>
            <td>{e.nodes}</td>
            <td>{e.time_ms}</td>
            <td>{e.bestmove ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function PositionPanel({ path }: { path: string }) {
  const { data, loading, error } = useApi<PositionDetail>(path)
  const trajectory = useApi<Trajectory>(
    data ? trajectoryPath(data.position.id) : null,
  )

  if (loading) return <p>Loading…</p>
  if (error) return <p className="error">{errorMessage(error)}</p>
  if (!data) return null

  const { position, evals, metrics } = data

  return (
    <div>
      <Board epd={position.epd} />

      <h2>Metrics</h2>
      <table>
        <thead>
          <tr>
            <th>engine_id</th>
            <th>metric_version</th>
            <th>top_rung</th>
            <th>sign_flips</th>
            <th>cp_range</th>
            <th>settle_dev</th>
            <th>version_disagreement</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m, i) => (
            <tr key={i}>
              <td>{m.engine_id}</td>
              <td>{m.metric_version}</td>
              <td>{m.top_rung}</td>
              <td>{m.sign_flips}</td>
              <td>{m.cp_range}</td>
              <td>{m.settle_dev}</td>
              <td>{m.version_disagreement ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Evals</h2>
      {groupEvalsByEngine(evals).map(([engineId, rows]) => (
        <div key={engineId}>
          <h3>engine {engineId}</h3>
          <EvalsTable evals={rows} />
        </div>
      ))}

      <h2>Trajectory (NODES ladder)</h2>
      {trajectory.loading && <p>Loading…</p>}
      {trajectory.error && <p className="error">{errorMessage(trajectory.error)}</p>}
      {trajectory.data && <TrajectoryChart trajectory={trajectory.data} />}
    </div>
  )
}

export default function Explorer({ route }: { route: string }) {
  const { id, epd } = parseRoute(route)
  const path =
    id !== null ? positionByIdPath(id) : epd !== null ? positionByEpdPath(epd) : null

  return (
    <div>
      <LookupForm initial={epd ?? (id !== null ? String(id) : '')} />
      {path ? (
        <PositionPanel path={path} key={path} />
      ) : (
        <p className="muted">Enter a position id or EPD to look it up.</p>
      )}
    </div>
  )
}

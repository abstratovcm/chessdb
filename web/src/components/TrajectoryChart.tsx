import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type DotItemDotProps,
} from 'recharts'
import { SCORE_KIND_MATE, type Trajectory } from '../api'
import { trajectoryToChartRows } from '../shape'

const LINE_COLORS = ['#5b4fc7', '#c0475a', '#2f9e6b', '#c8862f']
const MATE_DOT_RADIUS = 6
const NORMAL_DOT_RADIUS = 3

// Mates and big scores both clamp to ±1000, so mates get a bigger filled marker.
function mateAwareDot(engineId: number, color: string) {
  return ({ cx, cy, payload, index }: DotItemDotProps) => {
    if (cx === undefined || cy === undefined) return <g />
    const isMate = payload?.[`engine_${engineId}_mate`] === true
    return (
      <circle
        key={`dot-${engineId}-${index}`}
        cx={cx}
        cy={cy}
        r={isMate ? MATE_DOT_RADIUS : NORMAL_DOT_RADIUS}
        fill={color}
        stroke={color}
      />
    )
  }
}

function pointFor(trajectory: Trajectory, engineId: number, rung: number) {
  const engine = trajectory.engines.find((e) => e.engine_id === engineId)
  return engine?.series.find((p) => p.limit_value === rung)
}

function ChartTooltip({
  active,
  label,
  trajectory,
}: {
  active?: boolean
  label?: number
  trajectory: Trajectory
}) {
  if (!active || label === undefined) return null
  return (
    <div className="card tooltip">
      <p>
        <strong>nodes {label}</strong>
      </p>
      {trajectory.engines.map((e) => {
        const point = pointFor(trajectory, e.engine_id, label)
        if (!point) return null
        const mate = point.score_kind === SCORE_KIND_MATE
        return (
          <p key={e.engine_id}>
            engine {e.engine_id}: {mate ? `mate ${point.score}` : `${point.score}cp`}{' '}
            (depth {point.depth}, {point.bestmove ?? 'no move'})
          </p>
        )
      })}
    </div>
  )
}

export default function TrajectoryChart({ trajectory }: { trajectory: Trajectory }) {
  const rows = trajectoryToChartRows(trajectory)
  if (rows.length === 0) return <p className="muted">no NODES-ladder evals</p>

  return (
    <>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="rung" fontSize={11} />
          <YAxis domain={[-1000, 1000]} fontSize={11} />
          <Tooltip content={<ChartTooltip trajectory={trajectory} />} />
          <Legend />
          {trajectory.engines.map((e, i) => {
            const color = LINE_COLORS[i % LINE_COLORS.length]
            return (
              <Line
                key={e.engine_id}
                type="monotone"
                dataKey={`engine_${e.engine_id}`}
                name={`engine ${e.engine_id}`}
                stroke={color}
                dot={mateAwareDot(e.engine_id, color)}
                connectNulls
              />
            )
          })}
        </LineChart>
      </ResponsiveContainer>
      <p className="muted">larger filled point = mate</p>
    </>
  )
}

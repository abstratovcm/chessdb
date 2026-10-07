import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Distribution } from '../api'
import { bucketsToBarRows } from '../shape'

export default function Histogram({
  title,
  help,
  distribution,
}: {
  title: string
  help?: string
  distribution: Distribution
}) {
  const rows = bucketsToBarRows(distribution.buckets, distribution.width)

  return (
    <div className="card">
      <h2 title={help}>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted">no data</p>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" fontSize={11} />
            <YAxis allowDecimals={false} fontSize={11} />
            <Tooltip />
            <Bar dataKey="count" fill="var(--accent)" />
          </BarChart>
        </ResponsiveContainer>
      )}
      {distribution.null_count > 0 && (
        <p className="muted">{distribution.null_count} null (excluded)</p>
      )}
    </div>
  )
}

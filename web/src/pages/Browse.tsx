import { useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  COLUMN_GROUPS,
  DEFAULT_COLUMN_GROUPS,
  exportPath,
  metaPath,
  queryPath,
  type Meta,
  type QueryFilters,
  type QueryPage,
} from '../api'
import {
  decodeBrowseQuery,
  encodeBrowseQuery,
  filtersEqual,
  loadSavedFilters,
  saveSavedFilters,
  type BrowseQuery,
} from '../filters'
import { METRIC_HELP } from '../metricHelp'
import { navigate } from '../router'
import { isApiError, useApi } from '../useApi'

const APPLY_DEBOUNCE_MS = 400

const PAGE_SIZE = 50

function errorMessage(error: unknown): string {
  return isApiError(error) ? error.detail : (error as Error).message
}

function parseRoute(route: string): BrowseQuery {
  const [, search] = route.split('?')
  return decodeBrowseQuery(new URLSearchParams(search ?? ''))
}

function defaultMetricVersion(meta: Meta): number | undefined {
  return meta.metric_versions.length > 0 ? Math.max(...meta.metric_versions) : undefined
}

function goTo(query: BrowseQuery): void {
  navigate(`/browse?${encodeBrowseQuery(query).toString()}`)
}

const NUMERIC_FIELDS: { key: keyof QueryFilters; label: string }[] = [
  { key: 'min_sign_flips', label: 'min sign_flips' },
  { key: 'min_cp_range', label: 'min cp_range' },
  { key: 'max_settle_dev', label: 'max settle_dev' },
  { key: 'min_top_rung', label: 'min top_rung' },
  { key: 'min_mate_found_rung', label: 'min mate_found_rung' },
]

const SORTABLE_COLUMNS: { column: string; label: string }[] = [
  { column: 'position_id', label: 'position_id' },
  { column: 'epd', label: 'epd' },
  { column: 'top_rung', label: 'top_rung' },
  { column: 'sign_flips', label: 'sign_flips' },
  { column: 'cp_range', label: 'cp_range' },
  { column: 'settle_dev', label: 'settle_dev' },
  { column: 'version_disagreement', label: 'version_disagreement' },
  { column: 'mate_found_rung', label: 'mate_found_rung' },
]

function SortHeader({
  column,
  label,
  query,
}: {
  column: string
  label: string
  query: BrowseQuery
}) {
  const active = query.orderBy === column
  return (
    <th title={METRIC_HELP[column]}>
      <button
        type="button"
        className="link-btn"
        onClick={() =>
          goTo({
            filters: query.filters,
            orderBy: column,
            descending: active ? !query.descending : true,
          })
        }
      >
        {label}
        {active ? (query.descending ? ' ▼' : ' ▲') : ''}
      </button>
    </th>
  )
}

function NumberField({
  label,
  helpKey,
  value,
  onChange,
}: {
  label: string
  helpKey: string
  value: number | undefined
  onChange: (value: number | undefined) => void
}) {
  return (
    <label title={METRIC_HELP[helpKey]}>
      {label}{' '}
      <input
        type="number"
        size={8}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      />
    </label>
  )
}

function PredicateBuilder({
  meta,
  query,
}: {
  meta: Meta
  query: BrowseQuery
}) {
  const [form, setForm] = useState<QueryFilters>(query.filters)
  useEffect(() => setForm(query.filters), [query.filters])

  // Debounced auto-apply; the URL stays the source of truth. Skips when the form
  // already matches the route, to avoid a second navigation.
  useEffect(() => {
    if (filtersEqual(form, query.filters)) return
    const timer = setTimeout(() => {
      goTo({ filters: form, orderBy: query.orderBy, descending: query.descending })
    }, APPLY_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [form, query.filters, query.orderBy, query.descending])

  function submit(e: FormEvent) {
    e.preventDefault()
    goTo({ filters: form, orderBy: query.orderBy, descending: query.descending })
  }

  function reset() {
    setForm({})
    goTo({ filters: {}, orderBy: query.orderBy, descending: query.descending })
  }

  return (
    <form className="toolbar filters-grid" onSubmit={submit}>
      <label title={METRIC_HELP.metric_version}>
        metric_version{' '}
        <select
          value={form.metric_version ?? defaultMetricVersion(meta) ?? ''}
          onChange={(e) => setForm((f) => ({ ...f, metric_version: Number(e.target.value) }))}
        >
          {meta.metric_versions.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label title={METRIC_HELP.engine_id}>
        engine{' '}
        <select
          value={form.engine_id ?? ''}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              engine_id: e.target.value === '' ? undefined : Number(e.target.value),
            }))
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
      <label title={METRIC_HELP.has_mate}>
        has mate{' '}
        <select
          value={form.has_mate ?? ''}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              has_mate: e.target.value === '' ? undefined : Number(e.target.value),
            }))
          }
        >
          <option value="">any</option>
          <option value="1">yes</option>
          <option value="0">no</option>
        </select>
      </label>
      {NUMERIC_FIELDS.map(({ key, label }) => (
        <NumberField
          key={key}
          label={label}
          helpKey={key}
          value={form[key]}
          onChange={(value) => setForm((f) => ({ ...f, [key]: value }))}
        />
      ))}
      <button type="button" onClick={reset}>
        Reset
      </button>
    </form>
  )
}

function SavedFiltersToolbar({ query }: { query: BrowseQuery }) {
  const [saved, setSaved] = useState<Record<string, QueryFilters>>(() =>
    loadSavedFilters(window.localStorage),
  )
  const [name, setName] = useState('')
  const [selected, setSelected] = useState('')
  const names = Object.keys(saved)

  function persist(next: Record<string, QueryFilters>) {
    saveSavedFilters(window.localStorage, next)
    setSaved(next)
  }

  return (
    <div className="toolbar">
      <input
        placeholder="filter set name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <button
        type="button"
        disabled={!name.trim()}
        onClick={() => {
          persist({ ...saved, [name.trim()]: query.filters })
          setName('')
        }}
      >
        Save current
      </button>
      <label>
        saved{' '}
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">choose…</option>
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={!selected}
        onClick={() => goTo({ filters: saved[selected], descending: false })}
      >
        Load
      </button>
      <button
        type="button"
        disabled={!selected}
        onClick={() => {
          const next = { ...saved }
          delete next[selected]
          persist(next)
          setSelected('')
        }}
      >
        Delete
      </button>
    </div>
  )
}

function ExportBar({
  filters,
  total,
}: {
  filters: QueryFilters
  total: number | undefined
}) {
  const [groups, setGroups] = useState<string[]>([...DEFAULT_COLUMN_GROUPS])

  function toggle(group: string) {
    setGroups((prev) =>
      prev.includes(group) ? prev.filter((g) => g !== group) : [...prev, group],
    )
  }

  return (
    <div className="toolbar">
      <div className="checkbox-group">
        {COLUMN_GROUPS.map((group) => (
          <label key={group}>
            <input
              type="checkbox"
              checked={groups.includes(group)}
              onChange={() => toggle(group)}
            />{' '}
            {group}
          </label>
        ))}
      </div>
      <a
        href={exportPath(filters, groups.join(','))}
        download="chessdb-export.parquet"
        aria-disabled={groups.length === 0}
      >
        Download parquet ({total ?? '…'} rows)
      </a>
    </div>
  )
}

export function ResultsTable({ page, query }: { page: QueryPage; query: BrowseQuery }) {
  const byKey = Object.fromEntries(SORTABLE_COLUMNS.map((c) => [c.column, c]))
  return (
    <table>
      <thead>
        <tr>
          <SortHeader {...byKey.position_id} query={query} />
          <SortHeader {...byKey.epd} query={query} />
          <th>engine</th>
          <SortHeader {...byKey.top_rung} query={query} />
          <SortHeader {...byKey.sign_flips} query={query} />
          <SortHeader {...byKey.cp_range} query={query} />
          <SortHeader {...byKey.settle_dev} query={query} />
          <SortHeader {...byKey.version_disagreement} query={query} />
          <SortHeader {...byKey.mate_found_rung} query={query} />
        </tr>
      </thead>
      <tbody>
        {page.rows.map((row, i) => (
          <tr key={i}>
            <td>
              <a href={`#/position/${row.position_id}`}>{row.position_id}</a>
            </td>
            <td className="mono">{row.epd}</td>
            <td>
              {row.engine_name} {row.engine_version}
            </td>
            <td>{row.top_rung}</td>
            <td>{row.sign_flips}</td>
            <td>{row.cp_range}</td>
            <td>{row.settle_dev}</td>
            <td>{row.version_disagreement ?? '—'}</td>
            <td>{row.mate_found_rung ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function Browse({ route }: { route: string }) {
  const { data: meta, loading: metaLoading, error: metaError } = useApi<Meta>(metaPath())
  const query = useMemo(() => parseRoute(route), [route])
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [route])

  const metricVersion = query.filters.metric_version ?? (meta && defaultMetricVersion(meta))
  const effectiveFilters: QueryFilters | null =
    metricVersion === undefined || metricVersion === null
      ? null
      : { ...query.filters, metric_version: metricVersion }

  const path = effectiveFilters
    ? queryPath(effectiveFilters, PAGE_SIZE, offset, query.orderBy, query.descending)
    : null
  const { data, loading, error } = useApi<QueryPage>(path)

  if (metaLoading) return <p>Loading…</p>
  if (metaError) return <p className="error">{errorMessage(metaError)}</p>
  if (!meta || !effectiveFilters) return <p>Loading…</p>

  return (
    <div>
      <PredicateBuilder meta={meta} query={query} />
      <SavedFiltersToolbar query={{ ...query, filters: effectiveFilters }} />
      <ExportBar filters={effectiveFilters} total={data?.total} />

      {loading && <p>Loading…</p>}
      {error && <p className="error">{errorMessage(error)}</p>}
      {data && (
        <>
          <p className="muted">
            {data.total === 0
              ? 'no rows'
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, data.total)} of ${data.total}`}
          </p>
          <ResultsTable page={data} query={query} />
          <div className="toolbar">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  )
}

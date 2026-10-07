"""Query builders for the DuckDB listing and distribution endpoints. Filters
share metric_where with db/export.py so the API and the CLI always agree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chessdb.db.export import ExportError, MetricFilters, int_literal, metric_where
from chessdb.db.model import LimitKind, ScoreKind

_PAGE_COLUMNS = (
    ("position_id", "p.id"),
    ("epd", "p.epd"),
    ("engine_id", "pm.engine_id"),
    ("engine_name", "e.name"),
    ("engine_version", "e.version"),
    ("metric_version", "pm.metric_version"),
    ("top_rung", "pm.top_rung"),
    ("sign_flips", "pm.sign_flips"),
    ("cp_range", "pm.cp_range"),
    ("settle_dev", "pm.settle_dev"),
    ("version_disagreement", "pm.version_disagreement"),
    ("mate_found_rung", "pm.mate_found_rung"),
)

_PAGE_COLUMN_EXPR: dict[str, str] = dict(_PAGE_COLUMNS)
_PAGE_TIEBREAKERS = "p.id, pm.engine_id, pm.metric_version"

# Default bucket width is 1 for counts and 50 for centipawn metrics.
DISTRIBUTION_METRICS: dict[str, str] = {
    "top_rung": "pm.top_rung",
    "sign_flips": "pm.sign_flips",
    "cp_range": "pm.cp_range",
    "settle_dev": "pm.settle_dev",
    "version_disagreement": "pm.version_disagreement",
}

DEFAULT_DISTRIBUTION_WIDTH: dict[str, int] = {
    "top_rung": 1,
    "sign_flips": 1,
    "cp_range": 50,
    "settle_dev": 50,
    "version_disagreement": 50,
}


@dataclass(frozen=True)
class QuerySpec:
    filters: MetricFilters
    limit: int
    offset: int = 0
    order_by: str | None = None
    descending: bool = False


def _order_by_sql(order_by: str | None, descending: bool) -> str:
    """Whitelisted sort column (validated against _PAGE_COLUMNS' output
    names) leads; the id/engine/metric_version tiebreakers always follow
    so pagination stays stable regardless of the chosen column."""
    if order_by is None:
        return _PAGE_TIEBREAKERS
    if order_by not in _PAGE_COLUMN_EXPR:
        raise ExportError(
            f"unknown order_by column: {order_by!r} "
            f"(choices: {', '.join(_PAGE_COLUMN_EXPR)})"
        )
    direction = "DESC" if descending else "ASC"
    return f"{_PAGE_COLUMN_EXPR[order_by]} {direction}, {_PAGE_TIEBREAKERS}"


def build_position_page_query(spec: QuerySpec) -> tuple[str, tuple[str, ...]]:
    """positions ⋈ position_metrics ⋈ engines, filtered and paginated. Lighter
    than build_export_query, which has no OFFSET."""
    where_sql = " AND ".join(metric_where(spec.filters))
    select_sql = ",\n  ".join(f"{expr} AS {name}" for name, expr in _PAGE_COLUMNS)
    order_sql = _order_by_sql(spec.order_by, spec.descending)
    query = (
        f"SELECT\n  {select_sql}\n"
        "FROM src.positions p\n"
        "JOIN src.position_metrics pm ON pm.position_id = p.id\n"
        "JOIN src.engines e ON e.id = pm.engine_id\n"
        f"WHERE {where_sql}\n"
        f"ORDER BY {order_sql}\n"
        f"LIMIT {int_literal(spec.limit)} OFFSET {int_literal(spec.offset)}"
    )
    return query, tuple(name for name, _ in _PAGE_COLUMNS)


def build_count_query(spec: QuerySpec) -> str:
    where_sql = " AND ".join(metric_where(spec.filters))
    return (
        "SELECT COUNT(pm.position_id)\n"
        "FROM src.positions p\n"
        "JOIN src.position_metrics pm ON pm.position_id = p.id\n"
        f"WHERE {where_sql}"
    )


def _distribution_column(metric: str) -> str:
    if metric not in DISTRIBUTION_METRICS:
        raise ExportError(
            f"unknown metric: {metric!r} (choices: {', '.join(DISTRIBUTION_METRICS)})"
        )
    return DISTRIBUTION_METRICS[metric]


def default_distribution_width(metric: str) -> int:
    _distribution_column(metric)  # validates; raises ExportError if unknown
    return DEFAULT_DISTRIBUTION_WIDTH[metric]


def build_distribution_query(
    metric: str, metric_version: int, width: int, engine_id: int | None = None
) -> str:
    """Fixed-width buckets over a validated metric column, excluding
    NULLs (see build_distribution_null_count_query)."""
    col = _distribution_column(metric)
    w = int_literal(width)
    if w <= 0:
        raise ExportError(f"width must be positive, got {w}")
    where = [
        f"pm.metric_version = {int_literal(metric_version)}",
        f"{col} IS NOT NULL",
    ]
    if engine_id is not None:
        where.append(f"pm.engine_id = {int_literal(engine_id)}")
    where_sql = " AND ".join(where)
    return (
        f"SELECT ({col} // {w}) * {w} AS start, COUNT(*) AS count\n"
        "FROM src.position_metrics pm\n"
        f"WHERE {where_sql}\n"
        "GROUP BY 1\nORDER BY 1"
    )


def build_distribution_null_count_query(
    metric: str, metric_version: int, engine_id: int | None = None
) -> str:
    col = _distribution_column(metric)
    where = [f"pm.metric_version = {int_literal(metric_version)}", f"{col} IS NULL"]
    if engine_id is not None:
        where.append(f"pm.engine_id = {int_literal(engine_id)}")
    where_sql = " AND ".join(where)
    return (
        f"SELECT COUNT(pm.position_id)\nFROM src.position_metrics pm\nWHERE {where_sql}"
    )


@dataclass(frozen=True)
class DepthByRungRow:
    engine_id: int
    engine_name: str
    engine_version: str
    limit_value: int
    n: int
    avg_depth: float
    min_depth: int
    avg_seldepth: float | None
    mate_count: int


def build_depth_by_rung_query() -> str:
    """Eval count, depth stats and mate count per (engine, NODES rung)."""
    return (
        "SELECT\n"
        "  e.id AS engine_id,\n"
        "  e.name AS engine_name,\n"
        "  e.version AS engine_version,\n"
        "  ev.limit_value AS limit_value,\n"
        "  COUNT(*) AS n,\n"
        "  AVG(ev.depth) AS avg_depth,\n"
        "  MIN(ev.depth) AS min_depth,\n"
        "  AVG(ev.seldepth) AS avg_seldepth,\n"
        f"  SUM(CASE WHEN ev.score_kind = {int(ScoreKind.MATE)} THEN 1 ELSE 0 END)"
        " AS mate_count\n"
        "FROM src.evals ev\n"
        "JOIN src.engines e ON e.id = ev.engine_id\n"
        f"WHERE ev.limit_kind = {int(LimitKind.NODES)}\n"
        "GROUP BY e.id, e.name, e.version, ev.limit_value\n"
        "ORDER BY e.id, ev.limit_value"
    )


def depth_by_rung(conn: Any) -> list[DepthByRungRow]:
    rows = conn.execute(build_depth_by_rung_query()).fetchall()
    return [DepthByRungRow(*row) for row in rows]

"""Parquet export through a read-only DuckDB attach of the SQLite file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chessdb.db.model import LimitKind, ScoreKind
from chessdb.engine.ladder import NODE_LADDER
from chessdb.metrics.instability import CLAMP

_CORE_COLUMNS = (
    ("epd", "p.epd"),
    ("source_game_id", "p.source_game_id"),
    ("source_ply", "p.source_ply"),
    ("engine_name", "e.name"),
    ("engine_version", "e.version"),
)

_METRICS_COLUMNS = (
    ("top_rung", "pm.top_rung"),
    ("sign_flips", "pm.sign_flips"),
    ("cp_range", "pm.cp_range"),
    ("settle_dev", "pm.settle_dev"),
    ("version_disagreement", "pm.version_disagreement"),
    ("mate_found_rung", "pm.mate_found_rung"),
)


def _rung_columns(prefix: str) -> tuple[tuple[str, str], ...]:
    return tuple((f"{prefix}_{rung}", f"piv.{prefix}_{rung}") for rung in NODE_LADDER)


_CP_COLUMNS = _rung_columns("cp")
_BESTMOVE_COLUMNS = _rung_columns("bestmove")
_ACTUALS_COLUMNS = _rung_columns("depth")
_RAW_COLUMNS = tuple(
    col
    for rung in NODE_LADDER
    for col in (
        (f"score_kind_{rung}", f"piv.score_kind_{rung}"),
        (f"score_{rung}", f"piv.score_{rung}"),
    )
)

# Exports select named column groups, never single columns.
COLUMN_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "core": _CORE_COLUMNS,
    "metrics": _METRICS_COLUMNS,
    "cp": _CP_COLUMNS,
    "raw": _RAW_COLUMNS,
    "bestmove": _BESTMOVE_COLUMNS,
    "actuals": _ACTUALS_COLUMNS,
}

DEFAULT_COLUMN_GROUPS: tuple[str, ...] = ("core", "metrics", "cp")

# Grain keys are always emitted regardless of the requested column groups.
GRAIN_COLUMNS = (
    ("position_id", "p.id"),
    ("engine_id", "pm.engine_id"),
    ("metric_version", "pm.metric_version"),
)

CLAMP_BOUND = CLAMP


class ExportError(ValueError):
    """User-facing export or query error. Never SystemExit, which would kill
    the server thread inside an API request handler."""


class AttachError(ExportError):
    """DuckDB could not attach the SQLite file (missing duckdb, extension
    download, corrupt file). The API answers 503 here and 400 otherwise."""


@dataclass(frozen=True)
class MetricFilters:
    metric_version: int
    engine_id: int | None = None
    min_sign_flips: int | None = None
    min_cp_range: int | None = None
    max_settle_dev: int | None = None
    min_top_rung: int | None = None
    has_mate: int | None = None
    min_mate_found_rung: int | None = None


def metric_where(filters: MetricFilters) -> list[str]:
    where = [f"pm.metric_version = {int_literal(filters.metric_version)}"]
    if filters.engine_id is not None:
        where.append(f"pm.engine_id = {int_literal(filters.engine_id)}")
    if filters.min_sign_flips is not None:
        where.append(f"pm.sign_flips >= {int_literal(filters.min_sign_flips)}")
    if filters.min_cp_range is not None:
        where.append(f"pm.cp_range >= {int_literal(filters.min_cp_range)}")
    if filters.max_settle_dev is not None:
        where.append(f"pm.settle_dev <= {int_literal(filters.max_settle_dev)}")
    if filters.min_top_rung is not None:
        where.append(f"pm.top_rung >= {int_literal(filters.min_top_rung)}")
    if filters.has_mate is not None:
        if int_literal(filters.has_mate) not in (0, 1):
            raise ExportError(f"has_mate must be 0 or 1, got {filters.has_mate}")
        where.append(
            "pm.mate_found_rung IS NOT NULL"
            if filters.has_mate == 1
            else "pm.mate_found_rung IS NULL"
        )
    if filters.min_mate_found_rung is not None:
        where.append(
            f"pm.mate_found_rung >= {int_literal(filters.min_mate_found_rung)}"
        )
    return where


@dataclass(frozen=True)
class ExportSpec:
    db: Path
    out: Path
    force: bool
    column_groups: tuple[str, ...]
    filters: MetricFilters
    limit: int | None = None


def attach_readonly(path: Path):
    try:
        import duckdb
    except ImportError as exc:
        raise AttachError(
            "duckdb not installed — pip install 'chessdb[site]' "
            "(or: uv sync --extra site)"
        ) from exc
    conn = duckdb.connect(":memory:")
    quoted = str(path).replace("'", "''")
    try:
        conn.execute(f"ATTACH '{quoted}' AS src (TYPE sqlite, READ_ONLY)")
    except duckdb.Error as exc:
        conn.close()
        raise AttachError(
            "duckdb could not attach the sqlite file read-only — the "
            "'sqlite_scanner' extension auto-installs from the network on "
            f"first use; check connectivity: {exc}"
        ) from exc
    return conn


def int_literal(value: int) -> int:
    if not isinstance(value, int):
        raise TypeError(f"filter value must be int, got {type(value)!r}")
    return value


_int_literal = int_literal


def _clamp_sql(score_kind_col: str, score_col: str) -> str:
    """Mirrors metrics.instability.clamp_score: mate -> +-CLAMP_BOUND, cp
    clipped to [-CLAMP_BOUND, CLAMP_BOUND]."""
    return (
        f"CASE WHEN {score_kind_col} = {int(ScoreKind.MATE)} THEN "
        f"(CASE WHEN {score_col} > 0 THEN {CLAMP_BOUND} ELSE -{CLAMP_BOUND} END) "
        f"ELSE LEAST({CLAMP_BOUND}, GREATEST(-{CLAMP_BOUND}, {score_col})) END"
    )


def _pivot_cte_sql() -> str:
    exprs = [
        f"MAX(CASE WHEN limit_value = {rung} THEN "
        f"{_clamp_sql('score_kind', 'score')} END) AS cp_{rung}"
        for rung in NODE_LADDER
    ]
    for rung in NODE_LADDER:
        exprs.append(
            f"MAX(CASE WHEN limit_value = {rung} THEN score_kind END) "
            f"AS score_kind_{rung}"
        )
        exprs.append(
            f"MAX(CASE WHEN limit_value = {rung} THEN score END) AS score_{rung}"
        )
    exprs += [
        f"MAX(CASE WHEN limit_value = {rung} THEN bestmove END) AS bestmove_{rung}"
        for rung in NODE_LADDER
    ]
    exprs += [
        f"MAX(CASE WHEN limit_value = {rung} THEN depth END) AS depth_{rung}"
        for rung in NODE_LADDER
    ]
    rungs_csv = ", ".join(str(r) for r in NODE_LADDER)
    columns_sql = ",\n      ".join(exprs)
    return (
        "  SELECT position_id, engine_id,\n      "
        f"{columns_sql}\n"
        "  FROM src.evals\n"
        f"  WHERE limit_kind = {int(LimitKind.NODES)} AND limit_value IN ({rungs_csv})\n"
        "  GROUP BY position_id, engine_id"
    )


def _selected_columns(column_groups: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    unknown = [g for g in column_groups if g not in COLUMN_GROUPS]
    if unknown:
        raise ExportError(
            f"unknown --columns group(s): {', '.join(unknown)} "
            f"(choices: {', '.join(COLUMN_GROUPS)})"
        )
    return GRAIN_COLUMNS + tuple(
        col
        for group in COLUMN_GROUPS
        if group in column_groups
        for col in COLUMN_GROUPS[group]
    )


def build_export_query(spec: ExportSpec) -> tuple[str, tuple[str, ...]]:
    """Builds the DuckDB SELECT for `spec`. Values are inlined because COPY cannot
    bind parameters; filters are checked ints and rungs are constants."""
    selected = _selected_columns(spec.column_groups)
    select_sql = ",\n  ".join(f"{expr} AS {name}" for name, expr in selected)

    where_sql = " AND ".join(metric_where(spec.filters))

    limit_sql = f"\nLIMIT {int_literal(spec.limit)}" if spec.limit is not None else ""

    query = (
        f"WITH piv AS (\n{_pivot_cte_sql()}\n)\n"
        f"SELECT\n  {select_sql}\n"
        "FROM src.positions p\n"
        "JOIN src.position_metrics pm ON pm.position_id = p.id\n"
        "JOIN src.engines e ON e.id = pm.engine_id\n"
        "LEFT JOIN piv ON piv.position_id = p.id AND piv.engine_id = pm.engine_id\n"
        f"WHERE {where_sql}\n"
        "ORDER BY p.id, pm.engine_id, pm.metric_version"
        f"{limit_sql}"
    )
    return query, tuple(name for name, _ in selected)


def run_export(spec: ExportSpec) -> tuple[int, tuple[str, ...]]:
    if spec.out.exists() and not spec.force:
        raise ExportError(
            f"--out already exists (use --force to overwrite): {spec.out}"
        )
    query, columns = build_export_query(spec)
    conn = attach_readonly(spec.db)
    try:
        out_quoted = str(spec.out).replace("'", "''")
        (rows,) = conn.execute(
            f"COPY ({query}) TO '{out_quoted}' (FORMAT parquet)"
        ).fetchone()
    finally:
        conn.close()
    return rows, columns

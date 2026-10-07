"""Read-only FastAPI app factory.

Startup validates the DB so a bad file fails at serve time, not on the first request.
"""

import os
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
from typing import Annotated, TypeAlias

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from chessdb.db import connect_readonly
from chessdb.db.api import (
    count_rows,
    distinct_metric_versions,
    evals_for_position,
    get_position,
    get_position_by_id,
    list_engines,
    metrics_for_position,
    schema_version,
)
from chessdb.db.export import (
    DEFAULT_COLUMN_GROUPS,
    AttachError,
    ExportError,
    ExportSpec,
    MetricFilters,
    attach_readonly,
    run_export,
)
from chessdb.db.model import LimitKind, normalize_epd
from chessdb.db.query import (
    DepthByRungRow,
    QuerySpec,
    build_count_query,
    build_distribution_null_count_query,
    build_distribution_query,
    build_position_page_query,
    default_distribution_width,
    depth_by_rung,
)
from chessdb.metrics import METRIC_VERSION
from chessdb.metrics.instability import clamp_score

_MIN_SCHEMA_VERSION = 2
_COUNTED_TABLES = ("engines", "games", "positions", "evals", "position_metrics")
_QUERY_LIMIT_CAP = 500


def _serialize_position(position) -> dict:
    return {
        "id": position.id,
        "epd": position.epd,
        "source_game_id": position.source_game_id,
        "source_ply": position.source_ply,
    }


def _serialize_eval(row) -> dict:
    return {
        "engine_id": row.engine_id,
        "limit_kind": int(row.limit_kind),
        "limit_value": row.limit_value,
        "score_kind": int(row.score_kind),
        "score": row.score,
        "depth": row.depth,
        "seldepth": row.seldepth,
        "nodes": row.nodes,
        "time_ms": row.time_ms,
        "bestmove": row.bestmove,
    }


def _serialize_metrics(row) -> dict:
    return {
        "engine_id": row.engine_id,
        "metric_version": row.metric_version,
        "top_rung": row.top_rung,
        "sign_flips": row.sign_flips,
        "cp_range": row.cp_range,
        "settle_dev": row.settle_dev,
        "version_disagreement": row.version_disagreement,
        "mate_found_rung": row.mate_found_rung,
    }


def _serialize_depth_by_rung(row: DepthByRungRow) -> dict:
    return {
        "engine_id": row.engine_id,
        "engine_name": row.engine_name,
        "engine_version": row.engine_version,
        "limit_value": row.limit_value,
        "n": row.n,
        "avg_depth": row.avg_depth,
        "min_depth": row.min_depth,
        "avg_seldepth": row.avg_seldepth,
        "mate_count": row.mate_count,
    }


def _serialize_engine(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "binary_sha256": row.binary_sha256,
        "threads": row.threads,
        "hash_mb": row.hash_mb,
        "options_json": row.options_json,
    }


def _position_detail(conn: sqlite3.Connection, position) -> dict:
    return {
        "position": _serialize_position(position),
        "evals": [_serialize_eval(e) for e in evals_for_position(conn, position.id)],
        "metrics": [
            _serialize_metrics(m) for m in metrics_for_position(conn, position.id)
        ],
    }


def _validate_startup(db_path: Path) -> None:
    if not db_path.exists():
        raise SystemExit(f"--db does not exist: {db_path}")
    try:
        probe = connect_readonly(db_path)
        try:
            probe.execute("SELECT 1").fetchone()
            version = schema_version(probe)
            # position_metrics only exists from _MIN_SCHEMA_VERSION on.
            metrics_rows = (
                count_rows(probe, "position_metrics")
                if version >= _MIN_SCHEMA_VERSION
                else None
            )
        finally:
            probe.close()
    except sqlite3.Error as exc:
        raise SystemExit(f"could not open --db read-only: {exc}") from exc
    if version < _MIN_SCHEMA_VERSION:
        raise SystemExit(
            f"--db schema_version={version} is pre-metrics (need >= "
            f"{_MIN_SCHEMA_VERSION}) — run `chessdb metrics` first"
        )
    if metrics_rows == 0:
        print(
            f"warning: --db {db_path} has an empty position_metrics table; "
            "run `chessdb metrics` on it before serving",
            file=sys.stderr,
        )


def _validate_web_dist(web_dist: Path) -> None:
    if not web_dist.is_dir():
        raise SystemExit(f"--web-dist is not a directory: {web_dist}")
    if not (web_dist / "index.html").is_file():
        raise SystemExit(f"--web-dist has no index.html: {web_dist}")


def create_app(db_path: Path, web_dist: Path | None = None) -> FastAPI:
    _validate_startup(db_path)
    if web_dist is not None:
        _validate_web_dist(web_dist)
    try:
        duck = attach_readonly(db_path)
    except ExportError as exc:
        raise SystemExit(str(exc)) from exc

    app = FastAPI(title="chessdb")
    app.state.db_path = db_path
    app.state.duckdb_conn = duck
    app.state.duckdb_lock = threading.Lock()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def sqlite_conn():
        conn = connect_readonly(db_path)
        try:
            yield conn
        finally:
            conn.close()

    SqliteConn: TypeAlias = Annotated[sqlite3.Connection, Depends(sqlite_conn)]

    @app.get("/api/meta")
    def meta(conn: SqliteConn) -> dict:
        return {
            "schema_version": schema_version(conn),
            "row_counts": {t: count_rows(conn, t) for t in _COUNTED_TABLES},
            "engines": [_serialize_engine(e) for e in list_engines(conn)],
            "metric_versions": distinct_metric_versions(conn),
        }

    @app.get("/api/positions/by-epd")
    def position_by_epd(epd: str, conn: SqliteConn) -> dict:
        try:
            normalized = normalize_epd(epd)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        position = get_position(conn, normalized)
        if position is None:
            raise HTTPException(404, "position not found")
        return _position_detail(conn, position)

    @app.get("/api/positions/{position_id}")
    def position_by_id(position_id: int, conn: SqliteConn) -> dict:
        position = get_position_by_id(conn, position_id)
        if position is None:
            raise HTTPException(404, "position not found")
        return _position_detail(conn, position)

    @app.get("/api/positions/{position_id}/trajectory")
    def trajectory(position_id: int, conn: SqliteConn) -> dict:
        position = get_position_by_id(conn, position_id)
        if position is None:
            raise HTTPException(404, "position not found")
        by_engine: dict[int, list[dict]] = {}
        for row in evals_for_position(conn, position_id):
            if row.limit_kind != LimitKind.NODES:
                continue
            by_engine.setdefault(row.engine_id, []).append(
                {
                    "limit_value": row.limit_value,
                    "score_kind": int(row.score_kind),
                    "score": row.score,
                    "clamped": clamp_score(row.score_kind, row.score),
                    "depth": row.depth,
                    "bestmove": row.bestmove,
                }
            )
        return {
            "position_id": position_id,
            "engines": [
                {"engine_id": engine_id, "series": series}
                for engine_id, series in sorted(by_engine.items())
            ],
        }

    @app.get("/api/query")
    def query_positions(
        metric_version: int = METRIC_VERSION,
        engine_id: int | None = None,
        min_sign_flips: int | None = None,
        min_cp_range: int | None = None,
        max_settle_dev: int | None = None,
        min_top_rung: int | None = None,
        has_mate: int | None = None,
        min_mate_found_rung: int | None = None,
        order_by: str | None = None,
        descending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        limit = max(1, min(limit, _QUERY_LIMIT_CAP))
        offset = max(0, offset)
        spec = QuerySpec(
            filters=MetricFilters(
                metric_version=metric_version,
                engine_id=engine_id,
                min_sign_flips=min_sign_flips,
                min_cp_range=min_cp_range,
                max_settle_dev=max_settle_dev,
                min_top_rung=min_top_rung,
                has_mate=has_mate,
                min_mate_found_rung=min_mate_found_rung,
            ),
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
        )
        try:
            page_query, columns = build_position_page_query(spec)
            count_query = build_count_query(spec)
        except ExportError as exc:
            raise HTTPException(400, str(exc)) from exc
        with app.state.duckdb_lock:
            rows = app.state.duckdb_conn.execute(page_query).fetchall()
            total = app.state.duckdb_conn.execute(count_query).fetchone()[0]
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "rows": [dict(zip(columns, row, strict=True)) for row in rows],
        }

    @app.get("/api/depth-by-rung")
    def depth_by_rung_endpoint() -> dict:
        with app.state.duckdb_lock:
            rows = depth_by_rung(app.state.duckdb_conn)
        return {"rows": [_serialize_depth_by_rung(r) for r in rows]}

    @app.get("/api/distributions")
    def distributions(
        metric: str,
        metric_version: int,
        engine_id: int | None = None,
        width: int | None = None,
    ) -> dict:
        try:
            w = width if width is not None else default_distribution_width(metric)
            bucket_query = build_distribution_query(
                metric, metric_version, w, engine_id
            )
            null_query = build_distribution_null_count_query(
                metric, metric_version, engine_id
            )
        except ExportError as exc:
            raise HTTPException(400, str(exc)) from exc
        with app.state.duckdb_lock:
            buckets = app.state.duckdb_conn.execute(bucket_query).fetchall()
            null_count = app.state.duckdb_conn.execute(null_query).fetchone()[0]
        return {
            "metric": metric,
            "width": w,
            "buckets": [{"start": start, "count": count} for start, count in buckets],
            "null_count": null_count,
        }

    @app.get("/api/export")
    def export_positions(
        metric_version: int = METRIC_VERSION,
        engine_id: int | None = None,
        min_sign_flips: int | None = None,
        min_cp_range: int | None = None,
        max_settle_dev: int | None = None,
        min_top_rung: int | None = None,
        has_mate: int | None = None,
        min_mate_found_rung: int | None = None,
        columns: str = ",".join(DEFAULT_COLUMN_GROUPS),
        limit: int | None = None,
    ) -> FileResponse:
        fd, tmp_name = tempfile.mkstemp(suffix=".parquet")
        os.close(fd)
        out_path = Path(tmp_name)
        spec = ExportSpec(
            db=db_path,
            out=out_path,
            force=True,
            column_groups=tuple(g.strip() for g in columns.split(",") if g.strip()),
            filters=MetricFilters(
                metric_version=metric_version,
                engine_id=engine_id,
                min_sign_flips=min_sign_flips,
                min_cp_range=min_cp_range,
                max_settle_dev=max_settle_dev,
                min_top_rung=min_top_rung,
                has_mate=has_mate,
                min_mate_found_rung=min_mate_found_rung,
            ),
            limit=limit,
        )
        try:
            run_export(spec)
        except AttachError as exc:
            out_path.unlink(missing_ok=True)
            raise HTTPException(503, str(exc)) from exc
        except ExportError as exc:
            out_path.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        return FileResponse(
            out_path,
            filename="chessdb-export.parquet",
            background=BackgroundTask(os.remove, out_path),
        )

    if web_dist is not None:
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app

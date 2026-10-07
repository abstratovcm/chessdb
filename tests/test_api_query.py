"""DuckDB backed endpoints (/api/query, /api/distributions, /api/export) over a
hand-built DB. Skips without fastapi, httpx or a working DuckDB attach."""

import os
import tempfile

import chess
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
duckdb = pytest.importorskip("duckdb")

from fastapi.testclient import TestClient

from chessdb.api.app import create_app
from chessdb.db import connect
from chessdb.db.api import (
    ensure_engine,
    ensure_position,
    replace_position_metrics,
)
from chessdb.db.model import EngineSpec, PositionMetricsRow, normalize_epd

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_OPENING_MOVES = ("e2e4", "d2d4", "g1f3", "c2c4", "b1c3")

# (sign_flips, cp_range, settle_dev, top_rung, version_disagreement, mate_found_rung)
_ROWS = (
    (0, 10, 5, 1_000, None, None),
    (1, 20, 15, 1_000, 5, None),
    (2, 30, 25, 4_000, None, 4_000),
    (0, 40, 35, 4_000, 10, None),
    (1, 50, 45, 16_000, None, 16_000),
    (3, 60, 55, 16_000, 15, 1_000),
)


def _epd_variant(i):
    board = chess.Board(START_FEN)
    if i > 0:
        board.push_uci(_OPENING_MOVES[i - 1])
    return board.epd()


def _write_temp_parquet(content):
    fd, path = tempfile.mkstemp(suffix=".parquet")
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


def _build_db(db_path):
    conn = connect(db_path)
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="a" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    position_ids = []
    for i, (
        sign_flips,
        cp_range,
        settle_dev,
        top_rung,
        disagreement,
        mate_found_rung,
    ) in enumerate(_ROWS):
        position_id = ensure_position(conn, normalize_epd(_epd_variant(i)))
        position_ids.append(position_id)
        replace_position_metrics(
            conn,
            [
                PositionMetricsRow(
                    position_id=position_id,
                    engine_id=engine_id,
                    metric_version=1,
                    top_rung=top_rung,
                    sign_flips=sign_flips,
                    cp_range=cp_range,
                    settle_dev=settle_dev,
                    version_disagreement=disagreement,
                    mate_found_rung=mate_found_rung,
                )
            ],
        )
    conn.commit()
    conn.close()
    return {"engine_id": engine_id, "position_ids": position_ids}


@pytest.fixture
def client_and_ids(tmp_path, duckdb_sqlite_attach):
    db_path = tmp_path / "x.db"
    ids = _build_db(db_path)
    app = create_app(db_path)
    return TestClient(app), ids


def test_query_pagination_determinism(client_and_ids):
    client, _ids = client_and_ids
    full = client.get("/api/query", params={"limit": 500}).json()["rows"]
    assert len(full) == 6

    page1 = client.get("/api/query", params={"limit": 2, "offset": 0}).json()["rows"]
    page2 = client.get("/api/query", params={"limit": 2, "offset": 2}).json()["rows"]
    page3 = client.get("/api/query", params={"limit": 2, "offset": 4}).json()["rows"]
    assert page1 + page2 + page3 == full


def test_query_total_matches_export_row_count_same_flags(client_and_ids):
    client, _ids = client_and_ids
    body = client.get("/api/query", params={"min_sign_flips": 1}).json()
    assert body["total"] == 4

    resp = client.get("/api/export", params={"min_sign_flips": 1})
    assert resp.status_code == 200
    path = _write_temp_parquet(resp.content)
    con = duckdb.connect(":memory:")
    try:
        [(count,)] = con.execute(f"SELECT COUNT(*) FROM '{path}'").fetchall()
    finally:
        con.close()
    assert count == body["total"]


def test_query_order_by_sign_flips_ascending(client_and_ids):
    client, _ids = client_and_ids
    body = client.get(
        "/api/query", params={"limit": 500, "order_by": "sign_flips"}
    ).json()
    assert [row["sign_flips"] for row in body["rows"]] == [0, 0, 1, 1, 2, 3]


def test_query_order_by_unknown_column_returns_400(client_and_ids):
    client, _ids = client_and_ids
    resp = client.get("/api/query", params={"order_by": "bogus"})
    assert resp.status_code == 400


def test_query_order_by_version_disagreement_descending_nulls_last(client_and_ids):
    client, _ids = client_and_ids
    body = client.get(
        "/api/query",
        params={"limit": 500, "order_by": "version_disagreement", "descending": True},
    ).json()
    disagreements = [row["version_disagreement"] for row in body["rows"]]
    # real values first in DESC order, nulls last
    assert disagreements == [15, 10, 5, None, None, None]


def test_query_has_mate_filters_and_round_trips_through_export(client_and_ids):
    client, _ids = client_and_ids
    body = client.get("/api/query", params={"has_mate": 1, "limit": 500}).json()
    assert body["total"] == 3
    assert all(row["mate_found_rung"] is not None for row in body["rows"])

    resp = client.get("/api/export", params={"has_mate": 1})
    assert resp.status_code == 200
    path = _write_temp_parquet(resp.content)
    con = duckdb.connect(":memory:")
    try:
        [(count,)] = con.execute(f"SELECT COUNT(*) FROM '{path}'").fetchall()
    finally:
        con.close()
    assert count == body["total"]


def test_query_has_mate_zero_is_null(client_and_ids):
    client, _ids = client_and_ids
    body = client.get("/api/query", params={"has_mate": 0, "limit": 500}).json()
    assert body["total"] == 3
    assert all(row["mate_found_rung"] is None for row in body["rows"])


def test_query_min_mate_found_rung_excludes_shallower_mates(client_and_ids):
    client, _ids = client_and_ids
    body = client.get(
        "/api/query", params={"min_mate_found_rung": 4_000, "limit": 500}
    ).json()
    assert body["total"] == 2
    assert all(row["mate_found_rung"] >= 4_000 for row in body["rows"])


def test_query_has_mate_invalid_value_returns_400(client_and_ids):
    client, _ids = client_and_ids
    resp = client.get("/api/query", params={"has_mate": 2})
    assert resp.status_code == 400


def test_distribution_buckets_sum_to_total_minus_null_count(client_and_ids):
    client, _ids = client_and_ids
    total = client.get("/api/query", params={"limit": 500}).json()["total"]

    body = client.get(
        "/api/distributions",
        params={"metric": "version_disagreement", "metric_version": 1},
    ).json()
    assert body["null_count"] == 3
    bucket_sum = sum(b["count"] for b in body["buckets"])
    assert bucket_sum == total - body["null_count"]


def test_distribution_sign_flips_default_width_one(client_and_ids):
    client, _ids = client_and_ids
    body = client.get(
        "/api/distributions", params={"metric": "sign_flips", "metric_version": 1}
    ).json()
    assert body["width"] == 1
    assert body["null_count"] == 0
    by_start = {b["start"]: b["count"] for b in body["buckets"]}
    assert by_start == {0: 2, 1: 2, 2: 1, 3: 1}


def test_distribution_unknown_metric_returns_400(client_and_ids):
    client, _ids = client_and_ids
    resp = client.get(
        "/api/distributions", params={"metric": "bogus", "metric_version": 1}
    )
    assert resp.status_code == 400


def test_distribution_width_zero_returns_400(client_and_ids):
    client, _ids = client_and_ids
    resp = client.get(
        "/api/distributions",
        params={"metric": "cp_range", "metric_version": 1, "width": 0},
    )
    assert resp.status_code == 400


def test_distribution_wide_width_buckets_have_integer_starts_and_group_correctly(
    client_and_ids,
):
    client, _ids = client_and_ids
    # width=25 floor-divides cp_range 10..60 into three buckets of two each.
    body = client.get(
        "/api/distributions",
        params={"metric": "cp_range", "metric_version": 1, "width": 25},
    ).json()
    assert body["width"] == 25
    by_start = {b["start"]: b["count"] for b in body["buckets"]}
    assert all(isinstance(start, int) for start in by_start)
    assert by_start == {0: 2, 25: 2, 50: 2}


def test_export_download_round_trips_expected_rows_and_columns(client_and_ids):
    client, _ids = client_and_ids
    resp = client.get("/api/export", params={"columns": "core"})
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].endswith(
        'filename="chessdb-export.parquet"'
    )

    path = _write_temp_parquet(resp.content)
    con = duckdb.connect(":memory:")
    try:
        rows = con.execute(f"SELECT * FROM '{path}'").fetchall()
        columns = [d[0] for d in con.execute(f"SELECT * FROM '{path}'").description]
    finally:
        con.close()
    assert len(rows) == 6
    assert columns[:3] == ["position_id", "engine_id", "metric_version"]
    assert "epd" in columns

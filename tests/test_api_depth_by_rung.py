"""Depth by rung query and /api/depth-by-rung. Skips without fastapi, httpx
or a working DuckDB attach."""

import chess
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("duckdb")

from fastapi.testclient import TestClient

from chessdb.api.app import create_app
from chessdb.db import connect
from chessdb.db.api import ensure_engine, ensure_position, insert_evals
from chessdb.db.export import attach_readonly
from chessdb.db.model import EngineSpec, EvalRow, LimitKind, ScoreKind, normalize_epd
from chessdb.db.query import depth_by_rung

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_OPENING_MOVES = ("e2e4", "d2d4", "g1f3")


def _epd_variant(i):
    board = chess.Board(START_FEN)
    if i > 0:
        board.push_uci(_OPENING_MOVES[i - 1])
    return board.epd()


def _eval(position_id, engine_id, limit_value, score_kind, depth, seldepth):
    return EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=LimitKind.NODES,
        limit_value=limit_value,
        score_kind=score_kind,
        score=25 if score_kind is ScoreKind.CP else 3,
        depth=depth,
        seldepth=seldepth,
        nodes=limit_value,
        time_ms=5,
        bestmove="e2e4",
    )


def _build_db(db_path):
    conn = connect(db_path)
    engine1 = ensure_engine(
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
    engine2 = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="16.1",
            binary_sha256="b" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    p1 = ensure_position(conn, normalize_epd(_epd_variant(0)))
    p2 = ensure_position(conn, normalize_epd(_epd_variant(1)))
    p3 = ensure_position(conn, normalize_epd(_epd_variant(2)))
    insert_evals(
        conn,
        [
            # engine1 @ rung 1000: two evals, one with NULL seldepth
            _eval(p1, engine1, 1_000, ScoreKind.CP, depth=10, seldepth=15),
            _eval(p2, engine1, 1_000, ScoreKind.CP, depth=12, seldepth=None),
            # engine1 @ rung 4000: a single mate eval
            _eval(p1, engine1, 4_000, ScoreKind.MATE, depth=20, seldepth=25),
            # engine2 @ rung 1000: one eval
            _eval(p3, engine2, 1_000, ScoreKind.CP, depth=8, seldepth=10),
        ],
    )
    conn.commit()
    conn.close()
    return {"engine1": engine1, "engine2": engine2}


@pytest.fixture
def db_and_ids(tmp_path, duckdb_sqlite_attach):
    db_path = tmp_path / "x.db"
    ids = _build_db(db_path)
    return db_path, ids


def test_depth_by_rung_reader_counts_and_averages_are_exact(db_and_ids):
    db_path, ids = db_and_ids
    duck = attach_readonly(db_path)
    try:
        rows = depth_by_rung(duck)
    finally:
        duck.close()

    by_key = {(r.engine_id, r.limit_value): r for r in rows}
    assert set(by_key) == {
        (ids["engine1"], 1_000),
        (ids["engine1"], 4_000),
        (ids["engine2"], 1_000),
    }

    e1_r1000 = by_key[(ids["engine1"], 1_000)]
    assert e1_r1000.n == 2
    assert e1_r1000.avg_depth == 11.0
    assert e1_r1000.min_depth == 10
    assert e1_r1000.avg_seldepth == 15.0  # NULL seldepth excluded, not averaged as 0
    assert e1_r1000.mate_count == 0

    e1_r4000 = by_key[(ids["engine1"], 4_000)]
    assert e1_r4000.n == 1
    assert e1_r4000.avg_depth == 20.0
    assert e1_r4000.avg_seldepth == 25.0
    assert e1_r4000.mate_count == 1

    e2_r1000 = by_key[(ids["engine2"], 1_000)]
    assert e2_r1000.n == 1
    assert e2_r1000.avg_depth == 8.0
    assert e2_r1000.mate_count == 0


def test_depth_by_rung_reader_orders_by_engine_then_rung(db_and_ids):
    db_path, ids = db_and_ids
    duck = attach_readonly(db_path)
    try:
        rows = depth_by_rung(duck)
    finally:
        duck.close()
    assert [(r.engine_id, r.limit_value) for r in rows] == [
        (ids["engine1"], 1_000),
        (ids["engine1"], 4_000),
        (ids["engine2"], 1_000),
    ]


def test_depth_by_rung_endpoint_serializes_reader_rows(db_and_ids):
    db_path, ids = db_and_ids
    client = TestClient(create_app(db_path))
    body = client.get("/api/depth-by-rung").json()
    rows = {(r["engine_id"], r["limit_value"]): r for r in body["rows"]}

    row = rows[(ids["engine1"], 1_000)]
    assert row["engine_name"] == "stockfish"
    assert row["engine_version"] == "17.1"
    assert row["n"] == 2
    assert row["avg_depth"] == 11.0
    assert row["min_depth"] == 10
    assert row["avg_seldepth"] == 15.0
    assert row["mate_count"] == 0

    mate_row = rows[(ids["engine1"], 4_000)]
    assert mate_row["mate_count"] == 1

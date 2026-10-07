"""SQLite backed API endpoints over a hand-built DB. Skips without fastapi or httpx."""

import chess
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from chessdb.api.app import create_app
from chessdb.db import connect
from chessdb.db.api import (
    ensure_engine,
    ensure_position,
    insert_evals,
    replace_position_metrics,
)
from chessdb.db.model import (
    EngineSpec,
    EvalRow,
    LimitKind,
    PositionMetricsRow,
    ScoreKind,
    normalize_epd,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


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
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    insert_evals(
        conn,
        [
            EvalRow(
                position_id=position_id,
                engine_id=engine_id,
                limit_kind=LimitKind.NODES,
                limit_value=1_000,
                score_kind=ScoreKind.CP,
                score=25,
                depth=8,
                seldepth=10,
                nodes=1_000,
                time_ms=5,
                bestmove="e2e4",
            ),
            EvalRow(
                position_id=position_id,
                engine_id=engine_id,
                limit_kind=LimitKind.NODES,
                limit_value=4_000,
                score_kind=ScoreKind.MATE,
                score=-2,
                depth=12,
                seldepth=None,
                nodes=4_000,
                time_ms=8,
                bestmove="e2e4",
            ),
            EvalRow(
                position_id=position_id,
                engine_id=engine_id,
                limit_kind=LimitKind.DEPTH,
                limit_value=10,
                score_kind=ScoreKind.CP,
                score=30,
                depth=10,
                seldepth=None,
                nodes=500,
                time_ms=3,
                bestmove="d2d4",
            ),
        ],
    )
    replace_position_metrics(
        conn,
        [
            PositionMetricsRow(
                position_id=position_id,
                engine_id=engine_id,
                metric_version=1,
                top_rung=4_000,
                sign_flips=1,
                cp_range=1_025,
                settle_dev=1_000,
                version_disagreement=None,
            ),
        ],
    )
    conn.commit()
    conn.close()
    return {
        "engine_id": engine_id,
        "position_id": position_id,
        "epd": normalize_epd(START_FEN),
    }


@pytest.fixture
def client_and_ids(tmp_path):
    db_path = tmp_path / "x.db"
    ids = _build_db(db_path)
    app = create_app(db_path)
    return TestClient(app), ids


def test_meta_reports_counts_engines_and_metric_versions(client_and_ids):
    client, ids = client_and_ids
    body = client.get("/api/meta").json()
    assert body["schema_version"] == 3
    assert body["row_counts"] == {
        "engines": 1,
        "games": 0,
        "positions": 1,
        "evals": 3,
        "position_metrics": 1,
    }
    assert [e["id"] for e in body["engines"]] == [ids["engine_id"]]
    assert body["metric_versions"] == [1]


def test_position_lookup_by_id_returns_evals_and_metrics(client_and_ids):
    client, ids = client_and_ids
    resp = client.get(f"/api/positions/{ids['position_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["position"]["id"] == ids["position_id"]
    assert body["position"]["epd"] == ids["epd"]
    assert len(body["evals"]) == 3
    assert len(body["metrics"]) == 1
    assert body["metrics"][0]["sign_flips"] == 1


def test_position_lookup_missing_id_returns_404(client_and_ids):
    client, _ids = client_and_ids
    assert client.get("/api/positions/999999").status_code == 404


def test_position_lookup_by_epd_normalizes(client_and_ids):
    client, ids = client_and_ids
    resp = client.get("/api/positions/by-epd", params={"epd": START_FEN})
    assert resp.status_code == 200
    assert resp.json()["position"]["id"] == ids["position_id"]


def test_position_lookup_by_epd_illegal_returns_400(client_and_ids):
    client, _ids = client_and_ids
    resp = client.get("/api/positions/by-epd", params={"epd": "garbage"})
    assert resp.status_code == 400


def test_position_lookup_by_epd_missing_returns_404(client_and_ids):
    client, _ids = client_and_ids
    board = chess.Board(START_FEN)
    board.push_uci("e2e4")
    resp = client.get("/api/positions/by-epd", params={"epd": board.fen()})
    assert resp.status_code == 404


def test_trajectory_only_includes_nodes_rungs_and_matches_clamp(client_and_ids):
    client, ids = client_and_ids
    resp = client.get(f"/api/positions/{ids['position_id']}/trajectory")
    assert resp.status_code == 200
    body = resp.json()
    assert body["position_id"] == ids["position_id"]
    [engine_series] = body["engines"]
    assert engine_series["engine_id"] == ids["engine_id"]
    series = engine_series["series"]
    assert [s["limit_value"] for s in series] == [1_000, 4_000]  # DEPTH excluded
    assert series[0]["clamped"] == 25
    assert series[1]["clamped"] == -1_000  # MATE -2 clamps to -CLAMP


def test_trajectory_missing_position_returns_404(client_and_ids):
    client, _ids = client_and_ids
    assert client.get("/api/positions/999999/trajectory").status_code == 404

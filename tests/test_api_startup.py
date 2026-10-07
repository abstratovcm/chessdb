"""create_app refuses a bad DB with a clear error instead of a traceback.
Skips without fastapi."""

import sqlite3

import pytest

pytest.importorskip("fastapi")

from chessdb.db.export import AttachError
from chessdb.db.migrations import MIGRATIONS


def test_missing_db_file_raises_system_exit(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "missing.db"
    with pytest.raises(SystemExit, match="does not exist"):
        create_app(db_path)


def test_corrupt_db_file_raises_system_exit(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a sqlite file at all")
    with pytest.raises(SystemExit, match="could not open --db read-only"):
        create_app(db_path)


def test_pre_metrics_schema_version_raises_system_exit(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit, match="pre-metrics"):
        create_app(db_path)


def test_empty_position_metrics_warns_on_stderr(tmp_path, capsys, duckdb_sqlite_attach):
    from chessdb.api.app import create_app

    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    for step in MIGRATIONS:
        conn.executescript(step)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
    conn.commit()
    conn.close()

    create_app(db_path)
    assert "position_metrics" in capsys.readouterr().err


def test_populated_position_metrics_is_silent(tmp_path, capsys, duckdb_sqlite_attach):
    from chessdb.api.app import create_app
    from chessdb.db import connect
    from chessdb.db.api import ensure_engine, ensure_position, replace_position_metrics
    from chessdb.db.model import EngineSpec, PositionMetricsRow, normalize_epd

    db_path = tmp_path / "populated.db"
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
    position_id = ensure_position(
        conn, normalize_epd("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    )
    replace_position_metrics(
        conn,
        [
            PositionMetricsRow(
                position_id=position_id,
                engine_id=engine_id,
                metric_version=1,
                top_rung=1_000,
                sign_flips=0,
                cp_range=0,
                settle_dev=0,
                version_disagreement=None,
            )
        ],
    )
    conn.commit()
    conn.close()

    create_app(db_path)
    assert "position_metrics" not in capsys.readouterr().err


def test_attach_failure_raises_system_exit(tmp_path, monkeypatch):
    import chessdb.api.app as app_module

    db_path = tmp_path / "x.db"
    conn = sqlite3.connect(db_path)
    for step in MIGRATIONS:
        conn.executescript(step)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
    conn.commit()
    conn.close()

    def _boom(_path):
        raise AttachError("duckdb attach exploded")

    monkeypatch.setattr(app_module, "attach_readonly", _boom)
    with pytest.raises(SystemExit, match="duckdb attach exploded"):
        app_module.create_app(db_path)

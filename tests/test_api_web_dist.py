"""Static mount of `--web-dist`. Skips without fastapi or httpx."""

import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from chessdb.db.migrations import MIGRATIONS


def _build_db(db_path):
    conn = sqlite3.connect(db_path)
    for step in MIGRATIONS:
        conn.executescript(step)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
    conn.commit()
    conn.close()


def test_missing_web_dist_dir_raises_system_exit(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "x.db"
    _build_db(db_path)
    with pytest.raises(SystemExit, match="not a directory"):
        create_app(db_path, web_dist=tmp_path / "does-not-exist")


def test_web_dist_missing_index_html_raises_system_exit(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "x.db"
    _build_db(db_path)
    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    with pytest.raises(SystemExit, match="no index.html"):
        create_app(db_path, web_dist=web_dist)


def test_web_dist_serves_index_and_api_still_works(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "x.db"
    _build_db(db_path)
    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<html>dummy dist</html>")

    app = create_app(db_path, web_dist=web_dist)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "dummy dist" in resp.text

    api_resp = client.get("/api/meta")
    assert api_resp.status_code == 200
    assert api_resp.json()["schema_version"] == len(MIGRATIONS)


def test_no_web_dist_means_api_only(tmp_path):
    from chessdb.api.app import create_app

    db_path = tmp_path / "x.db"
    _build_db(db_path)
    app = create_app(db_path)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 404
    assert client.get("/api/meta").status_code == 200

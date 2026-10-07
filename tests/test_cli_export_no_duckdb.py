"""Missing duckdb exits cleanly. Runs without duckdb installed."""

import builtins

import pytest

from chessdb.cli.main import main


def test_export_missing_duckdb_raises_system_exit(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("no duckdb")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    db_path = tmp_path / "x.db"
    db_path.touch()
    out_path = tmp_path / "out.parquet"
    monkeypatch.setattr(
        "sys.argv",
        ["chessdb", "export", "--db", str(db_path), "--out", str(out_path)],
    )
    with pytest.raises(SystemExit, match=r"chessdb\[site\]"):
        main()

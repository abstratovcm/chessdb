"""Missing fastapi or uvicorn exits cleanly. Cached chessdb.api modules are
cleared so the fake import failure is actually hit."""

import builtins
import sys

import pytest

from chessdb.cli.main import main


def test_serve_missing_fastapi_raises_system_exit(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "fastapi" or name.startswith("fastapi."):
            raise ImportError("no fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.delitem(sys.modules, "chessdb.api.app", raising=False)
    monkeypatch.delitem(sys.modules, "chessdb.api", raising=False)

    db_path = tmp_path / "x.db"
    db_path.touch()
    monkeypatch.setattr("sys.argv", ["chessdb", "serve", "--db", str(db_path)])
    with pytest.raises(SystemExit, match=r"chessdb\[site\]"):
        main()

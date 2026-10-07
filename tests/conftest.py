import argparse
import dataclasses
import sqlite3

import chess
import chess.engine
import pytest

import chessdb.cli.run as run_mod
from chessdb.engine.fetch import cached_engine_path

_PIN_KEY = ("17.1", "x86-64-avx2")


class _FakeEngine:
    """Fake engine: multipv=None returns one dict like SimpleEngine, an int
    returns a list of dicts."""

    _CP_SPREAD = (40, 20, 0, -400)

    def analyse(self, board, limit, multipv=None, game=None, info=None):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())[: len(self._CP_SPREAD)]
        infos = [
            {
                "multipv": rank,
                "score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn),
                "pv": [move],
                "depth": 5,
                "seldepth": 5,
                "nodes": 1000,
                "time": 0.01,
            }
            for rank, (move, cp) in enumerate(zip(moves, self._CP_SPREAD), start=1)
        ]
        return infos[0] if multipv is None else infos[:multipv]

    def quit(self):
        pass


class _NeverStop:
    def is_set(self):
        return False


class _CountdownStopEvent:
    def __init__(self, trigger_after):
        self._trigger_after = trigger_after
        self._calls = 0
        self._flag = False

    def is_set(self):
        self._calls += 1
        if self._calls >= self._trigger_after:
            self._flag = True
        return self._flag

    def set(self):
        self._flag = True


def _patch_engine(monkeypatch, tmp_path, engine_cls=_FakeEngine):
    fake_binary = tmp_path / "fake-stockfish"
    monkeypatch.setattr(
        run_mod, "cached_engine_path", lambda version, variant: fake_binary
    )
    monkeypatch.setattr(run_mod, "compute_sha256", lambda binary: "d" * 64)
    monkeypatch.setattr(run_mod, "open_engine", lambda binary: engine_cls())


def _args(db_path, **overrides):
    defaults = {
        "db": db_path,
        "seed": 1,
        "games_target": 2,
        "max_hours": 1.0,
        "workers": 1,
        "version": "17.1",
        "variant": "x86-64-avx2",
        "max_ply": 12,
        "top_rung": 16_000,
        "drive_dir": None,
        "checkpoint_minutes": 15.0,
        "shards": 1,
        "shard_index": 0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _strip_time(row):
    return dataclasses.replace(row, time_ms=0)


@pytest.fixture
def engine_binary():
    try:
        return cached_engine_path(*_PIN_KEY)
    except FileNotFoundError:
        pytest.skip("pinned engine binary not cached; run `chessdb fetch-engine`")


@pytest.fixture
def duckdb_sqlite_attach(tmp_path):
    """Skips when DuckDB cannot attach SQLite (the extension downloads on first use)."""
    duckdb = pytest.importorskip("duckdb")
    probe_path = tmp_path / "probe.sqlite"
    sqlite3.connect(probe_path).close()
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"ATTACH '{probe_path}' AS probe (TYPE sqlite, READ_ONLY)")
    except duckdb.Error:
        pytest.skip("duckdb sqlite scanner extension unavailable")
    finally:
        conn.close()

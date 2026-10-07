import dataclasses

import pytest

from chessdb.cli.main import main
from chessdb.db import connect
from chessdb.db.api import evals_for_position, get_position
from chessdb.db.model import LimitKind, normalize_epd
from chessdb.engine.ladder import NODE_LADDER

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
SICILIAN_FEN = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2"


def _run_eval(monkeypatch, capsys, *extra_args):
    monkeypatch.setattr("sys.argv", ["chessdb", "eval", *extra_args])
    main()
    return capsys.readouterr().out


@pytest.mark.engine
def test_eval_default_ladder_two_positions(
    tmp_path, monkeypatch, capsys, engine_binary
):
    db_path = tmp_path / "x.db"
    out = _run_eval(
        monkeypatch,
        capsys,
        "--db",
        str(db_path),
        "--epd",
        START_FEN,
        "--epd",
        SICILIAN_FEN,
    )
    assert f"positions=2 inserted={2 * len(NODE_LADDER)} ignored=0" in out

    conn = connect(db_path)
    for fen in (START_FEN, SICILIAN_FEN):
        position = get_position(conn, normalize_epd(fen))
        rows = evals_for_position(conn, position.id)
        assert len(rows) == len(NODE_LADDER)
        assert [r.limit_value for r in rows] == sorted(NODE_LADDER)
        for row in rows:
            assert row.limit_kind == LimitKind.NODES
            assert row.nodes > 0
            assert row.depth > 0
            assert row.time_ms >= 0
    conn.close()


@pytest.mark.engine
def test_eval_determinism_same_db_second_run_inserts_zero(
    tmp_path, monkeypatch, capsys, engine_binary
):
    db_path = tmp_path / "x.db"
    _run_eval(monkeypatch, capsys, "--db", str(db_path), "--epd", START_FEN)
    second = _run_eval(monkeypatch, capsys, "--db", str(db_path), "--epd", START_FEN)
    assert f"positions=1 inserted=0 ignored={len(NODE_LADDER)}" in second


@pytest.mark.engine
def test_eval_determinism_two_fresh_dbs_match(
    tmp_path, monkeypatch, capsys, engine_binary
):
    db_a, db_b = tmp_path / "a.db", tmp_path / "b.db"
    _run_eval(monkeypatch, capsys, "--db", str(db_a), "--epd", START_FEN)
    _run_eval(monkeypatch, capsys, "--db", str(db_b), "--epd", START_FEN)

    conn_a, conn_b = connect(db_a), connect(db_b)
    position_a = get_position(conn_a, normalize_epd(START_FEN))
    position_b = get_position(conn_b, normalize_epd(START_FEN))
    rows_a = evals_for_position(conn_a, position_a.id)
    rows_b = evals_for_position(conn_b, position_b.id)
    conn_a.close()
    conn_b.close()

    assert len(rows_a) == len(rows_b) == len(NODE_LADDER)

    # Node limits are deterministic: everything but wall clock time_ms must match.
    def strip_time(row):
        return dataclasses.replace(row, time_ms=0)

    assert [strip_time(r) for r in rows_a] == [strip_time(r) for r in rows_b]


@pytest.mark.engine
def test_eval_full_fen_dedupes_to_same_epd_row(
    tmp_path, monkeypatch, capsys, engine_binary
):
    db_path = tmp_path / "x.db"
    full_fen = START_FEN
    other_counters_fen = START_FEN.replace("0 1", "3 7")
    out = _run_eval(
        monkeypatch,
        capsys,
        "--db",
        str(db_path),
        "--epd",
        full_fen,
        "--epd",
        other_counters_fen,
    )
    assert f"positions=2 inserted={len(NODE_LADDER)} ignored={len(NODE_LADDER)}" in out

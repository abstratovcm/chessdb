import re

import chess
import pytest

from chessdb.cli.main import main
from chessdb.db import connect
from chessdb.db.api import (
    ensure_engine,
    ensure_position,
    insert_evals,
    replace_position_metrics,
)
from chessdb.db.export import attach_readonly
from chessdb.db.model import (
    EngineSpec,
    EvalRow,
    LimitKind,
    PositionMetricsRow,
    ScoreKind,
    normalize_epd,
)
from chessdb.engine.ladder import NODE_LADDER

duckdb = pytest.importorskip("duckdb")

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_SUMMARY_RE = re.compile(r"^rows=(\d+) columns=(\d+) file=(.+)$")


def _eval_row(position_id, engine_id, limit_value):
    return EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=LimitKind.NODES,
        limit_value=limit_value,
        score_kind=ScoreKind.CP,
        score=10,
        depth=1,
        seldepth=None,
        nodes=limit_value,
        time_ms=1,
        bestmove=None,
    )


def _second_position_epd():
    board = chess.Board(START_FEN)
    board.push_uci("e2e4")
    return board.epd()


def test_attach_readonly_counts_without_rowid_tables(tmp_path, duckdb_sqlite_attach):
    db_path = tmp_path / "x.db"
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
    position_a = ensure_position(conn, normalize_epd(START_FEN))
    position_b = ensure_position(conn, _second_position_epd())
    insert_evals(
        conn,
        [
            _eval_row(position_a, engine_id, 1_000),
            _eval_row(position_a, engine_id, 4_000),
            _eval_row(position_a, engine_id, 16_000),
            _eval_row(position_b, engine_id, 1_000),
        ],
    )
    replace_position_metrics(
        conn,
        [
            PositionMetricsRow(
                position_id=position_a,
                engine_id=engine_id,
                metric_version=1,
                top_rung=16_000,
                sign_flips=0,
                cp_range=0,
                settle_dev=0,
                version_disagreement=None,
            ),
            PositionMetricsRow(
                position_id=position_b,
                engine_id=engine_id,
                metric_version=1,
                top_rung=1_000,
                sign_flips=0,
                cp_range=0,
                settle_dev=0,
                version_disagreement=None,
            ),
        ],
    )
    conn.commit()
    conn.close()

    duck = attach_readonly(db_path)
    try:
        # COUNT(*) fails on WITHOUT ROWID tables in duckdb 1.5.5's sqlite scanner.
        evals_count = duck.execute(
            "SELECT COUNT(position_id) FROM src.evals"
        ).fetchone()[0]
        metrics_count = duck.execute(
            "SELECT COUNT(position_id) FROM src.position_metrics"
        ).fetchone()[0]
    finally:
        duck.close()

    assert evals_count == 4
    assert metrics_count == 2


def _engine(conn, byte):
    return ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256=byte * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )


def _cp_eval(position_id, engine_id, limit_value, score):
    return EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=LimitKind.NODES,
        limit_value=limit_value,
        score_kind=ScoreKind.CP,
        score=score,
        depth=1,
        seldepth=None,
        nodes=limit_value,
        time_ms=1,
        bestmove="e2e4",
    )


def _epd_after(*uci_moves):
    board = chess.Board(START_FEN)
    for move in uci_moves:
        board.push_uci(move)
    return board.epd()


def _build_export_db(db_path):
    """position_a: full ladder, engine1, mv1 + mv2 (clamp + mate-clamp
    cases); position_b: truncated ladder, engine1, mv1 (NULL-rung case);
    position_c: engine2, mv1 (--engine-id filter case)."""
    conn = connect(db_path)
    engine1 = _engine(conn, "a")
    engine2 = _engine(conn, "b")
    position_a = ensure_position(conn, normalize_epd(START_FEN))
    position_b = ensure_position(conn, _epd_after("e2e4"))
    position_c = ensure_position(conn, _epd_after("d2d4"))

    insert_evals(
        conn,
        [
            _cp_eval(position_a, engine1, 1_000, 50),
            _cp_eval(position_a, engine1, 4_000, 1_500),  # clamps to 1000
            EvalRow(
                position_id=position_a,
                engine_id=engine1,
                limit_kind=LimitKind.NODES,
                limit_value=16_000,
                score_kind=ScoreKind.MATE,
                score=-2,
                depth=10,
                seldepth=None,
                nodes=16_000,
                time_ms=1,
                bestmove=None,
            ),
            _cp_eval(position_a, engine1, 64_000, 200),
            _cp_eval(position_a, engine1, 256_000, 220),
            _cp_eval(position_a, engine1, 1_000_000, 230),
            _cp_eval(position_b, engine1, 1_000, 10),
            EvalRow(
                position_id=position_c,
                engine_id=engine2,
                limit_kind=LimitKind.NODES,
                limit_value=1_000,
                score_kind=ScoreKind.MATE,
                score=3,
                depth=6,
                seldepth=None,
                nodes=1_000,
                time_ms=1,
                bestmove="d2d4",
            ),
        ],
    )
    replace_position_metrics(
        conn,
        [
            PositionMetricsRow(
                position_id=position_a,
                engine_id=engine1,
                metric_version=1,
                top_rung=1_000_000,
                sign_flips=2,
                cp_range=1_050,
                settle_dev=770,
                version_disagreement=None,
                mate_found_rung=16_000,
            ),
            PositionMetricsRow(
                position_id=position_a,
                engine_id=engine1,
                metric_version=2,
                top_rung=1_000_000,
                sign_flips=9,
                cp_range=9,
                settle_dev=9,
                version_disagreement=None,
            ),
            PositionMetricsRow(
                position_id=position_b,
                engine_id=engine1,
                metric_version=1,
                top_rung=1_000,
                sign_flips=0,
                cp_range=0,
                settle_dev=0,
                version_disagreement=None,
            ),
            PositionMetricsRow(
                position_id=position_c,
                engine_id=engine2,
                metric_version=1,
                top_rung=1_000,
                sign_flips=1,
                cp_range=5,
                settle_dev=5,
                version_disagreement=10,
                mate_found_rung=1_000,
            ),
        ],
    )
    conn.commit()
    conn.close()
    return {
        "engine1": engine1,
        "engine2": engine2,
        "position_a": position_a,
        "position_b": position_b,
        "position_c": position_c,
    }


def _run_export_cli(monkeypatch, capsys, db_path, out_path, *extra_args):
    monkeypatch.setattr(
        "sys.argv",
        [
            "chessdb",
            "export",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            *extra_args,
        ],
    )
    main()
    out = capsys.readouterr().out.strip()
    match = _SUMMARY_RE.match(out)
    assert match is not None, out
    return int(match.group(1)), int(match.group(2))


def _read_parquet(out_path, columns="*", order_by="position_id"):
    con = duckdb.connect(":memory:")
    try:
        return con.execute(
            f"SELECT {columns} FROM '{out_path}' ORDER BY {order_by}"
        ).fetchall()
    finally:
        con.close()


def test_export_default_row_and_column_counts(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, columns = _run_export_cli(monkeypatch, capsys, db_path, out_path)

    assert rows == 3  # position_a/b (engine1) + position_c (engine2), mv1
    assert columns == 3 + 5 + 6 + len(NODE_LADDER)  # grain + core + metrics + cp


def test_export_columns_group_selection(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    _build_export_db(db_path)

    core_out = tmp_path / "core.parquet"
    _, core_columns = _run_export_cli(
        monkeypatch, capsys, db_path, core_out, "--columns", "core"
    )
    assert core_columns == 3 + 5

    cp_out = tmp_path / "cp.parquet"
    _, cp_columns = _run_export_cli(
        monkeypatch, capsys, db_path, cp_out, "--columns", "cp"
    )
    assert cp_columns == 3 + len(NODE_LADDER)


def test_export_min_sign_flips_excludes_flat_positions(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--min-sign-flips", "1"
    )
    assert rows == 2
    kept = {r[0] for r in _read_parquet(out_path, columns="position_id")}
    assert kept == {ids["position_a"], ids["position_c"]}


def test_export_min_cp_range_keeps_only_wide_swings(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--min-cp-range", "100"
    )
    assert rows == 1
    assert _read_parquet(out_path, columns="position_id") == [(ids["position_a"],)]


def test_export_max_settle_dev_excludes_unstable_position(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--max-settle-dev", "5"
    )
    assert rows == 2
    kept = {r[0] for r in _read_parquet(out_path, columns="position_id")}
    assert kept == {ids["position_b"], ids["position_c"]}


def test_export_has_mate_keeps_only_mate_rows(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(monkeypatch, capsys, db_path, out_path, "--has-mate", "1")
    assert rows == 2
    kept = {r[0] for r in _read_parquet(out_path, columns="position_id")}
    assert kept == {ids["position_a"], ids["position_c"]}


def test_export_has_mate_zero_excludes_mate_rows(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(monkeypatch, capsys, db_path, out_path, "--has-mate", "0")
    assert rows == 1
    assert _read_parquet(out_path, columns="position_id") == [(ids["position_b"],)]


def test_export_min_mate_found_rung_excludes_shallower_mates(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--min-mate-found-rung", "16000"
    )
    assert rows == 1
    assert _read_parquet(out_path, columns="position_id") == [(ids["position_a"],)]


def test_export_has_mate_invalid_value_raises_system_exit(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    with pytest.raises(SystemExit):
        _run_export_cli(monkeypatch, capsys, db_path, out_path, "--has-mate", "2")


def test_export_min_top_rung_keeps_only_full_ladder(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--min-top-rung", "500000"
    )
    assert rows == 1
    assert _read_parquet(out_path, columns="position_id") == [(ids["position_a"],)]


def test_export_engine_id_filters_to_one_engine(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--engine-id", str(ids["engine2"])
    )
    assert rows == 1
    assert _read_parquet(out_path, columns="position_id") == [(ids["position_c"],)]


def test_export_metric_version_selects_the_requested_version(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    rows, _ = _run_export_cli(
        monkeypatch, capsys, db_path, out_path, "--metric-version", "2"
    )
    assert rows == 1
    assert _read_parquet(out_path, columns="position_id") == [(ids["position_a"],)]


def test_export_truncated_ladder_yields_null_cp_for_missing_rungs(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    _run_export_cli(
        monkeypatch,
        capsys,
        db_path,
        out_path,
        "--min-top-rung",
        "0",
        "--columns",
        "cp",
    )
    rows = {
        r[0]: r[1:]
        for r in _read_parquet(
            out_path,
            columns="position_id, " + ", ".join(f"cp_{r}" for r in NODE_LADDER),
        )
    }
    assert rows[ids["position_b"]] == (10,) + (None,) * (len(NODE_LADDER) - 1)


def test_export_mate_row_clamps_to_bound(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    _run_export_cli(monkeypatch, capsys, db_path, out_path, "--columns", "cp")
    by_16000 = {
        r[0]: r[1] for r in _read_parquet(out_path, columns="position_id, cp_16000")
    }
    assert by_16000[ids["position_a"]] == -1_000  # MATE -2 clamps to -CLAMP_BOUND

    by_1000 = {
        r[0]: r[1] for r in _read_parquet(out_path, columns="position_id, cp_1000")
    }
    assert by_1000[ids["position_c"]] == 1_000  # MATE +3 clamps to +CLAMP_BOUND

    by_4000 = {
        r[0]: r[1] for r in _read_parquet(out_path, columns="position_id, cp_4000")
    }
    assert by_4000[ids["position_a"]] == 1_000  # CP 1500 clamps to +CLAMP_BOUND


def test_export_refuses_existing_out_without_force(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    _build_export_db(db_path)
    out_path = tmp_path / "out.parquet"

    _run_export_cli(monkeypatch, capsys, db_path, out_path)
    monkeypatch.setattr(
        "sys.argv",
        ["chessdb", "export", "--db", str(db_path), "--out", str(out_path)],
    )
    with pytest.raises(SystemExit, match="already exists"):
        main()

    monkeypatch.setattr(
        "sys.argv",
        [
            "chessdb",
            "export",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            "--force",
        ],
    )
    main()  # does not raise
    out = capsys.readouterr().out.strip()
    assert _SUMMARY_RE.match(out) is not None


def test_export_determinism_two_runs_are_content_identical(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    _build_export_db(db_path)

    first_out = tmp_path / "first.parquet"
    second_out = tmp_path / "second.parquet"
    _run_export_cli(monkeypatch, capsys, db_path, first_out, "--columns", "core,cp")
    _run_export_cli(monkeypatch, capsys, db_path, second_out, "--columns", "core,cp")

    assert _read_parquet(first_out) == _read_parquet(second_out)


def test_export_filtered_rows_are_a_subset_of_unfiltered_rows(
    tmp_path, duckdb_sqlite_attach, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    ids = _build_export_db(db_path)

    unfiltered_out = tmp_path / "unfiltered.parquet"
    filtered_out = tmp_path / "filtered.parquet"
    _run_export_cli(monkeypatch, capsys, db_path, unfiltered_out)
    _run_export_cli(monkeypatch, capsys, db_path, filtered_out, "--min-sign-flips", "1")

    unfiltered_ids = {
        r[0] for r in _read_parquet(unfiltered_out, columns="position_id")
    }
    filtered_ids = {r[0] for r in _read_parquet(filtered_out, columns="position_id")}

    assert filtered_ids == {ids["position_a"], ids["position_c"]}
    assert filtered_ids < unfiltered_ids

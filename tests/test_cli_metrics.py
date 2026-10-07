import re
import sqlite3

import chess
import pytest

from chessdb.cli.main import main
from chessdb.db import connect
from chessdb.db.api import (
    ensure_engine,
    ensure_position,
    get_position,
    insert_evals,
    metrics_for_position,
)
from chessdb.db.model import EngineSpec, EvalRow, LimitKind, ScoreKind, normalize_epd
from chessdb.engine.ladder import NODE_LADDER

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

_V1_SUMMARY_RE = re.compile(
    r"^metric_version=1 engines=(\d+) computed=(\d+) skipped_partial=(\d+)$",
    re.MULTILINE,
)
_V2_SUMMARY_RE = re.compile(
    r"^metric_version=2 engines=(\d+) computed=(\d+) skipped_partial=(\d+)$",
    re.MULTILINE,
)


def _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000):
    monkeypatch.setattr(
        "sys.argv",
        ["chessdb", "metrics", "--db", str(db_path), "--top-rung", str(top_rung)],
    )
    main()
    return capsys.readouterr().out


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


def _eval(position_id, engine_id, limit_value, score_kind, score):
    return EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=LimitKind.NODES,
        limit_value=limit_value,
        score_kind=score_kind,
        score=score,
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


def _build_db(db_path):
    conn = connect(db_path)
    engine1 = _engine(conn, "a")
    engine2 = _engine(conn, "b")
    position_a = ensure_position(conn, normalize_epd(START_FEN))
    position_b = ensure_position(conn, _second_position_epd())

    insert_evals(
        conn,
        [
            _eval(position_a, engine1, 1_000, ScoreKind.CP, 100),
            _eval(position_a, engine1, 4_000, ScoreKind.CP, 1200),
            _eval(position_a, engine1, 16_000, ScoreKind.CP, -50),
            _eval(position_a, engine2, 1_000, ScoreKind.CP, 80),
            _eval(position_a, engine2, 4_000, ScoreKind.CP, 90),
            _eval(position_a, engine2, 16_000, ScoreKind.MATE, 3),
            _eval(position_b, engine1, 1_000, ScoreKind.CP, 10),
        ],
    )
    conn.commit()
    conn.close()
    return engine1, engine2, position_a, position_b


def test_metrics_summary_format_computed_and_skipped_counts(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    _build_db(db_path)

    out = _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000)
    v1_match = _V1_SUMMARY_RE.search(out)
    v2_match = _V2_SUMMARY_RE.search(out)
    assert v1_match is not None and v2_match is not None, out

    engines, computed, skipped_partial = (int(g) for g in v1_match.groups())
    assert (engines, computed, skipped_partial) == (2, 2, 2)

    engines, computed, skipped_partial = (int(g) for g in v2_match.groups())
    assert (engines, computed, skipped_partial) == (2, 3, 1)


def test_metrics_v1_formula_values_frozen_and_version_disagreement_symmetric(
    tmp_path, monkeypatch, capsys
):
    """metric_version 1 output stays unchanged next to version 2."""
    db_path = tmp_path / "x.db"
    engine1, engine2, position_a, position_b = _build_db(db_path)
    _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000)

    conn = connect(db_path)
    v1_rows = [
        r for r in metrics_for_position(conn, position_a) if r.metric_version == 1
    ]
    assert [r.engine_id for r in v1_rows] == [engine1, engine2]

    row1, row2 = v1_rows
    assert row1.top_rung == 16_000
    assert row1.sign_flips == 1
    assert row1.cp_range == 1050
    assert row1.settle_dev == 1050
    assert row1.version_disagreement == 1050
    assert row1.mate_found_rung is None

    assert row2.sign_flips == 0
    assert row2.cp_range == 920
    assert row2.settle_dev == 920
    assert row2.version_disagreement == 1050
    assert row2.mate_found_rung is None

    assert [
        r for r in metrics_for_position(conn, position_b) if r.metric_version == 1
    ] == []
    conn.close()


def test_metrics_v2_anchor_and_mate_found_rung(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "x.db"
    engine1, engine2, position_a, position_b = _build_db(db_path)
    _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000)

    conn = connect(db_path)
    v2_by_engine = {
        r.engine_id: r
        for r in metrics_for_position(conn, position_a)
        if r.metric_version == 2
    }
    row1, row2 = v2_by_engine[engine1], v2_by_engine[engine2]

    assert row1.top_rung == 16_000  # full 3-rung prefix present -> anchor 16000
    assert row1.sign_flips == 1
    assert row1.cp_range == 1050
    assert row1.settle_dev == 1050
    assert row1.version_disagreement == 1050
    assert row1.mate_found_rung is None

    assert row2.top_rung == 16_000
    assert row2.sign_flips == 0
    assert row2.cp_range == 920
    assert row2.settle_dev == 920
    assert row2.version_disagreement == 1050
    assert row2.mate_found_rung == 16_000  # engine2's raw mate at 16000

    v2_b = [
        r
        for r in metrics_for_position(conn, position_b)
        if r.metric_version == 2 and r.engine_id == engine1
    ]
    assert len(v2_b) == 1
    row_b = v2_b[0]
    assert row_b.top_rung == 1_000  # anchor stops at the only present rung
    assert row_b.sign_flips == 0
    assert row_b.cp_range == 0
    assert row_b.settle_dev == 0
    assert row_b.version_disagreement is None  # no other engine anchors position_b
    assert row_b.mate_found_rung is None

    assert not any(
        r.engine_id == engine2 for r in metrics_for_position(conn, position_b)
    )
    conn.close()


def test_metrics_rerun_on_unchanged_db_is_byte_identical(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "x.db"
    _build_db(db_path)
    _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000)

    raw = sqlite3.connect(db_path)
    first_dump = raw.execute(
        "SELECT position_id, engine_id, metric_version, top_rung, sign_flips, "
        "cp_range, settle_dev, version_disagreement, mate_found_rung "
        "FROM position_metrics ORDER BY position_id, engine_id, metric_version"
    ).fetchall()
    raw.close()

    _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000)

    raw = sqlite3.connect(db_path)
    second_dump = raw.execute(
        "SELECT position_id, engine_id, metric_version, top_rung, sign_flips, "
        "cp_range, settle_dev, version_disagreement, mate_found_rung "
        "FROM position_metrics ORDER BY position_id, engine_id, metric_version"
    ).fetchall()
    raw.close()

    assert first_dump == second_dump


def test_metrics_top_rung_must_be_a_ladder_member(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "x.db"
    _build_db(db_path)
    with pytest.raises(SystemExit):
        _run_metrics(monkeypatch, capsys, db_path, top_rung=12_345)


def test_metrics_no_engines_prints_zero_summary_both_versions(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "x.db"
    connect(db_path).close()
    out = _run_metrics(monkeypatch, capsys, db_path, top_rung=16_000)
    assert out.strip() == (
        "metric_version=1 engines=0 computed=0 skipped_partial=0\n"
        "metric_version=2 engines=0 computed=0 skipped_partial=0"
    )


@pytest.mark.engine
def test_eval_full_ladder_then_metrics_v2_anchors_at_4m_rung(
    tmp_path, monkeypatch, capsys, engine_binary
):
    """Real engine smoke test: the full ladder up to 4M nodes, then metrics
    anchoring version 2 at the top rung."""
    db_path = tmp_path / "smoke.sqlite"
    monkeypatch.setattr(
        "sys.argv", ["chessdb", "eval", "--db", str(db_path), "--epd", START_FEN]
    )
    main()
    eval_out = capsys.readouterr().out
    assert f"positions=1 inserted={len(NODE_LADDER)} ignored=0" in eval_out

    monkeypatch.setattr("sys.argv", ["chessdb", "metrics", "--db", str(db_path)])
    main()
    metrics_out = capsys.readouterr().out
    v2_match = _V2_SUMMARY_RE.search(metrics_out)
    assert v2_match is not None, metrics_out
    assert v2_match.groups() == ("1", "1", "0")

    conn = connect(db_path)
    position = get_position(conn, normalize_epd(START_FEN))
    v2_rows = [
        r for r in metrics_for_position(conn, position.id) if r.metric_version == 2
    ]
    assert len(v2_rows) == 1
    assert v2_rows[0].top_rung == 4_000_000
    conn.close()

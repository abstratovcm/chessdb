import dataclasses
import sqlite3

import chess
import pytest

from chessdb.db import connect, connect_readonly
from chessdb.db.api import (
    count_rows,
    distinct_metric_versions,
    engine_ids,
    ensure_engine,
    ensure_position,
    evals_for_position,
    get_game,
    get_position,
    get_position_by_id,
    insert_evals,
    insert_game,
    list_engines,
    metrics_for_position,
    positions_for_game,
    positions_ladder_prefix_scores,
    positions_missing_rungs,
    positions_with_full_ladder,
    replace_position_metrics,
)
from chessdb.db.migrations import MIGRATIONS
from chessdb.db.model import (
    EngineSpec,
    EvalRow,
    GameRecord,
    LimitKind,
    PositionMetricsRow,
    ScoreKind,
    normalize_epd,
)
from chessdb.engine.ladder import NODE_LADDER

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_fresh_connect_creates_tables(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    for table in ("engines", "games", "positions", "evals", "position_metrics"):
        assert count_rows(conn, table) == 0


def test_reconnect_is_idempotent(tmp_path):
    db_path = tmp_path / "x.db"
    connect(db_path).close()
    conn = connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_normalize_epd_strips_counters():
    epd = normalize_epd(START_FEN)
    assert epd == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    other_counters = START_FEN.replace("0 1", "5 10")
    assert normalize_epd(other_counters) == epd


def test_normalize_epd_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_epd("garbage")


def test_ensure_engine_dedupes_and_splits_on_hash_mb(tmp_path):
    conn = connect(tmp_path / "x.db")
    spec = EngineSpec(
        name="stockfish",
        version="17.1",
        binary_sha256="a" * 64,
        threads=1,
        hash_mb=16,
        options={},
    )
    id1 = ensure_engine(conn, spec)
    id2 = ensure_engine(conn, spec)
    assert id1 == id2

    bigger_hash = EngineSpec(**{**spec.__dict__, "hash_mb": 32})
    id3 = ensure_engine(conn, bigger_hash)
    assert id3 != id1


def test_ensure_position_keeps_first_writer_lineage(tmp_path):
    conn = connect(tmp_path / "x.db")
    epd = normalize_epd(START_FEN)
    id1 = ensure_position(conn, epd, source_game_id=None, source_ply=None)
    id2 = ensure_position(conn, epd, source_game_id=1, source_ply=5)
    assert id1 == id2
    pos = get_position(conn, epd)
    assert pos.id == id1
    assert pos.source_game_id is None
    assert pos.source_ply is None


def test_insert_evals_duplicate_pk_is_ignored(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="b" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    row = EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=LimitKind.NODES,
        limit_value=1000,
        score_kind=ScoreKind.CP,
        score=25,
        depth=10,
        seldepth=12,
        nodes=1000,
        time_ms=5,
        bestmove="e2e4",
    )
    assert insert_evals(conn, [row]) == 1
    conn.commit()
    assert count_rows(conn, "evals") == 1

    assert insert_evals(conn, [row]) == 0
    conn.commit()
    assert count_rows(conn, "evals") == 1


def test_eval_round_trip_white_pov(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="c" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    mate_row = EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=LimitKind.DEPTH,
        limit_value=20,
        score_kind=ScoreKind.MATE,
        score=-3,
        depth=20,
        seldepth=None,
        nodes=500,
        time_ms=10,
        bestmove=None,
    )
    insert_evals(conn, [mate_row])
    conn.commit()

    [readback] = evals_for_position(conn, position_id)
    assert readback == mate_row


def test_count_rows_rejects_unknown_table(tmp_path):
    conn = connect(tmp_path / "x.db")
    with pytest.raises(ValueError):
        count_rows(conn, "sqlite_master")


def test_get_game_round_trip(tmp_path):
    conn = connect(tmp_path / "x.db")
    game_id = insert_game(
        conn,
        GameRecord(
            seed=42,
            sampler_config_json='{"foo": 1}',
            moves_uci="e2e4 e7e5",
            result="1-0",
            ply_count=2,
        ),
    )
    game = get_game(conn, game_id)
    assert game.id == game_id
    assert game.seed == 42
    assert game.sampler_config_json == '{"foo": 1}'
    assert game.moves_uci == "e2e4 e7e5"
    assert game.result == "1-0"
    assert game.ply_count == 2


def test_get_game_missing_returns_none(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert get_game(conn, 999) is None


def test_positions_for_game_ordered_by_source_ply(tmp_path):
    conn = connect(tmp_path / "x.db")
    game_id = insert_game(
        conn,
        GameRecord(
            seed=1,
            sampler_config_json="{}",
            moves_uci="e2e4",
            result=None,
            ply_count=1,
        ),
    )
    other_game_id = insert_game(
        conn,
        GameRecord(
            seed=2,
            sampler_config_json="{}",
            moves_uci="d2d4",
            result=None,
            ply_count=1,
        ),
    )
    board_a = chess.Board(START_FEN)
    board_b = chess.Board(START_FEN)
    board_b.push_uci("e2e4")
    board_c = chess.Board(START_FEN)
    board_c.push_uci("d2d4")
    ensure_position(conn, board_a.epd(), source_game_id=game_id, source_ply=10)
    ensure_position(conn, board_b.epd(), source_game_id=game_id, source_ply=3)
    ensure_position(conn, board_c.epd(), other_game_id, 1)

    rows = positions_for_game(conn, game_id)
    assert [r.source_ply for r in rows] == [3, 10]
    assert all(r.source_game_id == game_id for r in rows)


def _eval_row(position_id, engine_id, limit_kind, limit_value):
    return EvalRow(
        position_id=position_id,
        engine_id=engine_id,
        limit_kind=limit_kind,
        limit_value=limit_value,
        score_kind=ScoreKind.CP,
        score=1,
        depth=1,
        seldepth=None,
        nodes=limit_value,
        time_ms=1,
        bestmove=None,
    )


def test_positions_missing_rungs_anti_join(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="d" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    other_engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="e" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    rungs = [1000, 5000, 10000]

    def epd_after(*uci_moves):
        board = chess.Board(START_FEN)
        for m in uci_moves:
            board.push_uci(m)
        return board.epd()

    full_id = ensure_position(conn, epd_after())
    partial_id = ensure_position(conn, epd_after("e2e4"))
    none_id = ensure_position(conn, epd_after("d2d4"))
    foreign_id = ensure_position(conn, epd_after("c2c4"))
    wrong_kind_id = ensure_position(conn, epd_after("g1f3"))

    insert_evals(
        conn, [_eval_row(full_id, engine_id, LimitKind.NODES, r) for r in rungs]
    )
    insert_evals(conn, [_eval_row(partial_id, engine_id, LimitKind.NODES, 1000)])
    insert_evals(
        conn,
        [_eval_row(foreign_id, other_engine_id, LimitKind.NODES, r) for r in rungs],
    )
    insert_evals(conn, [_eval_row(wrong_kind_id, engine_id, LimitKind.DEPTH, 10)])
    conn.commit()

    pending = positions_missing_rungs(conn, engine_id, rungs)
    by_id = {p.position_id: p for p in pending}

    assert full_id not in by_id
    assert by_id[partial_id].missing_rungs == (5000, 10000)
    assert by_id[partial_id].epd == epd_after("e2e4")
    assert by_id[none_id].missing_rungs == tuple(rungs)
    assert by_id[foreign_id].missing_rungs == tuple(rungs)
    assert by_id[wrong_kind_id].missing_rungs == tuple(rungs)
    assert [p.position_id for p in pending] == sorted(by_id)


def test_positions_missing_rungs_schedules_4m_backfill_for_six_rung_position(
    tmp_path,
):
    conn = connect(tmp_path / "x.db")
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="6" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    six_rungs = NODE_LADDER[:-1]
    assert len(six_rungs) == 6
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    insert_evals(
        conn, [_eval_row(position_id, engine_id, LimitKind.NODES, r) for r in six_rungs]
    )
    conn.commit()

    pending = positions_missing_rungs(conn, engine_id, list(NODE_LADDER))
    by_id = {p.position_id: p for p in pending}
    assert by_id[position_id].missing_rungs == (NODE_LADDER[-1],)


def test_migration_1_to_latest_preserves_data(tmp_path):
    db_path = tmp_path / "v1.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="f" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    insert_evals(conn, [_eval_row(position_id, engine_id, LimitKind.NODES, 1000)])
    conn.commit()
    conn.close()

    migrated = connect(db_path)
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert count_rows(migrated, "engines") == 1
    assert count_rows(migrated, "positions") == 1
    assert count_rows(migrated, "evals") == 1
    assert count_rows(migrated, "position_metrics") == 0
    migrated.close()


def test_migration_2_to_3_preserves_rows(tmp_path):
    db_path = tmp_path / "v2.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(MIGRATIONS[0])
    conn.executescript(MIGRATIONS[1])
    conn.execute("PRAGMA user_version = 2")
    conn.commit()

    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="9" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    insert_evals(conn, [_eval_row(position_id, engine_id, LimitKind.NODES, 1000)])
    conn.execute(
        "INSERT INTO position_metrics(position_id, engine_id, metric_version, "
        "top_rung, sign_flips, cp_range, settle_dev, version_disagreement) "
        "VALUES (?, ?, 1, 1000, 0, 0, 0, NULL)",
        (position_id, engine_id),
    )
    conn.commit()
    conn.close()

    migrated = connect(db_path)
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == 3
    assert count_rows(migrated, "evals") == 1
    rows = metrics_for_position(migrated, position_id)
    assert len(rows) == 1
    assert rows[0].mate_found_rung is None
    migrated.close()


def _seeded_engine(conn, byte):
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


def test_positions_with_full_ladder_complements_missing_rungs(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = _seeded_engine(conn, "d")
    other_engine_id = _seeded_engine(conn, "e")
    rungs = [1000, 5000, 10000]

    def epd_after(*uci_moves):
        board = chess.Board(START_FEN)
        for m in uci_moves:
            board.push_uci(m)
        return board.epd()

    full_id = ensure_position(conn, epd_after())
    partial_id = ensure_position(conn, epd_after("e2e4"))
    foreign_id = ensure_position(conn, epd_after("c2c4"))

    insert_evals(
        conn,
        [
            EvalRow(
                position_id=full_id,
                engine_id=engine_id,
                limit_kind=LimitKind.NODES,
                limit_value=r,
                score_kind=ScoreKind.CP,
                score=10 * i,
                depth=1,
                seldepth=None,
                nodes=r,
                time_ms=1,
                bestmove=None,
            )
            for i, r in enumerate(rungs, start=1)
        ],
    )
    insert_evals(conn, [_eval_row(partial_id, engine_id, LimitKind.NODES, 1000)])
    insert_evals(
        conn,
        [_eval_row(foreign_id, other_engine_id, LimitKind.NODES, r) for r in rungs],
    )
    conn.commit()

    full = positions_with_full_ladder(conn, engine_id, rungs)
    missing = positions_missing_rungs(conn, engine_id, rungs)

    assert [t.position_id for t in full] == [full_id]
    assert full[0].scores == (
        (ScoreKind.CP, 10),
        (ScoreKind.CP, 20),
        (ScoreKind.CP, 30),
    )
    assert {p.position_id for p in missing} == {partial_id, foreign_id}
    assert not {t.position_id for t in full} & {p.position_id for p in missing}


def test_positions_ladder_prefix_scores_returns_whatever_rungs_are_present(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = _seeded_engine(conn, "f")
    rungs = [1000, 5000, 10000]

    full_id = ensure_position(conn, normalize_epd(START_FEN))
    board = chess.Board(START_FEN)
    board.push_uci("e2e4")
    partial_id = ensure_position(conn, board.epd())

    insert_evals(
        conn,
        [_eval_row(full_id, engine_id, LimitKind.NODES, r) for r in rungs],
    )
    insert_evals(conn, [_eval_row(partial_id, engine_id, LimitKind.NODES, 5000)])
    conn.commit()

    trajs = {
        t.position_id: t for t in positions_ladder_prefix_scores(conn, engine_id, rungs)
    }
    assert set(trajs) == {full_id, partial_id}
    assert trajs[full_id].rung_scores == (
        (1000, ScoreKind.CP, 1),
        (5000, ScoreKind.CP, 1),
        (10000, ScoreKind.CP, 1),
    )
    assert trajs[partial_id].rung_scores == ((5000, ScoreKind.CP, 1),)


def test_position_metrics_replace_and_read_round_trip(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = _seeded_engine(conn, "a")
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    assert engine_ids(conn) == [engine_id]

    row = PositionMetricsRow(
        position_id=position_id,
        engine_id=engine_id,
        metric_version=1,
        top_rung=16_000,
        sign_flips=1,
        cp_range=50,
        settle_dev=10,
        version_disagreement=None,
    )
    replace_position_metrics(conn, [row])
    conn.commit()
    assert metrics_for_position(conn, position_id) == [row]

    replaced = dataclasses.replace(row, top_rung=1_000_000, sign_flips=2)
    replace_position_metrics(conn, [replaced])
    conn.commit()
    assert metrics_for_position(conn, position_id) == [replaced]
    assert count_rows(conn, "position_metrics") == 1


def test_connect_readonly_reads_an_existing_db(tmp_path):
    db_path = tmp_path / "x.db"
    conn = connect(db_path)
    position_id = ensure_position(conn, normalize_epd(START_FEN))
    conn.commit()
    conn.close()

    ro = connect_readonly(db_path)
    try:
        assert get_position_by_id(ro, position_id).epd == normalize_epd(START_FEN)
    finally:
        ro.close()


def test_connect_readonly_rejects_writes(tmp_path):
    db_path = tmp_path / "x.db"
    connect(db_path).close()

    ro = connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute(
                "INSERT INTO games(seed, sampler_config_json, moves_uci, "
                "result, ply_count) VALUES (0, '{}', '', NULL, 0)"
            )
    finally:
        ro.close()


def test_connect_readonly_missing_file_fails(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        connect_readonly(tmp_path / "missing.db")


def test_get_position_by_id_missing_returns_none(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert get_position_by_id(conn, 999) is None


def test_get_position_by_id_matches_get_position(tmp_path):
    conn = connect(tmp_path / "x.db")
    epd = normalize_epd(START_FEN)
    position_id = ensure_position(conn, epd)
    conn.commit()
    assert get_position_by_id(conn, position_id) == get_position(conn, epd)


def test_list_engines_round_trip(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert list_engines(conn) == []

    spec = EngineSpec(
        name="stockfish",
        version="17.1",
        binary_sha256="a" * 64,
        threads=1,
        hash_mb=16,
        options={"MultiPV": 4},
    )
    engine_id = ensure_engine(conn, spec)
    conn.commit()

    [row] = list_engines(conn)
    assert row.id == engine_id
    assert row.name == "stockfish"
    assert row.version == "17.1"
    assert row.binary_sha256 == "a" * 64
    assert row.threads == 1
    assert row.hash_mb == 16
    assert row.options_json == '{"MultiPV": 4}'


def test_distinct_metric_versions_reports_only_present_versions(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256="b" * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    assert distinct_metric_versions(conn) == []

    position_id = ensure_position(conn, normalize_epd(START_FEN))
    replace_position_metrics(
        conn,
        [
            PositionMetricsRow(
                position_id=position_id,
                engine_id=engine_id,
                metric_version=v,
                top_rung=1_000,
                sign_flips=0,
                cp_range=0,
                settle_dev=0,
                version_disagreement=None,
            )
            for v in (2, 1)
        ],
    )
    conn.commit()
    assert distinct_metric_versions(conn) == [1, 2]

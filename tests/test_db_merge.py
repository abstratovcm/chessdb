import argparse
import sqlite3

import pytest
from conftest import _args, _NeverStop, _patch_engine

import chessdb.cli.merge as merge_cli
import chessdb.cli.run as run_mod
from chessdb.db import connect
from chessdb.db.api import insert_game
from chessdb.db.merge import MergeError, merge_into
from chessdb.db.migrations import MIGRATIONS
from chessdb.db.model import GameRecord


def _dump(conn):
    """Dump by natural keys, without row ids and time_ms, which vary between
    sharded and sequential runs."""
    games = sorted(
        conn.execute(
            "SELECT seed, sampler_config_json, moves_uci, result, ply_count FROM games"
        ).fetchall()
    )
    positions = sorted(
        conn.execute(
            "SELECT p.epd, g.seed, p.source_ply FROM positions p "
            "LEFT JOIN games g ON g.id = p.source_game_id"
        ).fetchall()
    )
    evals = sorted(
        conn.execute(
            "SELECT p.epd, e.binary_sha256, e.threads, e.hash_mb, e.options_json, "
            "ev.limit_kind, ev.limit_value, ev.score_kind, ev.score, ev.depth, "
            "ev.seldepth, ev.nodes, ev.bestmove "
            "FROM evals ev "
            "JOIN positions p ON p.id = ev.position_id "
            "JOIN engines e ON e.id = ev.engine_id"
        ).fetchall()
    )
    return games, positions, evals


def _run_shard(tmp_path, name, seed, games_target, shards, shard_index):
    db_path = tmp_path / name
    run_mod._run(
        _args(
            db_path,
            seed=seed,
            games_target=games_target,
            workers=1,
            shards=shards,
            shard_index=shard_index,
        ),
        stop_event=_NeverStop(),
    )
    return db_path


def test_merge_sequential_vs_sharded_matches(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    seed, games_target = 500, 6

    sequential_db = tmp_path / "sequential.db"
    run_mod._run(
        _args(sequential_db, seed=seed, games_target=games_target, workers=1),
        stop_event=_NeverStop(),
    )

    shard0_db = _run_shard(tmp_path, "shard0.db", seed, games_target, 2, 0)
    shard1_db = _run_shard(tmp_path, "shard1.db", seed, games_target, 2, 1)

    canonical_db = tmp_path / "canonical.db"
    conn = connect(canonical_db)
    merge_into(conn, shard0_db)
    merge_into(conn, shard1_db)

    seq_conn = connect(sequential_db)
    assert _dump(conn) == _dump(seq_conn)
    seq_conn.close()
    conn.close()


def test_merge_idempotent_remerge_is_all_zero_and_dump_unchanged(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    source_db = tmp_path / "source.db"
    run_mod._run(
        _args(source_db, seed=1, games_target=3, workers=1), stop_event=_NeverStop()
    )

    dest_db = tmp_path / "dest.db"
    conn = connect(dest_db)
    first = merge_into(conn, source_db)
    assert first.games_added == 3
    assert first.evals_added > 0
    dump_after_first = _dump(conn)

    second = merge_into(conn, source_db)
    assert second.games_added == 0
    assert second.positions_added == 0
    assert second.attributions_updated == 0
    assert second.evals_added == 0
    assert second.evals_ignored == first.evals_added
    assert _dump(conn) == dump_after_first
    conn.close()


def test_merge_from_order_independent_natural_key_dump(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    seed, games_target = 700, 6
    shard0_db = _run_shard(tmp_path, "shard0.db", seed, games_target, 2, 0)
    shard1_db = _run_shard(tmp_path, "shard1.db", seed, games_target, 2, 1)

    conn_ab = connect(tmp_path / "dest_ab.db")
    merge_into(conn_ab, shard0_db)
    merge_into(conn_ab, shard1_db)

    conn_ba = connect(tmp_path / "dest_ba.db")
    merge_into(conn_ba, shard1_db)
    merge_into(conn_ba, shard0_db)

    assert _dump(conn_ab) == _dump(conn_ba)
    conn_ab.close()
    conn_ba.close()


def test_merge_raises_on_duplicate_seed_within_source(tmp_path):
    dest = connect(tmp_path / "dest.db")

    source_db = tmp_path / "source.db"
    source = connect(source_db)
    for _ in range(2):
        insert_game(
            source,
            GameRecord(
                seed=1,
                sampler_config_json="{}",
                moves_uci="",
                result=None,
                ply_count=0,
            ),
        )
    source.close()

    with pytest.raises(MergeError, match="duplicate games.seed"):
        merge_into(dest, source_db)
    dest.close()


def test_merge_raises_on_seed_collision_with_divergent_lineage(tmp_path):
    dest = connect(tmp_path / "dest.db")
    insert_game(
        dest,
        GameRecord(
            seed=5,
            sampler_config_json="{}",
            moves_uci="e2e4",
            result=None,
            ply_count=1,
        ),
    )

    source_db = tmp_path / "source.db"
    source = connect(source_db)
    insert_game(
        source,
        GameRecord(
            seed=5,
            sampler_config_json="{}",
            moves_uci="d2d4",
            result=None,
            ply_count=1,
        ),
    )
    source.close()

    with pytest.raises(MergeError, match="lineage divergence"):
        merge_into(dest, source_db)
    dest.close()


def test_merge_raises_on_user_version_mismatch(tmp_path):
    dest_db = tmp_path / "dest.db"
    connect(dest_db).close()

    source_db = tmp_path / "source.db"
    source_conn = sqlite3.connect(source_db)
    source_conn.executescript(MIGRATIONS[0])
    source_conn.execute("PRAGMA user_version = 1")
    source_conn.commit()
    source_conn.close()

    dest = connect(dest_db)
    with pytest.raises(MergeError, match="user_version mismatch"):
        merge_into(dest, source_db)
    dest.close()


def test_merge_cli_wraps_merge_error_as_system_exit(tmp_path):
    dest_db = tmp_path / "dest.db"
    connect(dest_db).close()

    source_db = tmp_path / "source.db"
    source_conn = sqlite3.connect(source_db)
    source_conn.executescript(MIGRATIONS[0])
    source_conn.execute("PRAGMA user_version = 1")
    source_conn.commit()
    source_conn.close()

    args = argparse.Namespace(db=dest_db, sources=[source_db])
    with pytest.raises(SystemExit):
        merge_cli._run(args)

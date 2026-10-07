import chess
from conftest import _args, _CountdownStopEvent, _NeverStop, _patch_engine, _strip_time

import chessdb.cli.run as run_mod
from chessdb.db import connect
from chessdb.db.api import (
    count_rows,
    ensure_engine,
    ensure_position,
    evals_for_position,
    game_seeds,
    get_game,
    insert_game,
    positions_for_game,
    positions_missing_rungs,
)
from chessdb.db.checkpoint import upload_checkpoint
from chessdb.db.model import EngineSpec, GameRecord

_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _epd_after(*uci_moves):
    board = chess.Board(_START_FEN)
    for move in uci_moves:
        board.push_uci(move)
    return board.epd()


def _seeded_engine(conn, sha_byte):
    return ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version="17.1",
            binary_sha256=sha_byte * 64,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )


def _blank_game(conn, seed):
    return insert_game(
        conn,
        GameRecord(
            seed=seed,
            sampler_config_json="{}",
            moves_uci="",
            result=None,
            ply_count=0,
        ),
    )


def test_wanted_seeds_partition_disjoint_and_exhaustive():
    seed, games_target = 10, 13
    for shards in (2, 3):
        per_shard = [
            set(run_mod._wanted_seeds(seed, games_target, shards, k))
            for k in range(shards)
        ]
        union = set().union(*per_shard)
        assert union == set(range(seed, seed + games_target))
        for i in range(shards):
            for j in range(i + 1, shards):
                assert per_shard[i].isdisjoint(per_shard[j])


def test_positions_missing_rungs_shard_partition_disjoint_and_exhaustive(tmp_path):
    conn = connect(tmp_path / "x.db")
    engine_id = _seeded_engine(conn, "a")
    rungs = [1000, 4000, 16000]

    seeds = range(6)
    position_ids = []
    for seed in seeds:
        game_id = _blank_game(conn, seed)
        position_ids.append(ensure_position(conn, f"epd-seed-{seed}", game_id, 0))
    null_source_id = ensure_position(conn, "epd-null-source", None, None)
    position_ids.append(null_source_id)
    conn.commit()

    unsharded = {p.position_id for p in positions_missing_rungs(conn, engine_id, rungs)}
    assert unsharded == set(position_ids)

    for shards in (2, 3):
        per_shard = [
            {
                p.position_id
                for p in positions_missing_rungs(
                    conn, engine_id, rungs, shards=shards, shard_index=k
                )
            }
            for k in range(shards)
        ]
        union = set().union(*per_shard)
        assert union == unsharded
        for i in range(shards):
            for j in range(i + 1, shards):
                assert per_shard[i].isdisjoint(per_shard[j])
        assert null_source_id in per_shard[0]
        for k in range(1, shards):
            assert null_source_id not in per_shard[k]


def test_shard_run_skips_foreign_owned_positions(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    db_path = tmp_path / "x.db"
    conn = connect(db_path)
    _seeded_engine(conn, "b")
    game_id = _blank_game(conn, seed=0)
    ensure_position(conn, _epd_after(), game_id, 0)
    conn.commit()
    conn.close()

    args = _args(
        db_path, seed=0, games_target=1, top_rung=16_000, shards=2, shard_index=1
    )
    run_mod._run(args, stop_event=_NeverStop())

    conn = connect(db_path)
    assert count_rows(conn, "evals") == 0
    assert count_rows(conn, "games") == 1
    conn.close()

    positive_db = tmp_path / "positive.db"
    conn = connect(positive_db)
    _seeded_engine(conn, "b")
    game_id = _blank_game(conn, seed=0)
    ensure_position(conn, _epd_after(), game_id, 0)
    conn.commit()
    conn.close()
    positive_args = _args(
        positive_db, seed=0, games_target=1, top_rung=16_000, shards=2, shard_index=0
    )
    run_mod._run(positive_args, stop_event=_NeverStop())
    conn = connect(positive_db)
    assert count_rows(conn, "evals") > 0
    conn.close()


def test_fork_order_root_then_subdir_wins(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    drive = tmp_path / "drive"

    root_src = tmp_path / "root_src.sqlite"
    conn = connect(root_src)
    _blank_game(conn, seed=999)
    conn.close()
    upload_checkpoint(root_src, drive)

    forked = tmp_path / "forked.sqlite"
    args = _args(
        forked,
        seed=0,
        games_target=0,
        top_rung=16_000,
        drive_dir=drive,
        shards=2,
        shard_index=0,
    )
    run_mod._run(args, stop_event=_NeverStop())
    conn = connect(forked)
    assert set(game_seeds(conn)) == {999}
    conn.close()

    subdir_src = tmp_path / "subdir_src.sqlite"
    conn = connect(subdir_src)
    _blank_game(conn, seed=1999)
    conn.close()
    upload_checkpoint(subdir_src, drive / "s0of2")

    forked2 = tmp_path / "forked2.sqlite"
    args2 = _args(
        forked2,
        seed=0,
        games_target=0,
        top_rung=16_000,
        drive_dir=drive,
        shards=2,
        shard_index=0,
    )
    run_mod._run(args2, stop_event=_NeverStop())
    conn = connect(forked2)
    assert set(game_seeds(conn)) == {1999}
    conn.close()


def test_shard_kill_resume_converges_to_uninterrupted_shard_run(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    seed = 100
    games_target = 6
    shards = 2
    shard_index = 0

    full_db = tmp_path / "full.db"
    run_mod._run(
        _args(
            full_db,
            seed=seed,
            games_target=games_target,
            workers=1,
            shards=shards,
            shard_index=shard_index,
        ),
        stop_event=_NeverStop(),
    )
    conn_full = connect(full_db)
    full_games = count_rows(conn_full, "games")
    assert full_games == 3
    for game_id in range(1, full_games + 1):
        assert get_game(conn_full, game_id).seed % shards == shard_index

    resumed_db = tmp_path / "resumed.db"
    interrupted = _CountdownStopEvent(trigger_after=3)
    run_mod._run(
        _args(
            resumed_db,
            seed=seed,
            games_target=games_target,
            workers=1,
            shards=shards,
            shard_index=shard_index,
        ),
        stop_event=interrupted,
    )
    conn_partial = connect(resumed_db)
    partial_games = count_rows(conn_partial, "games")
    conn_partial.close()
    assert 0 <= partial_games < full_games

    run_mod._run(
        _args(
            resumed_db,
            seed=seed,
            games_target=games_target,
            workers=1,
            shards=shards,
            shard_index=shard_index,
        ),
        stop_event=_NeverStop(),
    )

    conn_resumed = connect(resumed_db)
    assert count_rows(conn_resumed, "games") == full_games
    for game_id in range(1, full_games + 1):
        game_full = get_game(conn_full, game_id)
        game_resumed = get_game(conn_resumed, game_id)
        assert game_full == game_resumed

        positions_full = positions_for_game(conn_full, game_id)
        positions_resumed = positions_for_game(conn_resumed, game_id)
        assert positions_full == positions_resumed
        for position in positions_full:
            evals_full = [
                _strip_time(r) for r in evals_for_position(conn_full, position.id)
            ]
            evals_resumed = [
                _strip_time(r) for r in evals_for_position(conn_resumed, position.id)
            ]
            assert evals_full == evals_resumed

    conn_full.close()
    conn_resumed.close()

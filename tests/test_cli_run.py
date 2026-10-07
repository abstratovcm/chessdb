import re
import time

import pytest
from conftest import (
    _args,
    _CountdownStopEvent,
    _FakeEngine,
    _NeverStop,
    _patch_engine,
    _strip_time,
)

import chessdb.cli.run as run_mod
import chessdb.gen.game as game_mod
from chessdb.db import connect
from chessdb.db.api import count_rows, evals_for_position, get_game, positions_for_game
from chessdb.engine.ladder import NODE_LADDER

_SUMMARY_RE = re.compile(
    r"^status=(complete|budget) games=(\d+)/(\d+) evals_inserted=(\d+) "
    r"checkpoints=(\d+)$"
)
_PROGRESS_RE = re.compile(
    r"^progress games=(\d+)/(\d+) evals_inserted=(\d+) evals_per_hour=(\d+\.\d)$"
)


class _FailingEvalEngine(_FakeEngine):
    def analyse(self, board, limit, multipv=None, game=None, info=None):
        if multipv is None:
            raise RuntimeError("boom-eval")
        return super().analyse(board, limit, multipv=multipv, game=game, info=info)


def test_run_fixed_point_reaches_complete_with_full_ladder(
    tmp_path, monkeypatch, capsys
):
    _patch_engine(monkeypatch, tmp_path)
    db_path = tmp_path / "x.db"
    args = _args(db_path, seed=10, games_target=3, workers=2, top_rung=16_000)

    run_mod._run(args)
    out = capsys.readouterr().out.strip()

    match = _SUMMARY_RE.match(out)
    assert match is not None
    status, games, target, _evals, checkpoints = match.groups()
    assert status == "complete"
    assert games == target == "3"
    assert checkpoints == "0"

    rungs = tuple(r for r in NODE_LADDER if r <= args.top_rung)
    conn = connect(db_path)
    n_positions = count_rows(conn, "positions")
    assert n_positions > 0
    for game_id in range(1, 4):
        for position in positions_for_game(conn, game_id):
            rows = evals_for_position(conn, position.id)
            assert len(rows) == len(rungs)
            assert sorted(r.limit_value for r in rows) == sorted(rungs)
    conn.close()


def test_run_deadline_mid_run_stops_at_budget(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path)
    db_path = tmp_path / "x.db"
    args = _args(db_path, games_target=100, workers=1, max_hours=3 / 3600)

    class _FakeClock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            value = self.t
            self.t += 1.0
            return value

    run_mod._run(args, clock=_FakeClock())
    out = capsys.readouterr().out.strip()

    match = _SUMMARY_RE.match(out)
    assert match is not None
    status, games, target, _evals, _checkpoints = match.groups()
    assert status == "budget"
    assert target == "100"
    assert int(games) < 100

    conn = connect(db_path)
    assert count_rows(conn, "games") == int(games)
    conn.close()


def test_run_top_rung_must_be_a_ladder_member(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    args = _args(tmp_path / "x.db", top_rung=12_345)
    with pytest.raises(SystemExit):
        run_mod._run(args)


def test_run_worker_exception_clean_shutdown_and_reraise(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path, engine_cls=_FailingEvalEngine)
    db_path = tmp_path / "x.db"
    args = _args(db_path, games_target=1, workers=1, top_rung=4_000)

    with pytest.raises(RuntimeError, match="boom-eval"):
        run_mod._run(args)

    conn = connect(db_path)
    assert count_rows(conn, "games") == 1
    assert count_rows(conn, "evals") == 0
    conn.close()


def test_run_stop_event_then_resume_matches_uninterrupted_run(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    games_target = 6

    full_db = tmp_path / "full.db"
    run_mod._run(
        _args(full_db, seed=100, games_target=games_target, workers=1),
        stop_event=_NeverStop(),
    )

    resumed_db = tmp_path / "resumed.db"
    interrupted = _CountdownStopEvent(trigger_after=3)
    run_mod._run(
        _args(resumed_db, seed=100, games_target=games_target, workers=1),
        stop_event=interrupted,
    )
    conn_partial = connect(resumed_db)
    partial_games = count_rows(conn_partial, "games")
    seeds_partial = {
        get_game(conn_partial, i).seed for i in range(1, partial_games + 1)
    }
    conn_partial.close()
    assert 0 < partial_games < games_target

    run_mod._run(
        _args(resumed_db, seed=100, games_target=games_target, workers=1),
        stop_event=_NeverStop(),
    )

    conn_full = connect(full_db)
    conn_resumed = connect(resumed_db)

    all_seeds = set()
    for game_id in range(1, games_target + 1):
        game_full = get_game(conn_full, game_id)
        game_resumed = get_game(conn_resumed, game_id)
        assert game_full == game_resumed
        all_seeds.add(game_resumed.seed)

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

    assert len(all_seeds) == games_target
    assert seeds_partial.issubset(all_seeds)
    assert seeds_partial != all_seeds

    conn_full.close()
    conn_resumed.close()


def test_run_checkpoint_cadence_under_fake_clock(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path)

    class _FakeClock:
        def __init__(self, step):
            self.t = 0.0
            self.step = step

        def __call__(self):
            value = self.t
            self.t += self.step
            return value

    frequent_db = tmp_path / "frequent.db"
    frequent_drive = tmp_path / "frequent-drive"
    args_frequent = _args(
        frequent_db,
        games_target=2,
        workers=1,
        drive_dir=frequent_drive,
        checkpoint_minutes=1.0,
    )
    run_mod._run(args_frequent, clock=_FakeClock(step=120.0))
    lines_frequent = capsys.readouterr().out.strip().splitlines()
    match_frequent = _SUMMARY_RE.match(lines_frequent[-1])
    assert match_frequent is not None
    checkpoints_frequent = int(match_frequent.group(5))
    assert checkpoints_frequent > 1
    progress_lines = lines_frequent[:-1]
    assert len(progress_lines) == checkpoints_frequent
    assert all(_PROGRESS_RE.match(line) is not None for line in progress_lines)
    assert any(frequent_drive.glob("chessdb-*.sqlite"))

    rare_db = tmp_path / "rare.db"
    rare_drive = tmp_path / "rare-drive"
    args_rare = _args(
        rare_db,
        games_target=2,
        workers=1,
        drive_dir=rare_drive,
        checkpoint_minutes=10_000.0,
    )
    run_mod._run(args_rare, clock=_FakeClock(step=120.0))
    lines_rare = capsys.readouterr().out.strip().splitlines()
    match_rare = _SUMMARY_RE.match(lines_rare[-1])
    assert match_rare is not None
    assert int(match_rare.group(5)) == 1
    assert len(lines_rare) == 2
    assert _PROGRESS_RE.match(lines_rare[0]) is not None
    assert len(list(rare_drive.glob("chessdb-*.sqlite"))) == 1


def _install_reversed_delay(monkeypatch, base_seed, games_target, step=0.08):
    """Later-dispatched seeds finish sooner: completion order reverses
    dispatch (seed) order within a same-instant batch of concurrent tasks."""
    original_play_game = game_mod.play_game

    def _delayed_play_game(engine, config, seed):
        idx = seed - base_seed
        time.sleep((games_target - idx) * step)
        return original_play_game(engine, config, seed)

    monkeypatch.setattr(run_mod, "play_game", _delayed_play_game)


def test_run_workers4_out_of_order_completion_commits_games_in_seed_order(
    tmp_path, monkeypatch
):
    _patch_engine(monkeypatch, tmp_path)
    base_seed = 100
    games_target = 6
    _install_reversed_delay(monkeypatch, base_seed, games_target)

    db_path = tmp_path / "x.db"
    run_mod._run(
        _args(db_path, seed=base_seed, games_target=games_target, workers=4),
        stop_event=_NeverStop(),
    )

    conn = connect(db_path)
    for game_id in range(1, games_target + 1):
        assert get_game(conn, game_id).seed == base_seed + (game_id - 1)
    conn.close()


def test_run_workers4_stop_then_resume_matches_uninterrupted_run(tmp_path, monkeypatch):
    _patch_engine(monkeypatch, tmp_path)
    base_seed = 200
    games_target = 6
    _install_reversed_delay(monkeypatch, base_seed, games_target)

    full_db = tmp_path / "full.db"
    run_mod._run(
        _args(full_db, seed=base_seed, games_target=games_target, workers=4),
        stop_event=_NeverStop(),
    )

    resumed_db = tmp_path / "resumed.db"
    interrupted = _CountdownStopEvent(trigger_after=3)
    run_mod._run(
        _args(resumed_db, seed=base_seed, games_target=games_target, workers=4),
        stop_event=interrupted,
    )
    conn_partial = connect(resumed_db)
    partial_games = count_rows(conn_partial, "games")
    for game_id in range(1, partial_games + 1):
        assert get_game(conn_partial, game_id).seed == base_seed + (game_id - 1)
    seeds_partial = {
        get_game(conn_partial, i).seed for i in range(1, partial_games + 1)
    }
    conn_partial.close()
    assert 0 < partial_games < games_target

    run_mod._run(
        _args(resumed_db, seed=base_seed, games_target=games_target, workers=4),
        stop_event=_NeverStop(),
    )

    conn_full = connect(full_db)
    conn_resumed = connect(resumed_db)

    all_seeds = set()
    for game_id in range(1, games_target + 1):
        game_full = get_game(conn_full, game_id)
        game_resumed = get_game(conn_resumed, game_id)
        assert game_full == game_resumed
        assert game_resumed.seed == base_seed + (game_id - 1)
        all_seeds.add(game_resumed.seed)

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

    assert len(all_seeds) == games_target
    assert seeds_partial.issubset(all_seeds)

    conn_full.close()
    conn_resumed.close()


def test_run_all_workers_dead_at_factory_reraises_without_hang(tmp_path, monkeypatch):
    fake_binary = tmp_path / "fake-stockfish"
    monkeypatch.setattr(
        run_mod, "cached_engine_path", lambda version, variant: fake_binary
    )
    monkeypatch.setattr(run_mod, "compute_sha256", lambda binary: "d" * 64)

    def _dying_factory(binary):
        raise RuntimeError("boom-factory")

    monkeypatch.setattr(run_mod, "open_engine", _dying_factory)
    db_path = tmp_path / "x.db"
    args = _args(db_path, games_target=1, workers=2, top_rung=4_000)

    with pytest.raises(RuntimeError, match="boom-factory"):
        run_mod._run(args)

    conn = connect(db_path)
    assert count_rows(conn, "games") == 0
    conn.close()

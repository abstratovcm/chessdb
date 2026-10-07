"""Killing a real engine run and resuming it matches an uninterrupted run."""

import re
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from chessdb.db import connect
from chessdb.db.api import (
    count_rows,
    evals_for_position,
    get_game,
    metrics_for_position,
    positions_for_game,
)

pytestmark = pytest.mark.engine

_SUMMARY_RE = re.compile(
    r"status=(complete|budget) games=(\d+)/(\d+) evals_inserted=(\d+) "
    r"checkpoints=(\d+)"
)
_GATE_ARGS = [
    "--seed",
    "1",
    "--games-target",
    "2",
    "--max-hours",
    "1",
    "--max-ply",
    "12",
    "--top-rung",
    "16000",
    "--workers",
    "2",
]


def _cmd(db_path):
    return [
        sys.executable,
        "-m",
        "chessdb.cli.main",
        "run",
        "--db",
        str(db_path),
        *_GATE_ARGS,
    ]


def _run_to_completion(db_path, timeout=180):
    proc = subprocess.run(
        _cmd(db_path), capture_output=True, text=True, timeout=timeout, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


def _wait_for_nonempty_evals(db_path, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if db_path.exists():
            try:
                ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                try:
                    n = ro.execute("SELECT count(*) FROM evals").fetchone()[0]
                finally:
                    ro.close()
                if n > 0:
                    return
            except sqlite3.OperationalError:
                pass
        time.sleep(0.2)
    pytest.fail("evals table did not become non-empty before timeout")


def _table_rows(conn, table, exclude=()):
    cols = [
        r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] not in exclude
    ]
    order = ", ".join(cols)
    return conn.execute(f"SELECT {order} FROM {table} ORDER BY {order}").fetchall()


def test_kill_and_resume_matches_uninterrupted_run(tmp_path, engine_binary):
    resumed_db = tmp_path / "resumed.sqlite"

    proc = subprocess.Popen(
        _cmd(resumed_db), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        _wait_for_nonempty_evals(resumed_db)
        proc.send_signal(signal.SIGTERM)
        killed_out, _ = proc.communicate(timeout=60)
    except Exception:
        proc.kill()
        proc.communicate(timeout=10)
        raise
    assert proc.returncode == 0, killed_out
    killed_match = _SUMMARY_RE.search(killed_out)
    assert killed_match is not None, killed_out

    conn = connect(resumed_db)
    partial_games = count_rows(conn, "games")
    partial_seeds = {get_game(conn, i).seed for i in range(1, partial_games + 1)}
    conn.close()
    assert 0 <= partial_games <= 2

    resumed_out = _run_to_completion(resumed_db)
    resumed_match = _SUMMARY_RE.search(resumed_out)
    assert resumed_match is not None and resumed_match.group(1) == "complete", (
        resumed_out
    )
    assert resumed_match.group(2) == resumed_match.group(3) == "2"

    fresh_db = tmp_path / "fresh.sqlite"
    fresh_out = _run_to_completion(fresh_db)
    fresh_match = _SUMMARY_RE.search(fresh_out)
    assert fresh_match is not None and fresh_match.group(1) == "complete", fresh_out

    conn_resumed = sqlite3.connect(resumed_db)
    conn_fresh = sqlite3.connect(fresh_db)

    games_resumed = _table_rows(conn_resumed, "games")
    games_fresh = _table_rows(conn_fresh, "games")
    assert games_resumed == games_fresh
    assert len(games_resumed) == 2

    positions_resumed = _table_rows(conn_resumed, "positions", exclude=("id",))
    positions_fresh = _table_rows(conn_fresh, "positions", exclude=("id",))
    assert positions_resumed == positions_fresh
    assert len(positions_resumed) > 0

    evals_resumed = _table_rows(conn_resumed, "evals", exclude=("time_ms",))
    evals_fresh = _table_rows(conn_fresh, "evals", exclude=("time_ms",))
    assert evals_resumed == evals_fresh
    assert len(evals_resumed) > 0

    all_seeds = {row[0] for row in conn_resumed.execute("SELECT seed FROM games")}
    assert len(all_seeds) == 2
    assert partial_seeds.issubset(all_seeds)

    conn_resumed.close()
    conn_fresh.close()


def test_uninterrupted_run_completes_with_full_ladder_coverage(tmp_path, engine_binary):
    db_path = tmp_path / "complete.sqlite"
    out = _run_to_completion(db_path)
    match = _SUMMARY_RE.search(out)
    assert match is not None and match.group(1) == "complete", out
    assert match.group(2) == match.group(3) == "2"

    conn = connect(db_path)
    rungs = (1_000, 4_000, 16_000)
    for game_id in (1, 2):
        positions = positions_for_game(conn, game_id)
        assert positions
        for position in positions:
            rows = evals_for_position(conn, position.id)
            assert sorted(r.limit_value for r in rows) == sorted(rungs)
    conn.close()


_METRICS_SUMMARY_RE = re.compile(
    r"metric_version=1 engines=(\d+) computed=(\d+) skipped_partial=(\d+)"
)


def _metrics_cmd(db_path, top_rung):
    return [
        sys.executable,
        "-m",
        "chessdb.cli.main",
        "metrics",
        "--db",
        str(db_path),
        "--top-rung",
        str(top_rung),
    ]


def _dump_position_metrics(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT position_id, engine_id, metric_version, top_rung, sign_flips, "
            "cp_range, settle_dev, version_disagreement FROM position_metrics "
            "ORDER BY position_id, engine_id"
        ).fetchall()
    finally:
        conn.close()


def test_run_then_metrics_smoke_every_harvested_position_gets_a_row(
    tmp_path, engine_binary
):
    db_path = tmp_path / "smoke.sqlite"
    _run_to_completion(db_path)

    proc = subprocess.run(
        _metrics_cmd(db_path, 16_000),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    match = _METRICS_SUMMARY_RE.search(proc.stdout.strip())
    assert match is not None, proc.stdout
    assert match.group(3) == "0"

    conn = connect(db_path)
    for game_id in (1, 2):
        for position in positions_for_game(conn, game_id):
            assert metrics_for_position(conn, position.id)
    conn.close()

    first_dump = _dump_position_metrics(db_path)
    proc2 = subprocess.run(
        _metrics_cmd(db_path, 16_000),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    second_dump = _dump_position_metrics(db_path)
    assert first_dump == second_dump

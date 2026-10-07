import sqlite3

from chessdb.db import connect
from chessdb.db.api import ensure_engine, ensure_position, insert_evals, insert_game
from chessdb.db.checkpoint import backup_db, newest_checkpoint, upload_checkpoint
from chessdb.db.model import EngineSpec, EvalRow, GameRecord, LimitKind, ScoreKind

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"


def _fetch_all_rows(conn, table):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    order = ", ".join(cols)
    return conn.execute(f"SELECT {order} FROM {table} ORDER BY {order}").fetchall()


def _seeded_conn(tmp_path, name="src.db"):
    conn = connect(tmp_path / name)
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
    game_id = insert_game(
        conn,
        GameRecord(
            seed=1, sampler_config_json="{}", moves_uci="e2e4", result=None, ply_count=1
        ),
    )
    position_id = ensure_position(conn, START_FEN, source_game_id=game_id, source_ply=0)
    insert_evals(
        conn,
        [
            EvalRow(
                position_id=position_id,
                engine_id=engine_id,
                limit_kind=LimitKind.NODES,
                limit_value=1000,
                score_kind=ScoreKind.CP,
                score=10,
                depth=5,
                seldepth=None,
                nodes=1000,
                time_ms=1,
                bestmove="e2e4",
            )
        ],
    )
    conn.commit()
    return conn


def test_backup_db_matches_source_row_for_row(tmp_path):
    conn = _seeded_conn(tmp_path)
    dest = tmp_path / "backup.sqlite"
    backup_db(conn, dest)

    backup_conn = sqlite3.connect(dest)
    for table in ("engines", "games", "positions", "evals"):
        assert _fetch_all_rows(backup_conn, table) == _fetch_all_rows(conn, table)
    backup_conn.close()


def test_upload_checkpoint_copies_into_drive_dir(tmp_path):
    conn = _seeded_conn(tmp_path)
    backup_path = tmp_path / "backup.sqlite"
    backup_db(conn, backup_path)

    drive_dir = tmp_path / "drive"
    dest = upload_checkpoint(backup_path, drive_dir, keep=3)

    assert dest.parent == drive_dir
    assert dest.name.startswith("chessdb-") and dest.name.endswith(".sqlite")
    assert dest.read_bytes() == backup_path.read_bytes()


def test_upload_checkpoint_rotation_keeps_newest_n(tmp_path):
    conn = _seeded_conn(tmp_path)
    backup_path = tmp_path / "backup.sqlite"
    backup_db(conn, backup_path)

    drive_dir = tmp_path / "drive"
    drive_dir.mkdir()
    stale_names = [
        "chessdb-20200101-000000.sqlite",
        "chessdb-20200102-000000.sqlite",
        "chessdb-20200103-000000.sqlite",
    ]
    for name in stale_names:
        (drive_dir / name).write_bytes(b"stale")

    newest = upload_checkpoint(backup_path, drive_dir, keep=3)

    remaining = sorted(p.name for p in drive_dir.glob("chessdb-*.sqlite"))
    assert len(remaining) == 3
    assert newest.name in remaining
    assert stale_names[0] not in remaining


def test_newest_checkpoint_missing_and_empty_dir(tmp_path):
    assert newest_checkpoint(tmp_path / "does-not-exist") is None

    empty = tmp_path / "empty"
    empty.mkdir()
    assert newest_checkpoint(empty) is None


def test_newest_checkpoint_returns_max_by_name(tmp_path):
    drive_dir = tmp_path / "drive"
    drive_dir.mkdir()
    for name in (
        "chessdb-20200101-000000.sqlite",
        "chessdb-20211231-235959.sqlite",
        "chessdb-20200601-120000.sqlite",
    ):
        (drive_dir / name).write_bytes(b"x")
    assert newest_checkpoint(drive_dir).name == "chessdb-20211231-235959.sqlite"

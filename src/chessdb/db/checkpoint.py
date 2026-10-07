"""SQLite backup to a local file, then a copy to the Drive checkpoint dir."""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_CHECKPOINT_GLOB = "chessdb-*.sqlite"
# Shard checkpoints live in s{k}of{N}/; one tag per dir keeps filename order.
_SHARD_DIR_RE = re.compile(r"^s\d+of\d+$")


def backup_db(conn: sqlite3.Connection, dest: Path) -> None:
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    backup_conn = sqlite3.connect(tmp)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    tmp.replace(dest)


def upload_checkpoint(db_path_backup: Path, drive_dir: Path, keep: int = 3) -> Path:
    drive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    tag = f"{drive_dir.name}-" if _SHARD_DIR_RE.match(drive_dir.name) else ""
    dest = drive_dir / f"chessdb-{tag}{stamp}.sqlite"
    shutil.copyfile(db_path_backup, dest)
    for stale in sorted(drive_dir.glob(_CHECKPOINT_GLOB), reverse=True)[keep:]:
        stale.unlink()
    return dest


def newest_checkpoint(drive_dir: Path) -> Path | None:
    if not drive_dir.is_dir():
        return None
    checkpoints = sorted(drive_dir.glob(_CHECKPOINT_GLOB), reverse=True)
    return checkpoints[0] if checkpoints else None

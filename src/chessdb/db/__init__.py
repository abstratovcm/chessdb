import sqlite3
from pathlib import Path

from chessdb.db.migrations import migrate


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    migrate(conn)
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Opens `path` read-only and never migrates; a concurrent WAL writer is fine.
    check_same_thread=False because FastAPI may close it on another thread."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

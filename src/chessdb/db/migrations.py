import sqlite3

# Entry i migrates user_version i to i+1. Append only, never edit an entry.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE engines(
      id            INTEGER PRIMARY KEY,
      name          TEXT NOT NULL,
      version       TEXT NOT NULL,
      binary_sha256 TEXT NOT NULL,
      threads       INTEGER NOT NULL,
      hash_mb       INTEGER NOT NULL,
      options_json  TEXT NOT NULL DEFAULT '{}',
      UNIQUE(binary_sha256, threads, hash_mb, options_json)
    );

    CREATE TABLE games(
      id                  INTEGER PRIMARY KEY,
      seed                INTEGER NOT NULL,
      sampler_config_json TEXT NOT NULL,
      moves_uci           TEXT NOT NULL,
      result              TEXT,
      ply_count           INTEGER NOT NULL
    );

    CREATE TABLE positions(
      id             INTEGER PRIMARY KEY,
      epd            TEXT NOT NULL UNIQUE,
      source_game_id INTEGER REFERENCES games(id),
      source_ply     INTEGER
    );

    CREATE TABLE evals(
      position_id INTEGER NOT NULL REFERENCES positions(id),
      engine_id   INTEGER NOT NULL REFERENCES engines(id),
      limit_kind  INTEGER NOT NULL,
      limit_value INTEGER NOT NULL,
      score_kind  INTEGER NOT NULL,
      score       INTEGER NOT NULL,
      depth       INTEGER NOT NULL,
      seldepth    INTEGER,
      nodes       INTEGER NOT NULL,
      time_ms     INTEGER NOT NULL,
      bestmove    TEXT,
      PRIMARY KEY(position_id, engine_id, limit_kind, limit_value)
    ) WITHOUT ROWID;
    """,
    """
    CREATE TABLE position_metrics(
      position_id          INTEGER NOT NULL REFERENCES positions(id),
      engine_id            INTEGER NOT NULL REFERENCES engines(id),
      metric_version       INTEGER NOT NULL,
      top_rung             INTEGER NOT NULL,
      sign_flips           INTEGER NOT NULL,
      cp_range             INTEGER NOT NULL,
      settle_dev           INTEGER NOT NULL,
      version_disagreement INTEGER,
      PRIMARY KEY (position_id, engine_id, metric_version)
    ) WITHOUT ROWID;
    """,
    """
    ALTER TABLE position_metrics ADD COLUMN mate_found_rung INTEGER;
    """,
]


def migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for i in range(current, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[i])
        conn.execute(f"PRAGMA user_version = {i + 1}")
    conn.commit()

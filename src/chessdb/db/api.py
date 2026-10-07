import json
import sqlite3

from chessdb.db.model import (
    EngineRow,
    EngineSpec,
    EvalRow,
    GameRecord,
    GameRow,
    LadderPrefixTrajectory,
    LadderTrajectory,
    LimitKind,
    PendingLadder,
    PositionMetricsRow,
    PositionRow,
    ScoreKind,
)

_COUNTABLE_TABLES = {"engines", "games", "positions", "evals", "position_metrics"}


def ensure_engine(conn: sqlite3.Connection, spec: EngineSpec) -> int:
    options_json = json.dumps(spec.options, sort_keys=True)
    row = conn.execute(
        "SELECT id FROM engines WHERE binary_sha256=? AND threads=? "
        "AND hash_mb=? AND options_json=?",
        (spec.binary_sha256, spec.threads, spec.hash_mb, options_json),
    ).fetchone()
    if row is not None:
        return row[0]
    cur = conn.execute(
        "INSERT INTO engines(name, version, binary_sha256, threads, hash_mb, "
        "options_json) VALUES (?, ?, ?, ?, ?, ?)",
        (
            spec.name,
            spec.version,
            spec.binary_sha256,
            spec.threads,
            spec.hash_mb,
            options_json,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_game(conn: sqlite3.Connection, game: GameRecord) -> int:
    cur = conn.execute(
        "INSERT INTO games(seed, sampler_config_json, moves_uci, result, "
        "ply_count) VALUES (?, ?, ?, ?, ?)",
        (
            game.seed,
            game.sampler_config_json,
            game.moves_uci,
            game.result,
            game.ply_count,
        ),
    )
    conn.commit()
    return cur.lastrowid


def ensure_position(
    conn: sqlite3.Connection,
    epd: str,
    source_game_id: int | None = None,
    source_ply: int | None = None,
) -> int:
    row = conn.execute("SELECT id FROM positions WHERE epd=?", (epd,)).fetchone()
    if row is not None:
        return row[0]
    cur = conn.execute(
        "INSERT INTO positions(epd, source_game_id, source_ply) VALUES (?, ?, ?)",
        (epd, source_game_id, source_ply),
    )
    conn.commit()
    return cur.lastrowid


def insert_evals(conn: sqlite3.Connection, evals: list[EvalRow]) -> int:
    cur = conn.executemany(
        "INSERT OR IGNORE INTO evals(position_id, engine_id, limit_kind, "
        "limit_value, score_kind, score, depth, seldepth, nodes, time_ms, "
        "bestmove) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                e.position_id,
                e.engine_id,
                int(e.limit_kind),
                e.limit_value,
                int(e.score_kind),
                e.score,
                e.depth,
                e.seldepth,
                e.nodes,
                e.time_ms,
                e.bestmove,
            )
            for e in evals
        ],
    )
    return cur.rowcount


def get_position(conn: sqlite3.Connection, epd: str) -> PositionRow | None:
    row = conn.execute(
        "SELECT id, epd, source_game_id, source_ply FROM positions WHERE epd=?",
        (epd,),
    ).fetchone()
    if row is None:
        return None
    return PositionRow(*row)


def get_position_by_id(
    conn: sqlite3.Connection, position_id: int
) -> PositionRow | None:
    row = conn.execute(
        "SELECT id, epd, source_game_id, source_ply FROM positions WHERE id=?",
        (position_id,),
    ).fetchone()
    if row is None:
        return None
    return PositionRow(*row)


def list_engines(conn: sqlite3.Connection) -> list[EngineRow]:
    rows = conn.execute(
        "SELECT id, name, version, binary_sha256, threads, hash_mb, options_json "
        "FROM engines ORDER BY id"
    ).fetchall()
    return [EngineRow(*row) for row in rows]


def distinct_metric_versions(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT metric_version FROM position_metrics ORDER BY metric_version"
    ).fetchall()
    return [r[0] for r in rows]


def get_game(conn: sqlite3.Connection, game_id: int) -> GameRow | None:
    row = conn.execute(
        "SELECT id, seed, sampler_config_json, moves_uci, result, ply_count "
        "FROM games WHERE id=?",
        (game_id,),
    ).fetchone()
    if row is None:
        return None
    return GameRow(*row)


def positions_for_game(conn: sqlite3.Connection, game_id: int) -> list[PositionRow]:
    rows = conn.execute(
        "SELECT id, epd, source_game_id, source_ply FROM positions "
        "WHERE source_game_id=? ORDER BY source_ply",
        (game_id,),
    ).fetchall()
    return [PositionRow(*row) for row in rows]


def evals_for_position(conn: sqlite3.Connection, position_id: int) -> list[EvalRow]:
    rows = conn.execute(
        "SELECT position_id, engine_id, limit_kind, limit_value, score_kind, "
        "score, depth, seldepth, nodes, time_ms, bestmove FROM evals "
        "WHERE position_id=? ORDER BY engine_id, limit_kind, limit_value",
        (position_id,),
    ).fetchall()
    return [
        EvalRow(
            position_id=r[0],
            engine_id=r[1],
            limit_kind=LimitKind(r[2]),
            limit_value=r[3],
            score_kind=ScoreKind(r[4]),
            score=r[5],
            depth=r[6],
            seldepth=r[7],
            nodes=r[8],
            time_ms=r[9],
            bestmove=r[10],
        )
        for r in rows
    ]


def positions_missing_rungs(
    conn: sqlite3.Connection,
    engine_id: int,
    rungs: list[int],
    shards: int = 1,
    shard_index: int = 0,
) -> list[PendingLadder]:
    if not rungs:
        return []
    placeholders = ",".join("?" for _ in rungs)
    rows = conn.execute(
        "SELECT p.id, p.epd, GROUP_CONCAT(e.limit_value) FROM positions p "
        "LEFT JOIN games g ON g.id = p.source_game_id "
        "LEFT JOIN evals e ON e.position_id = p.id AND e.engine_id = ? "
        f"AND e.limit_kind = ? AND e.limit_value IN ({placeholders}) "
        "WHERE COALESCE(g.seed, 0) % ? = ? "
        "GROUP BY p.id ORDER BY p.id",
        (engine_id, int(LimitKind.NODES), *rungs, shards, shard_index),
    ).fetchall()
    result = []
    for position_id, epd, present_csv in rows:
        present = {int(v) for v in present_csv.split(",")} if present_csv else set()
        missing = tuple(r for r in rungs if r not in present)
        if missing:
            result.append(PendingLadder(position_id, epd, missing))
    return result


def positions_with_full_ladder(
    conn: sqlite3.Connection, engine_id: int, rungs: list[int]
) -> list[LadderTrajectory]:
    if not rungs:
        return []
    placeholders = ",".join("?" for _ in rungs)
    rows = conn.execute(
        "SELECT position_id, score_kind, score FROM evals "
        "WHERE engine_id = ? AND limit_kind = ? "
        f"AND limit_value IN ({placeholders}) "
        "AND position_id IN ("
        "SELECT e.position_id FROM evals e "
        "WHERE e.engine_id = ? AND e.limit_kind = ? "
        f"AND e.limit_value IN ({placeholders}) "
        "GROUP BY e.position_id "
        "HAVING COUNT(DISTINCT e.limit_value) = ?"
        ") ORDER BY position_id, limit_value",
        (
            engine_id,
            int(LimitKind.NODES),
            *rungs,
            engine_id,
            int(LimitKind.NODES),
            *rungs,
            len(rungs),
        ),
    ).fetchall()
    scores_by_position: dict[int, list[tuple[ScoreKind, int]]] = {}
    order: list[int] = []
    for position_id, score_kind, score in rows:
        if position_id not in scores_by_position:
            order.append(position_id)
        scores_by_position.setdefault(position_id, []).append(
            (ScoreKind(score_kind), score)
        )
    return [
        LadderTrajectory(position_id=pid, scores=tuple(scores_by_position[pid]))
        for pid in order
    ]


def positions_ladder_prefix_scores(
    conn: sqlite3.Connection, engine_id: int, rungs: list[int]
) -> list[LadderPrefixTrajectory]:
    """Raw evals for every rung in `rungs` a position has, with no full ladder
    requirement (unlike `positions_with_full_ladder`)."""
    if not rungs:
        return []
    placeholders = ",".join("?" for _ in rungs)
    rows = conn.execute(
        "SELECT position_id, limit_value, score_kind, score FROM evals "
        "WHERE engine_id = ? AND limit_kind = ? "
        f"AND limit_value IN ({placeholders}) "
        "ORDER BY position_id, limit_value",
        (engine_id, int(LimitKind.NODES), *rungs),
    ).fetchall()
    scores_by_position: dict[int, list[tuple[int, ScoreKind, int]]] = {}
    order: list[int] = []
    for position_id, limit_value, score_kind, score in rows:
        if position_id not in scores_by_position:
            order.append(position_id)
        scores_by_position.setdefault(position_id, []).append(
            (limit_value, ScoreKind(score_kind), score)
        )
    return [
        LadderPrefixTrajectory(
            position_id=pid, rung_scores=tuple(scores_by_position[pid])
        )
        for pid in order
    ]


def replace_position_metrics(
    conn: sqlite3.Connection, rows: list[PositionMetricsRow]
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO position_metrics(position_id, engine_id, "
        "metric_version, top_rung, sign_flips, cp_range, settle_dev, "
        "version_disagreement, mate_found_rung) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.position_id,
                r.engine_id,
                r.metric_version,
                r.top_rung,
                r.sign_flips,
                r.cp_range,
                r.settle_dev,
                r.version_disagreement,
                r.mate_found_rung,
            )
            for r in rows
        ],
    )


def metrics_for_position(
    conn: sqlite3.Connection, position_id: int
) -> list[PositionMetricsRow]:
    rows = conn.execute(
        "SELECT position_id, engine_id, metric_version, top_rung, sign_flips, "
        "cp_range, settle_dev, version_disagreement, mate_found_rung "
        "FROM position_metrics WHERE position_id = ? ORDER BY engine_id, metric_version",
        (position_id,),
    ).fetchall()
    return [PositionMetricsRow(*row) for row in rows]


def engine_ids(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT id FROM engines ORDER BY id")]


def game_seeds(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT DISTINCT seed FROM games ORDER BY seed")]


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    if table not in _COUNTABLE_TABLES:
        raise ValueError(f"unknown table: {table}")
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]

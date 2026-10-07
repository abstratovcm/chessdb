"""Idempotent merge of shard checkpoints into a canonical DB. Shards open
read-only and the result does not depend on their order."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from chessdb.db import connect_readonly
from chessdb.db.api import schema_version


class MergeError(Exception):
    pass


@dataclass(frozen=True)
class MergeStats:
    games_added: int
    positions_added: int
    attributions_updated: int
    evals_added: int
    evals_ignored: int


def _assert_unique_seeds(conn: sqlite3.Connection, label: str) -> None:
    dupes = conn.execute(
        "SELECT seed FROM games GROUP BY seed HAVING COUNT(*) > 1"
    ).fetchall()
    if dupes:
        raise MergeError(
            f"{label}: duplicate games.seed values {sorted(r[0] for r in dupes)}"
        )


def _attribution_key(seed: int | None, ply: int | None) -> tuple:
    # No source (from `chessdb eval`) wins, then lowest seed, then lowest ply.
    return (0, 0, 0) if seed is None else (1, seed, ply)


def _merge_engines(
    dest: sqlite3.Connection, source: sqlite3.Connection
) -> dict[int, int]:
    dest_by_key = {
        (row[1], row[2], row[3], row[4]): row[0]
        for row in dest.execute(
            "SELECT id, binary_sha256, threads, hash_mb, options_json FROM engines"
        )
    }
    engine_id_map: dict[int, int] = {}
    for src_id, name, version, sha, threads, hash_mb, options_json in source.execute(
        "SELECT id, name, version, binary_sha256, threads, hash_mb, options_json "
        "FROM engines"
    ):
        key = (sha, threads, hash_mb, options_json)
        dest_id = dest_by_key.get(key)
        if dest_id is None:
            cur = dest.execute(
                "INSERT INTO engines(name, version, binary_sha256, threads, "
                "hash_mb, options_json) VALUES (?, ?, ?, ?, ?, ?)",
                (name, version, sha, threads, hash_mb, options_json),
            )
            dest_id = cur.lastrowid
            dest_by_key[key] = dest_id
        engine_id_map[src_id] = dest_id
    return engine_id_map


def _merge_games(
    dest: sqlite3.Connection, source: sqlite3.Connection
) -> tuple[dict[int, int], int]:
    dest_game_id_by_seed = {
        seed: game_id for game_id, seed in dest.execute("SELECT id, seed FROM games")
    }
    dest_lineage_by_seed = {
        seed: (moves_uci, sampler_config_json)
        for _id, seed, sampler_config_json, moves_uci, _result, _ply in dest.execute(
            "SELECT id, seed, sampler_config_json, moves_uci, result, ply_count "
            "FROM games"
        )
    }
    games_added = 0
    for seed, sampler_config_json, moves_uci, result, ply_count in source.execute(
        "SELECT seed, sampler_config_json, moves_uci, result, ply_count "
        "FROM games ORDER BY seed"
    ):
        existing = dest_lineage_by_seed.get(seed)
        if existing is not None:
            if existing != (moves_uci, sampler_config_json):
                raise MergeError(f"seed {seed}: lineage divergence in games")
            continue
        cur = dest.execute(
            "INSERT INTO games(seed, sampler_config_json, moves_uci, result, "
            "ply_count) VALUES (?, ?, ?, ?, ?)",
            (seed, sampler_config_json, moves_uci, result, ply_count),
        )
        dest_game_id_by_seed[seed] = cur.lastrowid
        dest_lineage_by_seed[seed] = (moves_uci, sampler_config_json)
        games_added += 1
    return dest_game_id_by_seed, games_added


def _merge_positions(
    dest: sqlite3.Connection,
    source: sqlite3.Connection,
    dest_game_id_by_seed: dict[int, int],
) -> tuple[dict[str, int], int, int]:
    dest_seed_by_game_id = {v: k for k, v in dest_game_id_by_seed.items()}
    source_seed_by_game_id = {
        game_id: seed for game_id, seed in source.execute("SELECT id, seed FROM games")
    }
    dest_positions = {
        epd: (pid, source_game_id, source_ply)
        for pid, epd, source_game_id, source_ply in dest.execute(
            "SELECT id, epd, source_game_id, source_ply FROM positions"
        )
    }

    positions_added = 0
    attributions_updated = 0
    new_rows = []
    for epd, src_game_id, src_ply in source.execute(
        "SELECT epd, source_game_id, source_ply FROM positions"
    ):
        src_seed = (
            source_seed_by_game_id[src_game_id] if src_game_id is not None else None
        )
        existing = dest_positions.get(epd)
        if existing is None:
            new_rows.append((epd, src_seed, src_ply))
            continue
        _pid, dest_game_id, dest_ply = existing
        dest_seed = (
            dest_seed_by_game_id[dest_game_id] if dest_game_id is not None else None
        )
        if _attribution_key(src_seed, src_ply) < _attribution_key(dest_seed, dest_ply):
            winner_game_id = (
                dest_game_id_by_seed[src_seed] if src_seed is not None else None
            )
            dest.execute(
                "UPDATE positions SET source_game_id = ?, source_ply = ? WHERE epd = ?",
                (winner_game_id, src_ply, epd),
            )
            attributions_updated += 1

    # Content is independent of shard count and order; row ids are not.
    new_rows.sort(key=lambda r: (*_attribution_key(r[1], r[2]), r[0]))
    dest_position_id_by_epd = {epd: pid for epd, (pid, _, _) in dest_positions.items()}
    for epd, seed, ply in new_rows:
        game_id = dest_game_id_by_seed[seed] if seed is not None else None
        cur = dest.execute(
            "INSERT INTO positions(epd, source_game_id, source_ply) VALUES (?, ?, ?)",
            (epd, game_id, ply),
        )
        dest_position_id_by_epd[epd] = cur.lastrowid
        positions_added += 1

    return dest_position_id_by_epd, positions_added, attributions_updated


def _merge_evals(
    dest: sqlite3.Connection,
    source: sqlite3.Connection,
    engine_id_map: dict[int, int],
    dest_position_id_by_epd: dict[str, int],
) -> tuple[int, int]:
    source_epd_by_position_id = {
        pid: epd for pid, epd in source.execute("SELECT id, epd FROM positions")
    }
    params = [
        (
            dest_position_id_by_epd[source_epd_by_position_id[position_id]],
            engine_id_map[engine_id],
            limit_kind,
            limit_value,
            score_kind,
            score,
            depth,
            seldepth,
            nodes,
            time_ms,
            bestmove,
        )
        for (
            position_id,
            engine_id,
            limit_kind,
            limit_value,
            score_kind,
            score,
            depth,
            seldepth,
            nodes,
            time_ms,
            bestmove,
        ) in source.execute(
            "SELECT position_id, engine_id, limit_kind, limit_value, score_kind, "
            "score, depth, seldepth, nodes, time_ms, bestmove FROM evals"
        )
    ]
    if not params:
        return 0, 0
    cur = dest.executemany(
        "INSERT OR IGNORE INTO evals(position_id, engine_id, limit_kind, "
        "limit_value, score_kind, score, depth, seldepth, nodes, time_ms, "
        "bestmove) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        params,
    )
    added = cur.rowcount
    return added, len(params) - added


def merge_into(dest: sqlite3.Connection, source_path: Path) -> MergeStats:
    source = connect_readonly(source_path)
    try:
        dest_version, source_version = schema_version(dest), schema_version(source)
        if dest_version != source_version:
            raise MergeError(
                f"user_version mismatch: dest={dest_version} "
                f"source={source_version} ({source_path})"
            )
        _assert_unique_seeds(dest, "dest")
        _assert_unique_seeds(source, f"source ({source_path})")

        engine_id_map = _merge_engines(dest, source)
        dest_game_id_by_seed, games_added = _merge_games(dest, source)
        dest_position_id_by_epd, positions_added, attributions_updated = (
            _merge_positions(dest, source, dest_game_id_by_seed)
        )
        evals_added, evals_ignored = _merge_evals(
            dest, source, engine_id_map, dest_position_id_by_epd
        )
    except Exception:
        dest.rollback()
        raise
    finally:
        source.close()

    dest.commit()
    return MergeStats(
        games_added=games_added,
        positions_added=positions_added,
        attributions_updated=attributions_updated,
        evals_added=evals_added,
        evals_ignored=evals_ignored,
    )

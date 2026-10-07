import argparse
from pathlib import Path

from chessdb.db import connect
from chessdb.db.api import (
    engine_ids,
    positions_ladder_prefix_scores,
    positions_missing_rungs,
    positions_with_full_ladder,
    replace_position_metrics,
)
from chessdb.db.model import PositionMetricsRow
from chessdb.engine.ladder import NODE_LADDER
from chessdb.metrics import SHIPPED_METRIC_VERSIONS
from chessdb.metrics.instability import (
    anchor_rung,
    clamp_sequence,
    clamped_by_rung,
    common_rung_disagreement,
    cp_range,
    mate_found_rung,
    prefix_scores,
    settle_dev,
    sign_flips,
    version_disagreement,
)

# metric_version 1 never goes past 1M nodes, whatever --top-rung says.
_V1_TOP_RUNG_CAP = 1_000_000


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "metrics", help="compute versioned instability metrics over stored ladders"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--top-rung", type=int, default=NODE_LADDER[-1])
    parser.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    if args.top_rung not in NODE_LADDER:
        raise SystemExit(
            f"--top-rung must be a NODE_LADDER value {NODE_LADDER}: got {args.top_rung}"
        )

    conn = connect(args.db)
    ids = engine_ids(conn)

    for version in SHIPPED_METRIC_VERSIONS:
        if version == 1:
            cap = min(args.top_rung, _V1_TOP_RUNG_CAP)
            rows, computed, skipped_partial = _compute_v1(conn, ids, cap)
        else:
            rows, computed, skipped_partial = _compute_v2(conn, ids, args.top_rung)
        replace_position_metrics(conn, rows)
        conn.commit()
        print(
            f"metric_version={version} engines={len(ids)} computed={computed} "
            f"skipped_partial={skipped_partial}"
        )

    conn.close()


def _compute_v1(
    conn, ids: list[int], top_rung_cap: int
) -> tuple[list[PositionMetricsRow], int, int]:
    rungs = [r for r in NODE_LADDER if r <= top_rung_cap]
    top_rung = rungs[-1]

    trajectories = {
        engine_id: positions_with_full_ladder(conn, engine_id, rungs)
        for engine_id in ids
    }
    clamped_tops = {
        engine_id: {t.position_id: clamp_sequence(t.scores)[-1] for t in trajs}
        for engine_id, trajs in trajectories.items()
    }

    rows: list[PositionMetricsRow] = []
    computed = 0
    skipped_partial = 0
    for engine_id in ids:
        for traj in trajectories[engine_id]:
            clamped = clamp_sequence(traj.scores)
            others = tuple(
                other_tops[traj.position_id]
                for other_id, other_tops in clamped_tops.items()
                if other_id != engine_id and traj.position_id in other_tops
            )
            rows.append(
                PositionMetricsRow(
                    position_id=traj.position_id,
                    engine_id=engine_id,
                    metric_version=1,
                    top_rung=top_rung,
                    sign_flips=sign_flips(clamped),
                    cp_range=cp_range(clamped),
                    settle_dev=settle_dev(clamped),
                    version_disagreement=version_disagreement(clamped[-1], others),
                )
            )
            computed += 1
        skipped_partial += len(positions_missing_rungs(conn, engine_id, rungs))
    return rows, computed, skipped_partial


def _compute_v2(
    conn, ids: list[int], top_rung_cap: int
) -> tuple[list[PositionMetricsRow], int, int]:
    rungs = tuple(r for r in NODE_LADDER if r <= top_rung_cap)

    trajectories = {
        engine_id: {
            t.position_id: t
            for t in positions_ladder_prefix_scores(conn, engine_id, list(rungs))
        }
        for engine_id in ids
    }
    anchors = {
        engine_id: {
            pid: a
            for pid, t in trajs.items()
            if (a := anchor_rung(t.rung_scores, rungs)) is not None
        }
        for engine_id, trajs in trajectories.items()
    }
    clamped = {
        engine_id: {
            pid: clamped_by_rung(trajectories[engine_id][pid].rung_scores, anchor)
            for pid, anchor in engine_anchors.items()
        }
        for engine_id, engine_anchors in anchors.items()
    }

    rows: list[PositionMetricsRow] = []
    computed = 0
    skipped_partial = 0
    for engine_id in ids:
        for position_id, anchor in anchors[engine_id].items():
            traj = trajectories[engine_id][position_id]
            seq = clamp_sequence(prefix_scores(traj.rung_scores, anchor))
            others = tuple(
                (other_anchors[position_id], clamped[other_id][position_id])
                for other_id, other_anchors in anchors.items()
                if other_id != engine_id and position_id in other_anchors
            )
            rows.append(
                PositionMetricsRow(
                    position_id=position_id,
                    engine_id=engine_id,
                    metric_version=2,
                    top_rung=anchor,
                    sign_flips=sign_flips(seq),
                    cp_range=cp_range(seq),
                    settle_dev=settle_dev(seq),
                    version_disagreement=common_rung_disagreement(
                        clamped[engine_id][position_id], anchor, others
                    ),
                    mate_found_rung=mate_found_rung(traj.rung_scores, anchor),
                )
            )
            computed += 1
        skipped_partial += len(positions_missing_rungs(conn, engine_id, [rungs[0]]))
    return rows, computed, skipped_partial

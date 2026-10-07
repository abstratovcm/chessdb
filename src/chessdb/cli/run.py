import argparse
import os
import shutil
import signal
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chessdb.cli.eval import build_eval_row
from chessdb.db import connect
from chessdb.db.api import (
    ensure_engine,
    ensure_position,
    evals_for_position,
    game_seeds,
    get_game,
    get_position,
    insert_evals,
    insert_game,
    positions_missing_rungs,
)
from chessdb.db.checkpoint import backup_db, newest_checkpoint, upload_checkpoint
from chessdb.db.model import EngineSpec, EvalRow, GameRecord, LimitKind
from chessdb.engine.fetch import cached_engine_path, compute_sha256
from chessdb.engine.ladder import NODE_LADDER
from chessdb.engine.pool import TaskOutcome, WorkerPool
from chessdb.engine.runner import open_engine
from chessdb.gen.game import GeneratedGame, play_game
from chessdb.gen.sampler import SamplerConfig

_POLL_SECONDS = 0.5


@dataclass(frozen=True)
class GenTask:
    seed: int
    config: SamplerConfig

    def run(self, engine) -> GeneratedGame:
        return play_game(engine, self.config, self.seed)


@dataclass(frozen=True)
class EvalTask:
    position_id: int
    epd: str
    missing_rungs: tuple[int, ...]
    engine_id: int

    def run(self, engine) -> list[EvalRow]:
        return [
            build_eval_row(
                engine,
                self.epd,
                self.position_id,
                self.engine_id,
                LimitKind.NODES,
                rung,
            )
            for rung in self.missing_rungs
        ]


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "run", help="orchestrate generation and laddered eval on a worker pool"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--games-target", required=True, type=int)
    parser.add_argument("--max-hours", required=True, type=float)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--version", default="17.1")
    parser.add_argument("--variant", default="x86-64-avx2")
    parser.add_argument("--max-ply", type=int, default=80)
    parser.add_argument("--top-rung", type=int, default=1_000_000)
    parser.add_argument("--drive-dir", type=Path, default=None)
    parser.add_argument("--checkpoint-minutes", type=float, default=15)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.set_defaults(func=_run)


def _effective_drive(args: argparse.Namespace) -> Path | None:
    if args.drive_dir is None:
        return None
    if args.shards <= 1:
        return args.drive_dir
    return args.drive_dir / f"s{args.shard_index}of{args.shards}"


def _shard_suffix(args: argparse.Namespace) -> str:
    return f" shard={args.shard_index}/{args.shards}" if args.shards > 1 else ""


def _wanted_seeds(
    seed: int, games_target: int, shards: int, shard_index: int
) -> list[int]:
    return [s for s in range(seed, seed + games_target) if s % shards == shard_index]


class _Orchestrator:
    def __init__(
        self,
        conn,
        engine_id: int,
        rungs: tuple[int, ...],
        config: SamplerConfig,
        pool: WorkerPool,
        clock: Callable[[], float],
        stop_event: Any,
        args: argparse.Namespace,
    ) -> None:
        self.conn = conn
        self.engine_id = engine_id
        self.rungs = rungs
        self.config = config
        self.pool = pool
        self.clock = clock
        self.stop_event = stop_event
        self.args = args
        self.effective_drive = _effective_drive(args)
        now = clock()
        self.start_time = now
        self.deadline = now + args.max_hours * 3600

        pending = positions_missing_rungs(
            conn,
            engine_id,
            list(rungs),
            shards=args.shards,
            shard_index=args.shard_index,
        )
        self.backlog_eval = deque(
            EvalTask(p.position_id, p.epd, p.missing_rungs, engine_id) for p in pending
        )
        self.eval_queued = {p.position_id for p in pending}

        present = set(game_seeds(conn))
        wanted = _wanted_seeds(
            args.seed, args.games_target, args.shards, args.shard_index
        )
        self.pending_seeds: deque[int] = deque(s for s in wanted if s not in present)
        self.owned_total = len(wanted)
        self._game_seed_cache: dict[int, int] = {}

        self.gen_buffer: dict[int, GeneratedGame] = {}
        self.gen_dispatch_order: deque[int] = deque()

        self.gen_in_flight = 0
        self.eval_in_flight = 0
        self.evals_inserted = 0
        self.checkpoints_done = 0
        self.first_error: BaseException | None = None
        self.last_checkpoint = self.clock()

    @property
    def owned_done(self) -> int:
        return self.owned_total - len(self.pending_seeds)

    def _owning_shard(self, source_game_id: int | None) -> int:
        if source_game_id is None:
            return 0
        if source_game_id not in self._game_seed_cache:
            self._game_seed_cache[source_game_id] = get_game(
                self.conn, source_game_id
            ).seed
        return self._game_seed_cache[source_game_id] % self.args.shards

    def stop_requested(self) -> bool:
        return self.stop_event.is_set() or self.clock() >= self.deadline

    def dispatch(self) -> None:
        while self.gen_in_flight + self.eval_in_flight < self.args.workers:
            if self.backlog_eval:
                self.pool.submit(self.backlog_eval.popleft())
                self.eval_in_flight += 1
                continue
            if self.pending_seeds:
                seed = self.pending_seeds.popleft()
                self.pool.submit(GenTask(seed, self.config))
                self.gen_dispatch_order.append(seed)
                self.gen_in_flight += 1
                continue
            break

    def apply_outcome(self, outcome: TaskOutcome) -> None:
        if outcome.task is None:
            if self.first_error is None:
                self.first_error = outcome.error
            return
        if isinstance(outcome.task, GenTask):
            self.gen_in_flight -= 1
        else:
            self.eval_in_flight -= 1
        if outcome.error is not None:
            if self.first_error is None:
                self.first_error = outcome.error
            return
        if isinstance(outcome.task, GenTask):
            self.gen_buffer[outcome.task.seed] = outcome.result
            self._drain_gen_buffer()
        else:
            self._insert_evals(outcome.task, outcome.result)

    def _drain_gen_buffer(self) -> None:
        while self.gen_dispatch_order and self.gen_dispatch_order[0] in self.gen_buffer:
            seed = self.gen_dispatch_order.popleft()
            self._insert_game(self.gen_buffer.pop(seed))

    def _insert_game(self, game: GeneratedGame) -> None:
        game_id = insert_game(
            self.conn,
            GameRecord(
                seed=game.seed,
                sampler_config_json=self.config.to_json(),
                moves_uci=game.moves_uci,
                result=game.result,
                ply_count=game.ply_count,
            ),
        )
        for harvest in game.harvested:
            existing = get_position(self.conn, harvest.epd)
            if existing is not None:
                if self._owning_shard(existing.source_game_id) != self.args.shard_index:
                    continue
                position_id = existing.id
            else:
                position_id = ensure_position(
                    self.conn, harvest.epd, game_id, harvest.ply
                )
            self._enqueue_eval(position_id, harvest.epd)
        self.conn.commit()

    def _enqueue_eval(self, position_id: int, epd: str) -> None:
        if position_id in self.eval_queued:
            return
        present = {
            row.limit_value
            for row in evals_for_position(self.conn, position_id)
            if row.engine_id == self.engine_id and row.limit_kind is LimitKind.NODES
        }
        missing = tuple(r for r in self.rungs if r not in present)
        if missing:
            self.backlog_eval.append(
                EvalTask(position_id, epd, missing, self.engine_id)
            )
            self.eval_queued.add(position_id)

    def _insert_evals(self, task: EvalTask, rows: list[EvalRow]) -> None:
        n = insert_evals(self.conn, rows)
        self.conn.commit()
        self.evals_inserted += n
        self.eval_queued.discard(task.position_id)

    def maybe_checkpoint(self) -> None:
        if self.args.drive_dir is None:
            return
        if self.clock() - self.last_checkpoint < self.args.checkpoint_minutes * 60:
            return
        self.checkpoint()

    def checkpoint(self) -> None:
        backup_path = self.args.db.with_name(self.args.db.name + ".checkpoint")
        backup_db(self.conn, backup_path)
        upload_checkpoint(backup_path, self.effective_drive)
        self.checkpoints_done += 1
        self.last_checkpoint = self.clock()
        self._print_progress()

    def _print_progress(self) -> None:
        elapsed_hours = (self.clock() - self.start_time) / 3600
        rate = self.evals_inserted / elapsed_hours if elapsed_hours > 0 else 0.0
        print(
            f"progress games={self.owned_done}/{self.owned_total} "
            f"evals_inserted={self.evals_inserted} evals_per_hour={rate:.1f}"
            f"{_shard_suffix(self.args)}"
        )

    def run(self) -> str:
        try:
            while True:
                if self.first_error is None and not self.stop_requested():
                    self.dispatch()
                if self.gen_in_flight + self.eval_in_flight == 0:
                    break
                outcome = self.pool.next_result(timeout=_POLL_SECONDS)
                if outcome is not None:
                    self.apply_outcome(outcome)
                self.maybe_checkpoint()
                in_flight = self.gen_in_flight + self.eval_in_flight
                if self.pool.live_workers == 0 and in_flight > 0:
                    if self.first_error is None:
                        self.first_error = RuntimeError("all workers died")
                    break
        finally:
            if self.args.drive_dir is not None:
                self.checkpoint()
            self.pool.close()

        if self.first_error is not None:
            raise self.first_error
        complete = not self.stop_requested() and not self.pending_seeds
        return "complete" if complete else "budget"


def _install_signal_handlers(stop_event: Any) -> dict:
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, lambda signum, frame: stop_event.set())
    return previous


def _restore_signal_handlers(previous: dict) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def _run(
    args: argparse.Namespace,
    clock: Callable[[], float] = time.monotonic,
    stop_event: Any = None,
) -> None:
    if args.top_rung not in NODE_LADDER:
        raise SystemExit(
            f"--top-rung must be a NODE_LADDER value {NODE_LADDER}: got {args.top_rung}"
        )
    rungs = tuple(r for r in NODE_LADDER if r <= args.top_rung)

    if args.shards < 1:
        raise SystemExit(f"--shards must be >= 1: got {args.shards}")
    if not 0 <= args.shard_index < args.shards:
        raise SystemExit(
            f"--shard-index must satisfy 0 <= shard-index < shards ({args.shards}): "
            f"got {args.shard_index}"
        )
    if args.shards > 1 and args.seed < 0:
        raise SystemExit(f"--seed must be >= 0 when --shards > 1: got {args.seed}")

    try:
        binary = cached_engine_path(args.version, args.variant)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    sha256 = compute_sha256(binary)

    if not args.db.exists() and args.drive_dir is not None:
        effective_drive = _effective_drive(args)
        newest = newest_checkpoint(effective_drive) or newest_checkpoint(args.drive_dir)
        if newest is not None:
            shutil.copyfile(newest, args.db)

    conn = connect(args.db)
    engine_id = ensure_engine(
        conn,
        EngineSpec(
            name="stockfish",
            version=args.version,
            binary_sha256=sha256,
            threads=1,
            hash_mb=16,
            options={},
        ),
    )
    config = SamplerConfig(
        engine_version=args.version,
        engine_variant=args.variant,
        engine_sha256=sha256,
        max_ply=args.max_ply,
    )

    stop_event = stop_event if stop_event is not None else threading.Event()
    previous_handlers = _install_signal_handlers(stop_event)
    pool = WorkerPool(lambda: open_engine(binary), args.workers)
    try:
        orchestrator = _Orchestrator(
            conn, engine_id, rungs, config, pool, clock, stop_event, args
        )
        status = orchestrator.run()
    finally:
        _restore_signal_handlers(previous_handlers)
        conn.close()

    print(
        f"status={status} games={orchestrator.owned_done}/{orchestrator.owned_total} "
        f"evals_inserted={orchestrator.evals_inserted} "
        f"checkpoints={orchestrator.checkpoints_done}"
        f"{_shard_suffix(args)}"
    )

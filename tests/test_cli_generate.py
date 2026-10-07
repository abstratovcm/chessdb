import re

import chess
import chess.engine
import pytest

import chessdb.cli.generate as generate_mod
from chessdb.cli.main import main
from chessdb.db import connect
from chessdb.db.api import get_game, positions_for_game
from chessdb.engine.runner import open_engine
from chessdb.gen.game import play_game
from chessdb.gen.sampler import SamplerConfig

_SUMMARY_RE = re.compile(r"^games=(\d+) plies=(\d+) harvested=(\d+) dup=(\d+)$")


class _FakeMultiPVEngine:
    _CP_SPREAD = (40, 20, 0, -400)

    def analyse(self, board, limit, multipv=1, game=None, info=None):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())[: len(self._CP_SPREAD)]
        return [
            {
                "multipv": rank,
                "score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn),
                "pv": [move],
            }
            for rank, (move, cp) in enumerate(zip(moves, self._CP_SPREAD), start=1)
        ]

    def quit(self):
        pass


def _patch_engine(monkeypatch, tmp_path):
    fake_binary = tmp_path / "fake-stockfish"
    monkeypatch.setattr(
        generate_mod, "cached_engine_path", lambda version, variant: fake_binary
    )
    monkeypatch.setattr(generate_mod, "compute_sha256", lambda binary: "d" * 64)
    monkeypatch.setattr(
        generate_mod, "open_engine", lambda binary: _FakeMultiPVEngine()
    )


def _run_generate(monkeypatch, capsys, db_path, seed, games, max_ply):
    monkeypatch.setattr(
        "sys.argv",
        [
            "chessdb",
            "generate",
            "--db",
            str(db_path),
            "--seed",
            str(seed),
            "--games",
            str(games),
            "--max-ply",
            str(max_ply),
        ],
    )
    main()
    return capsys.readouterr().out


def test_generate_offline_games_and_lineage(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path)
    db_path = tmp_path / "x.db"

    out = _run_generate(monkeypatch, capsys, db_path, seed=100, games=3, max_ply=12)
    match = _SUMMARY_RE.match(out.strip())
    assert match is not None
    n_games, _plies, harvested, dup = (int(g) for g in match.groups())
    assert n_games == 3
    assert harvested > 0
    assert dup == 0

    conn = connect(db_path)
    for i in range(3):
        game = get_game(conn, i + 1)
        assert game.seed == 100 + i
        assert game.sampler_config_json
        assert game.ply_count > 0

    seen_lineage = 0
    for i in range(3):
        for position in positions_for_game(conn, i + 1):
            assert position.source_game_id == i + 1
            assert position.source_ply is not None
            seen_lineage += 1
    assert seen_lineage == harvested
    conn.close()

    # Replaying the same seeds makes every position a duplicate.
    second = _run_generate(monkeypatch, capsys, db_path, seed=100, games=3, max_ply=12)
    match2 = _SUMMARY_RE.match(second.strip())
    assert match2 is not None
    n_games2, _, harvested2, dup2 = (int(g) for g in match2.groups())
    assert n_games2 == 3
    assert harvested2 == 0
    assert dup2 == harvested


@pytest.mark.engine
def test_generate_prints_expected_summary(tmp_path, monkeypatch, capsys, engine_binary):
    db_path = tmp_path / "x.db"
    out = _run_generate(monkeypatch, capsys, db_path, seed=7, games=1, max_ply=16)
    assert _SUMMARY_RE.match(out.strip()) is not None
    assert out.strip().startswith("games=1 plies=")


@pytest.mark.engine
def test_generate_replay_reproduces_movetext_and_harvest(
    tmp_path, monkeypatch, capsys, engine_binary
):
    db_path = tmp_path / "x.db"
    _run_generate(monkeypatch, capsys, db_path, seed=42, games=1, max_ply=24)

    conn = connect(db_path)
    row = get_game(conn, 1)
    original_positions = {(p.epd, p.source_ply) for p in positions_for_game(conn, 1)}
    conn.close()

    config = SamplerConfig.from_json(row.sampler_config_json)
    engine = open_engine(engine_binary)
    try:
        replayed = play_game(engine, config, row.seed)
    finally:
        engine.quit()

    assert replayed.moves_uci == row.moves_uci
    replayed_positions = {(h.epd, h.ply) for h in replayed.harvested}
    assert replayed_positions == original_positions

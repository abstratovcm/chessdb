import re

import chess
import chess.engine
import pytest

import chessdb.cli.import_epd as import_mod
from chessdb.cli.main import main
from chessdb.db import connect
from chessdb.db.api import get_position

_SUMMARY_RE = re.compile(
    r"^read=(\d+) invalid=(\d+) gameover=(\d+) dup=(\d+) kept=(\d+) dropped_mate=(\d+) dropped_cp=(\d+)$"
)

# Three quiet, legal middlegame positions (any legal non-terminal EPDs work).
_EPDS = [
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -",
    "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq -",
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq -",
]
_FOOLS_MATE = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq -"  # checkmated


class _FakeMultiPVEngine:
    _RANK1 = chess.engine.Cp(40)
    _REST = (chess.engine.Cp(20), chess.engine.Cp(0), chess.engine.Cp(-400))

    def analyse(self, board, limit, multipv=1, game=None, info=None):
        moves = sorted(board.legal_moves, key=lambda m: m.uci())[:4]
        scores = (self._RANK1, *self._REST)
        return [
            {"multipv": rank, "score": chess.engine.PovScore(s, board.turn), "pv": [m]}
            for rank, (m, s) in enumerate(zip(moves, scores), start=1)
        ]

    def quit(self):
        pass


class _MateEngine(_FakeMultiPVEngine):
    _RANK1 = chess.engine.Mate(3)


class _LostEngine(_FakeMultiPVEngine):
    _RANK1 = chess.engine.Cp(-900)


def _patch_engine(monkeypatch, tmp_path, engine_cls=_FakeMultiPVEngine):
    fake_binary = tmp_path / "fake-stockfish"
    monkeypatch.setattr(import_mod, "cached_engine_path", lambda v, var: fake_binary)
    monkeypatch.setattr(import_mod, "compute_sha256", lambda b: "d" * 64)
    monkeypatch.setattr(import_mod, "open_engine", lambda b: engine_cls())


def _run_import(monkeypatch, capsys, db_path, epd_file):
    monkeypatch.setattr(
        "sys.argv",
        ["chessdb", "import-epd", "--db", str(db_path), "--epd-file", str(epd_file)],
    )
    main()
    return _SUMMARY_RE.match(capsys.readouterr().out.strip())


def _write_epd_file(tmp_path):
    text = "\n".join(["# comment", "", *_EPDS, "not an epd at all", _FOOLS_MATE]) + "\n"
    path = tmp_path / "in.epd"
    path.write_text(text)
    return path


def test_import_keeps_harvestable_and_counts_junk(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path)
    db_path = tmp_path / "x.db"
    epd_file = _write_epd_file(tmp_path)

    match = _run_import(monkeypatch, capsys, db_path, epd_file)
    assert match is not None
    read, invalid, gameover, dup, kept, dropped_mate, dropped_cp = (
        int(g) for g in match.groups()
    )
    assert (read, invalid, gameover, dup, kept, dropped_mate, dropped_cp) == (
        5,
        1,
        1,
        0,
        3,
        0,
        0,
    )

    conn = connect(db_path)
    for epd in _EPDS:
        row = get_position(conn, epd)
        assert row is not None
        assert row.source_game_id is None
        assert row.source_ply is None
    conn.close()


def test_import_is_idempotent(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path)
    db_path = tmp_path / "x.db"
    epd_file = _write_epd_file(tmp_path)

    _run_import(monkeypatch, capsys, db_path, epd_file)
    match = _run_import(monkeypatch, capsys, db_path, epd_file)
    assert match is not None
    _, _, _, dup, kept, _, _ = (int(g) for g in match.groups())
    assert dup == 3
    assert kept == 0

    conn = connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert count == 3
    conn.close()


def test_import_drops_rank1_mate(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path, engine_cls=_MateEngine)
    db_path = tmp_path / "x.db"
    epd_file = _write_epd_file(tmp_path)

    match = _run_import(monkeypatch, capsys, db_path, epd_file)
    assert match is not None
    _, _, _, _, kept, dropped_mate, dropped_cp = (int(g) for g in match.groups())
    assert kept == 0
    assert dropped_mate == 3
    assert dropped_cp == 0

    conn = connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert count == 0
    conn.close()


def test_import_drops_decided_cp(tmp_path, monkeypatch, capsys):
    _patch_engine(monkeypatch, tmp_path, engine_cls=_LostEngine)
    db_path = tmp_path / "x.db"
    epd_file = _write_epd_file(tmp_path)

    match = _run_import(monkeypatch, capsys, db_path, epd_file)
    assert match is not None
    _, _, _, _, kept, dropped_mate, dropped_cp = (int(g) for g in match.groups())
    assert kept == 0
    assert dropped_cp == 3
    assert dropped_mate == 0


@pytest.mark.engine
def test_import_then_run_ladders_sourceless_positions(
    tmp_path, monkeypatch, capsys, engine_binary
):
    db_path = tmp_path / "x.db"
    epd_file = tmp_path / "in.epd"
    epd_file.write_text("\n".join(_EPDS[:2]) + "\n")

    monkeypatch.setattr(
        "sys.argv",
        ["chessdb", "import-epd", "--db", str(db_path), "--epd-file", str(epd_file)],
    )
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        "sys.argv",
        [
            "chessdb",
            "run",
            "--db",
            str(db_path),
            "--seed",
            "1",
            "--games-target",
            "0",
            "--max-hours",
            "0.2",
            "--workers",
            "1",
            "--top-rung",
            "4000",
        ],
    )
    main()
    out = capsys.readouterr().out

    conn = connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM evals").fetchone()[0]
    conn.close()
    assert count == 4
    assert "status=complete" in out

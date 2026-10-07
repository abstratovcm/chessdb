from chessdb.cli.main import main


def test_init_is_idempotent(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "x.db"
    monkeypatch.setattr("sys.argv", ["chessdb", "init", "--db", str(db_path)])

    main()
    first = capsys.readouterr().out

    main()
    second = capsys.readouterr().out

    assert first == second
    assert "user_version=3" in first
    assert "engines=0" in first
    assert "position_metrics=0" in first

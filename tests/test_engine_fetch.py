import hashlib

import pytest

from chessdb.engine import fetch as fetch_mod
from chessdb.engine.fetch import cached_engine_path, compute_sha256, fetch_engine


def test_fetch_engine_rejects_unknown_pin(tmp_path):
    with pytest.raises(ValueError, match="unknown engine pin"):
        fetch_engine("0.0", "bogus-variant", cache_dir=tmp_path)


def test_pins_table_lists_both_known_engine_versions(tmp_path):
    with pytest.raises(ValueError, match=r"17\.1/x86-64-avx2.*16\.1/x86-64-avx2"):
        fetch_engine("0.0", "bogus-variant", cache_dir=tmp_path)


def test_compute_sha256_round_trip(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"some engine bytes")
    assert compute_sha256(f) == hashlib.sha256(b"some engine bytes").hexdigest()


def test_fetch_engine_rejects_and_deletes_tampered_cache(tmp_path, monkeypatch):
    version, variant = "9.9", "test-variant"
    expected_sha256 = "b" * 64
    monkeypatch.setitem(
        fetch_mod.PINS, (version, variant), ("http://example.invalid", expected_sha256)
    )

    dest = tmp_path / f"stockfish-{version}-{variant}"
    dest.write_bytes(b"tampered content")

    def _no_network(url, dest_path):
        raise RuntimeError("network disabled in test")

    monkeypatch.setattr(fetch_mod, "_download", _no_network)

    with pytest.raises(RuntimeError, match="network disabled"):
        fetch_engine(version, variant, cache_dir=tmp_path)

    assert not dest.exists()


def test_fetch_engine_full_pipeline_offline(tmp_path, monkeypatch):
    import tarfile

    version, variant = "9.9", "test-variant"
    binary_bytes = b"fake stockfish binary"
    expected_sha256 = hashlib.sha256(binary_bytes).hexdigest()
    monkeypatch.setitem(
        fetch_mod.PINS, (version, variant), ("http://example.invalid", expected_sha256)
    )

    def _fake_download(url, dest_path):
        member_path = tmp_path / "stockfish" / f"stockfish-ubuntu-{variant}"
        member_path.parent.mkdir(parents=True, exist_ok=True)
        member_path.write_bytes(binary_bytes)
        with tarfile.open(dest_path, "w") as tar:
            tar.add(member_path, arcname=f"stockfish/stockfish-ubuntu-{variant}")

    monkeypatch.setattr(fetch_mod, "_download", _fake_download)

    binary = fetch_engine(version, variant, cache_dir=tmp_path)
    assert compute_sha256(binary) == expected_sha256
    assert (binary.stat().st_mode & 0o777) == 0o755

    # Second call hits the cache, no download.
    monkeypatch.setattr(
        fetch_mod, "_download", lambda *a: (_ for _ in ()).throw(AssertionError())
    )
    assert fetch_engine(version, variant, cache_dir=tmp_path) == binary


def test_cached_engine_path_unknown_pin_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown engine pin"):
        cached_engine_path("0.0", "bogus-variant", cache_dir=tmp_path)


def test_cached_engine_path_miss_raises_with_fetch_command(tmp_path, monkeypatch):
    version, variant = "9.9", "test-variant"
    monkeypatch.setitem(
        fetch_mod.PINS, (version, variant), ("http://example.invalid", "c" * 64)
    )
    with pytest.raises(FileNotFoundError, match="chessdb fetch-engine"):
        cached_engine_path(version, variant, cache_dir=tmp_path)


def test_cached_engine_path_hit_returns_cached_binary(tmp_path, monkeypatch):
    version, variant = "9.9", "test-variant"
    binary_bytes = b"fake stockfish binary"
    expected_sha256 = hashlib.sha256(binary_bytes).hexdigest()
    monkeypatch.setitem(
        fetch_mod.PINS, (version, variant), ("http://example.invalid", expected_sha256)
    )
    dest = tmp_path / f"stockfish-{version}-{variant}"
    dest.write_bytes(binary_bytes)
    assert cached_engine_path(version, variant, cache_dir=tmp_path) == dest

"""Downloads a pinned Stockfish release, checks its sha256 and caches it."""

from __future__ import annotations

import hashlib
import os
import tarfile
import urllib.request
from pathlib import Path

# (version, variant) -> (asset_url, binary_sha256), pinned after a checked download.
PINS: dict[tuple[str, str], tuple[str, str]] = {
    ("17.1", "x86-64-avx2"): (
        "https://github.com/official-stockfish/Stockfish/releases"
        + "/download/sf_17.1/stockfish-ubuntu-x86-64-avx2.tar",
        "7fecbc0b26454b62be5e3b237b58dc5666401b56e520aeb1b0bf8f53fa8f2ef3",
    ),
    ("16.1", "x86-64-avx2"): (
        "https://github.com/official-stockfish/Stockfish/releases"
        + "/download/sf_16.1/stockfish-ubuntu-x86-64-avx2.tar",
        "01a8cbe27fabf6aad1c6393d2510982805f682c8c61243cad2e84f51e974505a",
    ),
}


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "chessdb" / "engines"


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url)
    with (
        urllib.request.urlopen(request, timeout=60) as response,
        open(dest, "wb") as out,
    ):
        while chunk := response.read(1 << 20):
            out.write(chunk)


def cached_engine_path(
    version: str, variant: str, cache_dir: Path | None = None
) -> Path:
    key = (version, variant)
    if key not in PINS:
        known = ", ".join(f"{v}/{va}" for v, va in PINS)
        raise ValueError(f"unknown engine pin {version}/{variant}; known: {known}")
    _, expected_sha256 = PINS[key]
    cache_dir = cache_dir or _default_cache_dir()
    path = cache_dir / f"stockfish-{version}-{variant}"
    if not path.exists() or compute_sha256(path) != expected_sha256:
        raise FileNotFoundError(
            f"engine {version}/{variant} not cached; run `chessdb fetch-engine "
            f"--version {version} --variant {variant}` first"
        )
    return path


def fetch_engine(version: str, variant: str, cache_dir: Path | None = None) -> Path:
    key = (version, variant)
    if key not in PINS:
        known = ", ".join(f"{v}/{va}" for v, va in PINS)
        raise ValueError(f"unknown engine pin {version}/{variant}; known: {known}")
    asset_url, expected_sha256 = PINS[key]

    cache_dir = cache_dir or _default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"stockfish-{version}-{variant}"

    if dest.exists():
        if compute_sha256(dest) == expected_sha256:
            return dest
        dest.unlink()

    tar_tmp = cache_dir / f".download-{version}-{variant}.tar.tmp"
    bin_tmp = cache_dir / f".download-{version}-{variant}.bin.tmp"
    member_name = f"stockfish/stockfish-ubuntu-{variant}"
    try:
        _download(asset_url, tar_tmp)
        with tarfile.open(tar_tmp) as tar:
            member = tar.getmember(member_name)
            extracted = tar.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"tar member {member_name!r} is not a file")
            with open(bin_tmp, "wb") as out:
                out.write(extracted.read())

        bin_tmp.chmod(0o755)
        actual_sha256 = compute_sha256(bin_tmp)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"sha256 mismatch for {version}/{variant}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        bin_tmp.replace(dest)
    finally:
        tar_tmp.unlink(missing_ok=True)
        bin_tmp.unlink(missing_ok=True)

    return dest

"""Amostra determinística de posições humanas do dump aberto do Lichess (licença CC0)
para o conjunto de validação do artigo. Reproduzível a partir de: URL, --games, --min-ply,
--max-ply, --sample e --seed. Não grava o PGN em disco.

Uso:
    python paper/scripts/lichess_sample.py --out paper/dados/lichess
"""

import argparse
import datetime
import io
import json
import random
import urllib.request
from pathlib import Path

import chess
import chess.pgn
import zstandard

URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--games", type=int, default=10_000)
    ap.add_argument("--min-ply", type=int, default=8)
    ap.add_argument("--max-ply", type=int, default=80)
    ap.add_argument("--sample", type=int, default=6_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    games_read = parse_errors = harvested = 0
    epds: set[str] = set()
    with urllib.request.urlopen(a.url) as resp:
        reader = zstandard.ZstdDecompressor().stream_reader(resp)
        text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        while games_read < a.games:
            game = chess.pgn.read_game(text)
            if game is None:
                break
            games_read += 1
            if game.errors:
                parse_errors += 1
            board = game.board()
            for ply, move in enumerate(game.mainline_moves(), start=1):
                board.push(move)
                if a.min_ply <= ply < a.max_ply and not board.is_game_over(
                    claim_draw=True
                ):
                    epds.add(board.epd())
                    harvested += 1
    unique = sorted(epds)
    sample = random.Random(a.seed).sample(unique, min(a.sample, len(unique)))
    (a.out / "candidatos.epd").write_text("\n".join(sample) + "\n")
    meta = {
        "url": a.url,
        "games_read": games_read,
        "parse_errors": parse_errors,
        "harvested": harvested,
        "unique": len(unique),
        "sample": len(sample),
        "seed": a.seed,
        "min_ply": a.min_ply,
        "max_ply": a.max_ply,
        "extracted_at": datetime.datetime.now(datetime.UTC).date().isoformat(),
    }
    (a.out / "metadados.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(meta)


if __name__ == "__main__":
    main()

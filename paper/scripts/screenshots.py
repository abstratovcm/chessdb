"""Captura telas do site chessdb (servido localmente) para as figuras do artigo.

Uso:
    python paper/scripts/screenshots.py --base http://127.0.0.1:8765 --out paper/figuras [--position 261]

Requer o site rodando: `chessdb serve --db <banco> --web-dist web/dist --port 8765`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGINAS = {
    "tela_dashboard": ("#/", 1400, 1500),
    "tela_explorer": ("#/position/{pid}", 1400, 1900),
    "tela_browse": ("#/browse?min_sign_flips=2&metric_version=2", 1400, 1100),
    "tela_compare": ("#/compare", 1400, 1500),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--position", type=int, default=261)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for nome, (rota, w, h) in PAGINAS.items():
            page = browser.new_page(
                viewport={"width": w, "height": h}, device_scale_factor=2
            )
            page.goto(f"{args.base}/{rota.format(pid=args.position)}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            dest = args.out / f"{nome}.png"
            page.screenshot(path=str(dest), full_page=True)
            print(dest)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()

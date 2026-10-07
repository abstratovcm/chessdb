"""Compara as métricas de instabilidade entre as posições geradas (autojogo) e a
validação com posições humanas do Lichess, uma linha por (origem, motor).

Uso:
    python paper/scripts/tabela_fontes.py --dados paper/dados
"""

import argparse
from pathlib import Path

import pandas as pd

COLUNAS = [
    "fonte",
    "motor",
    "n",
    "pct_sign_flips_ge1",
    "pct_sign_flips_ge2",
    "cp_range_mediana",
    "settle_dev_mediana",
    "pct_settle_dev_gt100",
    "pct_posicoes_com_mate",
    "diverg_mediana",
    "pct_diverg_gt50",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True, type=Path)
    dados = ap.parse_args().dados
    fontes = {
        "Geradas (autojogo)": dados,
        "Lichess 2013-01": dados / "lichess",
    }
    rows = []
    for fonte, pasta in fontes.items():
        resumo = pd.read_csv(pasta / "resumo_metricas.csv")
        escala = pd.read_csv(pasta / "tabela_escala.csv")
        posicoes = dict(zip(escala.motor, escala.posicoes))
        for _, r in resumo.iterrows():
            n = int(posicoes[r.motor])
            rows.append(
                {
                    "fonte": fonte,
                    "motor": r.motor,
                    "n": n,
                    "pct_sign_flips_ge1": r.pct_sign_flips_ge1,
                    "pct_sign_flips_ge2": r.pct_sign_flips_ge2,
                    "cp_range_mediana": r.cp_range_mediana,
                    "settle_dev_mediana": r.settle_dev_mediana,
                    "pct_settle_dev_gt100": r.pct_settle_dev_gt100,
                    "pct_posicoes_com_mate": round(100 * r.posicoes_com_mate / n, 2),
                    "diverg_mediana": r.diverg_mediana,
                    "pct_diverg_gt50": r.pct_diverg_gt50,
                }
            )
    df = pd.DataFrame(rows, columns=COLUNAS)
    df.to_csv(dados / "tabela_fontes.csv", index=False)
    print(df.to_string(index=False))

    for fonte, pasta in fontes.items():
        prof = pd.read_csv(pasta / "tabela_profundidade_por_degrau.csv")
        topo = prof[prof.degrau == 1_000_000]
        for _, r in topo.iterrows():
            print(
                f"{fonte} / {r.motor}: profundidade média no maior degrau = {r.prof_media:.2f}"
            )


if __name__ == "__main__":
    main()

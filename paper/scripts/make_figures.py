"""Gera as figuras 3 a 5 do artigo a partir dos CSVs de paper/dados.

Uso:
    python paper/scripts/make_figures.py --dados paper/dados --out paper/figuras

Estilo conforme o manual do MBA USP/Esalq (Tabela 8): sem linhas de grade,
sem borda, sem preenchimento de fundo, sem título no gráfico, eixos com
linha sólida preta, fonte Arial (Liberation Sans como substituta métrica).
Painéis múltiplos identificados por letras maiúsculas no canto superior
esquerdo, sem pontuação.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")

RUNGS = [1000, 4000, 16000, 64000, 256000, 1000000, 4000000]
RUNG_LABELS = ["1 k", "4 k", "16 k", "64 k", "256 k", "1 M", "4 M"]
CORES = ["#1f4e79", "#c55a11", "#548235", "#7030a0"]

plt.rcParams.update(
    {
        "font.family": ["Arial", "Liberation Sans", "DejaVu Sans"],
        "font.size": 10,
        "axes.grid": False,
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "axes.edgecolor": "black",
        "axes.linewidth": 1.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": "black",
        "ytick.color": "black",
        "legend.frameon": False,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
    }
)


def rotular(ax, letra: str) -> None:
    ax.text(
        -0.12,
        1.04,
        letra,
        transform=ax.transAxes,
        fontsize=12,
        fontweight="bold",
        va="bottom",
        ha="left",
    )


def fig_profundidade(dados: Path, out: Path) -> None:
    df = pd.read_csv(dados / "tabela_profundidade_por_degrau.csv")
    motores = list(df.motor.unique())
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    x = np.arange(len(RUNGS))
    for i, m in enumerate(motores):
        g = df[df.motor == m]
        g = (
            g[g.n == g.n.max()].set_index("degrau").reindex(RUNGS)
        )  # ignora degraus parciais
        axes[0].plot(x, g.prof_media, marker="o", color=CORES[i], label=m)
        axes[0].plot(
            x, g.seldepth_media, marker="o", linestyle="--", color=CORES[i], alpha=0.6
        )
        axes[1].plot(x, g.mates, marker="s", color=CORES[i], label=m)
    axes[0].set_ylabel("Profundidade média (plies)")
    axes[0].set_xlabel("Limite de nós")
    axes[1].set_ylabel("Avaliações com mate encontrado")
    axes[1].set_xlabel("Limite de nós")
    for ax, letra in zip(axes, "AB"):
        ax.set_xticks(x, RUNG_LABELS)
        rotular(ax, letra)
    axes[0].legend(loc="upper left", fontsize=8)
    axes[0].text(
        0.98,
        0.03,
        "linha cheia: depth\nlinha tracejada: seldepth",
        transform=axes[0].transAxes,
        fontsize=7,
        ha="right",
        va="bottom",
    )
    fig.tight_layout()
    fig.savefig(out / "fig_profundidade_por_degrau.png")
    plt.close(fig)


def fig_histogramas(dados: Path, out: Path) -> None:
    m = pd.read_csv(dados / "metricas_v2.csv")
    motores = list(m.motor.unique())
    tem_div = m.version_disagreement.notna().any()
    ncols = 4 if tem_div else 3
    fig, axes = plt.subplots(1, ncols, figsize=(1.9 * ncols + 0.6, 2.9))
    w = 0.8 / len(motores)
    # A: sign_flips (barras por valor)
    vals = sorted(m.sign_flips.unique())
    for i, mo in enumerate(motores):
        g = m[m.motor == mo]
        pct = [100 * (g.sign_flips == v).mean() for v in vals]
        axes[0].bar(
            np.arange(len(vals)) + i * w - 0.4 + w / 2,
            pct,
            width=w,
            color=CORES[i],
            label=mo,
        )
    axes[0].set_xticks(np.arange(len(vals)), [str(v) for v in vals])
    axes[0].set_xlabel("Inversões de sinal")
    axes[0].set_ylabel("Posições (%)")
    axes[0].set_yscale("log")
    axes[0].legend(fontsize=7, loc="upper right")
    # B: cp_range, C: settle_dev
    bins = np.arange(0, 2001, 50)
    for k, (col, xl) in enumerate(
        [
            ("cp_range", "Amplitude da avaliação (cp)"),
            ("settle_dev", "Desvio de assentamento (cp)"),
        ],
        start=1,
    ):
        for i, mo in enumerate(motores):
            g = m[m.motor == mo]
            axes[k].hist(
                g[col].clip(upper=2000),
                bins=bins,
                histtype="step",
                color=CORES[i],
                label=mo,
                linewidth=1.2,
            )
        axes[k].set_xlabel(xl)
        axes[k].set_ylabel("Posições")
        axes[k].set_yscale("log")
    if tem_div:
        d = m[m.engine_id == m.engine_id.min()].version_disagreement.dropna()
        axes[3].hist(
            d.clip(upper=2000), bins=bins, histtype="step", color="black", linewidth=1.2
        )
        axes[3].set_xlabel("Divergência entre versões (cp)")
        axes[3].set_ylabel("Posições")
        axes[3].set_yscale("log")
    for ax, letra in zip(axes, "ABCD"):
        rotular(ax, letra)
    fig.tight_layout()
    fig.savefig(out / "fig_histogramas_metricas.png")
    plt.close(fig)


def fig_trajetorias(dados: Path, out: Path) -> None:
    t = pd.read_csv(dados / "trajetorias_exemplos.csv")
    ex = pd.read_csv(dados / "exemplos_ids.csv").iloc[0]
    ordem = [
        ("estavel", "Posição estável"),
        ("instavel", "Posição instável"),
        ("mate", "Mate encontrado em profundidade"),
    ]
    motores = list(t.motor.unique())
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.8), sharey=True)
    x = np.arange(len(RUNGS))
    for ax, (chave, rotulo), letra in zip(axes, ordem, "ABC"):
        pid = int(ex[chave])
        for i, mo in enumerate(motores):
            g = (
                t[(t.position_id == pid) & (t.motor == mo)]
                .set_index("degrau")
                .reindex(RUNGS)
            )
            ax.plot(x, g.cp_clamp, marker="o", color=CORES[i], label=mo)
            mates = g[g.score_kind == 1]
            if len(mates):
                ax.plot(
                    [RUNGS.index(r) for r in mates.index],
                    mates.cp_clamp,
                    marker="o",
                    markersize=9,
                    linestyle="none",
                    color=CORES[i],
                )
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_xticks(x, RUNG_LABELS, fontsize=8)
        ax.set_xlabel("Limite de nós")
        ax.set_xlabel(f"Limite de nós\n{rotulo} (id {pid})", fontsize=8)
        rotular(ax, letra)
    axes[0].set_ylabel("Avaliação (cp, brancas, ±1000)")
    axes[0].legend(fontsize=7, loc="center left")
    fig.tight_layout()
    fig.savefig(out / "fig_trajetorias_exemplos.png")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fig_profundidade(args.dados, args.out)
    fig_histogramas(args.dados, args.out)
    fig_trajetorias(args.dados, args.out)
    for f in sorted(args.out.glob("fig_*.png")):
        print(f)


if __name__ == "__main__":
    main()

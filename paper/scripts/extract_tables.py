"""Extrai, de um banco chessdb (SQLite), as tabelas e séries usadas no artigo.

Uso:
    python paper/scripts/extract_tables.py --db chessdb-tcc.sqlite --out paper/dados
    python paper/scripts/extract_tables.py --db chessdb-tcc.sqlite --out paper/dados/ancora4m --top-rung 4000000
    python paper/scripts/extract_tables.py --db chessdb-lichess-tcc.sqlite --out paper/dados/lichess

Só lê o banco (URI mode=ro). Gera CSVs em --out; cada CSV é a fonte de uma
tabela ou figura do artigo, para que qualquer gráfico possa ser refeito.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import pandas as pd

NODE_LADDER = [1000, 4000, 16000, 64000, 256000, 1000000, 4000000]
RUNGS = list(NODE_LADDER)  # limitado por --top-rung em main()
CLAMP = 1000


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def engines(conn) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT id, name, version, binary_sha256, threads, hash_mb FROM engines ORDER BY id",
        conn,
    )
    df["motor"] = df["name"].str.capitalize() + " " + df["version"]
    return df


def tabela_escala(conn, db_path: Path, eng: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n_games = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    n_pos = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    for _, e in eng.iterrows():
        n_ev = conn.execute(
            "SELECT COUNT(*) FROM evals WHERE engine_id=?", (e.id,)
        ).fetchone()[0]
        n_full = conn.execute(
            "SELECT COUNT(*) FROM (SELECT position_id FROM evals WHERE engine_id=? AND limit_value<=? "
            "GROUP BY position_id HAVING COUNT(*)=?)",
            (e.id, RUNGS[-1], len(RUNGS)),
        ).fetchone()[0]
        n_met = conn.execute(
            "SELECT COUNT(*) FROM position_metrics WHERE engine_id=?", (e.id,)
        ).fetchone()[0]
        nodes = conn.execute(
            "SELECT SUM(nodes) FROM evals WHERE engine_id=?", (e.id,)
        ).fetchone()[0]
        secs = conn.execute(
            "SELECT SUM(time_ms)/1000.0 FROM evals WHERE engine_id=?", (e.id,)
        ).fetchone()[0]
        rows.append(
            {
                "motor": e.motor,
                "sha256_8": e.binary_sha256[:8],
                "threads": e.threads,
                "hash_mb": e.hash_mb,
                "partidas": n_games,
                "posicoes": n_pos,
                "avaliacoes": n_ev,
                "posicoes_escada_completa": n_full,
                "linhas_metricas": n_met,
                "nos_total": nodes,
                "cpu_horas_motor": round(secs / 3600, 1),
            }
        )
    df = pd.DataFrame(rows)
    df["tamanho_arquivo_mb"] = round(
        os.path.getsize(db_path) / 1e6, 1
    )  # MB (SI), conforme o manual de formatação
    return df


def tabela_profundidade(conn, eng: pd.DataFrame) -> pd.DataFrame:
    q = """
    SELECT engine_id, limit_value AS degrau, COUNT(*) AS n,
           AVG(depth) AS prof_media, MIN(depth) AS prof_min, MAX(depth) AS prof_max,
           AVG(seldepth) AS seldepth_media,
           SUM(CASE WHEN score_kind=1 THEN 1 ELSE 0 END) AS mates,
           AVG(time_ms)/1000.0 AS seg_media, AVG(nodes) AS nos_medios
    FROM evals WHERE limit_kind=0 GROUP BY engine_id, limit_value ORDER BY engine_id, limit_value
    """
    df = pd.read_sql(q, conn)
    df = df.merge(eng[["id", "motor"]], left_on="engine_id", right_on="id").drop(
        columns=["id"]
    )
    df["nps_medio"] = (df["nos_medios"] / df["seg_media"]).round(0)
    for c in ("prof_media", "seldepth_media"):
        df[c] = df[c].round(1)
    df["seg_media"] = df["seg_media"].round(2)
    return df[
        [
            "motor",
            "degrau",
            "n",
            "prof_media",
            "prof_min",
            "prof_max",
            "seldepth_media",
            "mates",
            "seg_media",
            "nps_medio",
        ]
    ]


def metricas_v2(conn, eng: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT position_id, engine_id, top_rung, sign_flips, cp_range, settle_dev, version_disagreement, mate_found_rung "
        "FROM position_metrics WHERE metric_version=2",
        conn,
    )
    return df.merge(eng[["id", "motor"]], left_on="engine_id", right_on="id").drop(
        columns=["id"]
    )


def resumo_metricas(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for motor, g in m.groupby("motor"):
        n = len(g)
        row = {
            "motor": motor,
            "n": n,
            "sign_flips_media": round(g.sign_flips.mean(), 3),
            "pct_sign_flips_ge1": round(100 * (g.sign_flips >= 1).mean(), 2),
            "pct_sign_flips_ge2": round(100 * (g.sign_flips >= 2).mean(), 2),
            "cp_range_mediana": g.cp_range.median(),
            "cp_range_p90": g.cp_range.quantile(0.9),
            "cp_range_media": round(g.cp_range.mean(), 1),
            "settle_dev_mediana": g.settle_dev.median(),
            "settle_dev_p90": g.settle_dev.quantile(0.9),
            "settle_dev_media": round(g.settle_dev.mean(), 1),
            "pct_settle_dev_gt100": round(100 * (g.settle_dev > 100).mean(), 2),
            "posicoes_com_mate": int(g.mate_found_rung.notna().sum()),
        }
        if g.version_disagreement.notna().any():
            d = g.version_disagreement.dropna()
            row.update(
                {
                    "diverg_mediana": d.median(),
                    "diverg_p90": d.quantile(0.9),
                    "diverg_media": round(d.mean(), 1),
                    "pct_diverg_gt50": round(100 * (d > 50).mean(), 2),
                    "pct_diverg_gt200": round(100 * (d > 200).mean(), 2),
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def trajetorias(conn, eng: pd.DataFrame, position_ids: list[int]) -> pd.DataFrame:
    ids = ",".join(str(i) for i in position_ids)
    df = pd.read_sql(
        f"SELECT e.position_id, p.epd, e.engine_id, e.limit_value AS degrau, e.score_kind, e.score, e.depth, e.bestmove "
        f"FROM evals e JOIN positions p ON p.id=e.position_id WHERE e.limit_kind=0 AND e.position_id IN ({ids}) "
        f"ORDER BY e.position_id, e.engine_id, e.limit_value",
        conn,
    )
    df = df.merge(eng[["id", "motor"]], left_on="engine_id", right_on="id").drop(
        columns=["id"]
    )
    df["cp_clamp"] = df.apply(
        lambda r: (
            max(-CLAMP, min(CLAMP, r.score))
            if r.score_kind == 0
            else (CLAMP if r.score > 0 else -CLAMP)
        ),
        axis=1,
    )
    return df


def escolher_exemplos(m: pd.DataFrame, conn) -> dict[str, int]:
    """Três posições ilustrativas com base no primeiro motor (engine_id mínimo)."""
    base = m[m.engine_id == m.engine_id.min()]
    estavel = (
        base[(base.cp_range <= 15) & (base.settle_dev <= 10)]
        .sort_values("position_id")
        .iloc[0]
        .position_id
    )
    candidatos = base[(base.sign_flips >= 3) & (base.mate_found_rung.isna())]
    instavel = candidatos.sort_values("cp_range", ascending=False).iloc[0].position_id
    com_mate = base[base.mate_found_rung == 256000].sort_values("position_id")
    mate_id = (
        int(com_mate.iloc[0].position_id)
        if len(com_mate)
        else int(base[base.mate_found_rung.notna()].iloc[0].position_id)
    )
    return {"estavel": int(estavel), "instavel": int(instavel), "mate": mate_id}


def tabela_divergencia(
    conn, m: pd.DataFrame, eng: pd.DataFrame, n: int = 15
) -> pd.DataFrame | None:
    if m.version_disagreement.isna().all():
        return None
    top = (
        m[m.engine_id == m.engine_id.min()]
        .dropna(subset=["version_disagreement"])
        .sort_values("version_disagreement", ascending=False)
        .head(n)
    )
    ids = ",".join(str(int(i)) for i in top.position_id)
    ev = pd.read_sql(
        f"SELECT e.position_id, p.epd, e.engine_id, e.limit_value, e.score_kind, e.score, e.bestmove "
        f"FROM evals e JOIN positions p ON p.id=e.position_id WHERE e.limit_kind=0 AND e.position_id IN ({ids})",
        conn,
    )
    ev = ev.merge(eng[["id", "motor"]], left_on="engine_id", right_on="id").drop(
        columns=["id"]
    )
    rows = []
    for pid, g in ev.groupby("position_id"):
        common = int(min(min(g.groupby("engine_id").limit_value.max()), RUNGS[-1]))
        gc = g[g.limit_value == common]
        row = {
            "position_id": pid,
            "epd": gc.epd.iloc[0],
            "degrau_comum": common,
            "divergencia_cp": int(
                top[top.position_id == pid].version_disagreement.iloc[0]
            ),
        }
        for _, r in gc.iterrows():
            tag = r.motor.replace(" ", "_")
            row[f"cp_{tag}"] = int(r.score) if r.score_kind == 0 else f"M{int(r.score)}"
            row[f"lance_{tag}"] = r.bestmove
        rows.append(row)
    return pd.DataFrame(rows).sort_values("divergencia_cp", ascending=False)


def passo_entre_degraus(
    conn, eng: pd.DataFrame, pares=((256000, 1000000), (1000000, 4000000))
) -> pd.DataFrame:
    """Quanto o rótulo muda entre dois degraus consecutivos: |Δcp| (com clamp e mates em ±CLAMP),
    troca de melhor lance, inversão de sinal e mates novos. Só posições com os dois degraus."""
    degraus = sorted({d for par in pares for d in par})
    q = (
        "SELECT position_id, engine_id, limit_value AS degrau, score_kind, score, bestmove FROM evals "
        f"WHERE limit_value IN ({','.join('?' * len(degraus))})"
    )
    ev = pd.read_sql(q, conn, params=degraus)
    ev["cp"] = ev.apply(
        lambda r: (
            (CLAMP if r.score > 0 else -CLAMP)
            if r.score_kind == 1
            else max(-CLAMP, min(CLAMP, r.score))
        ),
        axis=1,
    )
    rows = []
    for _, e in eng.iterrows():
        g = ev[ev.engine_id == e.id]
        for a, b in pares:
            x = g[g.degrau == a].set_index("position_id")
            y = g[g.degrau == b].set_index("position_id")
            idx = x.index.intersection(y.index)
            if len(idx) == 0:
                continue
            x, y = x.loc[idx], y.loc[idx]
            d = (y.cp - x.cp).abs()
            rows.append(
                {
                    "motor": e.motor,
                    "de": a,
                    "para": b,
                    "n": len(idx),
                    "pct_abs_delta_gt20": round(100 * (d > 20).mean(), 2),
                    "pct_abs_delta_gt50": round(100 * (d > 50).mean(), 2),
                    "pct_abs_delta_gt100": round(100 * (d > 100).mean(), 2),
                    "abs_delta_mediana": d.median(),
                    "abs_delta_p90": d.quantile(0.9),
                    "pct_melhor_lance_mudou": round(
                        100 * (x.bestmove != y.bestmove).mean(), 2
                    ),
                    "pct_inversao_sinal": round(100 * ((x.cp * y.cp) < 0).mean(), 2),
                    "mates_novos": int(
                        ((y.score_kind == 1) & (x.score_kind != 1)).sum()
                    ),
                }
            )
    return pd.DataFrame(rows)


def estatisticas_texto(conn, m: pd.DataFrame, eng: pd.DataFrame) -> pd.DataFrame:
    """Estatísticas citadas no corpo do artigo sem tabela própria (rastreabilidade):
    seletiva < nominal a 1.000 nós; concordância de melhor lance a 1 M entre os dois
    motores; divergência por faixa de |cp|; quantis da divergência."""
    rows = []
    for _, e in eng.iterrows():
        pct = conn.execute(
            "SELECT 100.0*AVG(CASE WHEN seldepth<depth THEN 1 ELSE 0 END) FROM evals "
            "WHERE engine_id=? AND limit_value=1000",
            (e.id,),
        ).fetchone()[0]
        rows.append(
            {
                "chave": "pct_seldepth_menor_que_depth_1000",
                "motor": e.motor,
                "valor": round(pct, 1),
            }
        )
    if len(eng) < 2:
        return pd.DataFrame(rows)
    top = RUNGS[-1]
    ev = pd.read_sql(
        "SELECT position_id, engine_id, score_kind, score, bestmove FROM evals WHERE limit_value=?",
        conn,
        params=(top,),
    )
    ev["cp"] = ev.apply(
        lambda r: (
            (CLAMP if r.score > 0 else -CLAMP)
            if r.score_kind == 1
            else max(-CLAMP, min(CLAMP, r.score))
        ),
        axis=1,
    )
    e1, e2 = int(eng.id.iloc[0]), int(eng.id.iloc[1])
    a = ev[ev.engine_id == e1].set_index("position_id")
    b = ev[ev.engine_id == e2].set_index("position_id")
    idx = a.index.intersection(b.index)
    a, b = a.loc[idx], b.loc[idx]
    d = (
        m[(m.engine_id == e1)]
        .set_index("position_id")
        .version_disagreement.reindex(idx)
    )
    sd = m[(m.engine_id == e1)].set_index("position_id").settle_dev.reindex(idx)
    same = a.bestmove == b.bestmove
    abs1 = a.cp.abs()
    par = "ambos"
    rows += [
        {"chave": "n_posicoes_degrau_comum", "motor": par, "valor": len(idx)},
        {
            "chave": "pct_mesmo_melhor_lance",
            "motor": par,
            "valor": round(100 * same.mean(), 1),
        },
        {
            "chave": "pct_mesmo_melhor_lance_diverg_le15",
            "motor": par,
            "valor": round(100 * same[d <= 15].mean(), 1),
        },
        {
            "chave": "pct_mesmo_melhor_lance_diverg_gt100",
            "motor": par,
            "valor": round(100 * same[d > 100].mean(), 1),
        },
        {
            "chave": "pct_sinal_oposto",
            "motor": par,
            "valor": round(100 * ((a.cp * b.cp) < 0).mean(), 1),
        },
        {
            "chave": "pct_valor_identico",
            "motor": par,
            "valor": round(100 * (d == 0).mean(), 1),
        },
        {"chave": "diverg_q75", "motor": par, "valor": d.quantile(0.75)},
        {"chave": "diverg_q90", "motor": par, "valor": d.quantile(0.90)},
        {"chave": "diverg_q99", "motor": par, "valor": d.quantile(0.99)},
        {
            "chave": "pct_diverg_gt100",
            "motor": par,
            "valor": round(100 * (d > 100).mean(), 1),
        },
        {
            "chave": "pct_diverg_gt200",
            "motor": par,
            "valor": round(100 * (d > 200).mean(), 1),
        },
        {
            "chave": "diverg_mediana_abscp_le50",
            "motor": eng.motor.iloc[0],
            "valor": d[abs1 <= 50].median(),
        },
        {
            "chave": "diverg_mediana_abscp_gt600",
            "motor": eng.motor.iloc[0],
            "valor": d[abs1 > 600].median(),
        },
        {
            "chave": "n_abscp_le50",
            "motor": eng.motor.iloc[0],
            "valor": int((abs1 <= 50).sum()),
        },
        {
            "chave": "settle_dev_mediana_abscp_le50",
            "motor": eng.motor.iloc[0],
            "valor": sd[abs1 <= 50].median(),
        },
    ]
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--top-rung",
        type=int,
        default=1_000_000,
        help="degrau máximo considerado (mesmo valor passado a chessdb metrics)",
    )
    args = ap.parse_args()
    RUNGS[:] = [r for r in NODE_LADDER if r <= args.top_rung]
    args.out.mkdir(parents=True, exist_ok=True)
    conn = connect_ro(args.db)
    eng = engines(conn)
    eng.to_csv(args.out / "motores.csv", index=False)

    tabela_escala(conn, args.db, eng).to_csv(
        args.out / "tabela_escala.csv", index=False
    )
    tabela_profundidade(conn, eng).to_csv(
        args.out / "tabela_profundidade_por_degrau.csv", index=False
    )

    m = metricas_v2(conn, eng)
    m.to_csv(args.out / "metricas_v2.csv", index=False)
    resumo_metricas(m).to_csv(args.out / "resumo_metricas.csv", index=False)
    passo_entre_degraus(conn, eng).to_csv(
        args.out / "passo_entre_degraus.csv", index=False
    )
    estatisticas_texto(conn, m, eng).to_csv(
        args.out / "estatisticas_texto.csv", index=False
    )

    ex = escolher_exemplos(m, conn)
    pd.DataFrame([ex]).to_csv(args.out / "exemplos_ids.csv", index=False)
    trajetorias(conn, eng, list(ex.values())).to_csv(
        args.out / "trajetorias_exemplos.csv", index=False
    )

    div = tabela_divergencia(conn, m, eng)
    if div is not None:
        div.to_csv(args.out / "tabela_divergencia_top.csv", index=False)
    else:
        print("aviso: um só motor no banco; tabela_divergencia_top.csv não gerada")

    for f in sorted(args.out.glob("*.csv")):
        print(f.name, len(f.read_text().splitlines()) - 1, "linhas")


if __name__ == "__main__":
    main()

# Artigo

Material do artigo *Avaliação padronizada de posições de xadrez por múltiplas
versões de motor e orçamentos de busca*, trabalho de conclusão do MBA em
Engenharia de Software da USP/Esalq. O texto do artigo será incluído aqui após
a versão final.

- `dados/`: CSVs de onde saem as tabelas e figuras
  - `dados/`: posições geradas, escada até 1 milhão de nós
  - `dados/ancora4m/`: mesmas posições, escada até 4 milhões de nós
  - `dados/lichess/`: conjunto de validação com posições humanas
- `figuras/`: figuras do artigo
- `scripts/`: scripts que geram os CSVs, as figuras e o `.docx`

## Dados

Os bancos estão no release
[`dataset-v1.0`](https://github.com/abstratovcm/chessdb/releases/tag/dataset-v1.0):

| Arquivo | Conteúdo |
|---|---|
| `chessdb-tcc.sqlite` | 2.000 partidas geradas, 131.493 posições, Stockfish 17.1 e 16.1 |
| `chessdb-tcc.parquet` | exportação do banco acima |
| `chessdb-lichess-tcc.sqlite` | 5.683 posições da Lichess (janeiro de 2013), Stockfish 17.1 e 16.1 |
| `chessdb-lichess-tcc.parquet` | exportação do banco acima |
| `candidatos.epd` | as 6.000 posições sorteadas antes da triagem |
| `SHA256SUMS` | somas de verificação |

Os dados do release e de `dados/` estão sob
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). As posições da
Lichess vêm do dump aberto `lichess_db_standard_rated_2013-01` (CC0).

## Reprodução das tabelas e figuras

Na raiz do repositório, com os bancos do release baixados:

```
uv sync --extra paper
uv run python paper/scripts/extract_tables.py --db chessdb-tcc.sqlite --out paper/dados
uv run python paper/scripts/extract_tables.py --db chessdb-tcc.sqlite --out paper/dados/ancora4m --top-rung 4000000
uv run python paper/scripts/extract_tables.py --db chessdb-lichess-tcc.sqlite --out paper/dados/lichess
uv run python paper/scripts/tabela_fontes.py --dados paper/dados
uv run python paper/scripts/make_figures.py --dados paper/dados --out paper/figuras
```

Leva poucos minutos e reproduz os CSVs e as figuras 3 a 5 byte a byte.
As figuras usam Arial ou, na falta dela, Liberation Sans; com outra fonte
elas mudam só na aparência.
`extract_tables.py` também grava `metricas_v2.csv` (cerca de 11 MB), que
`make_figures.py` usa e que fica fora do repositório. As figuras 1 e 2 foram
desenhadas à mão (`.svg`), e as figuras 6 e 7 são capturas do site feitas com
`scripts/screenshots.py` (`uv sync --extra screenshots`).

`scripts/build_docx.py` monta o `.docx` a partir do texto do artigo, mas
depende do template oficial do curso, que não acompanha o repositório.

## Como os bancos foram produzidos

Avaliar com limite de nós e um thread por motor é determinístico: refazer os
passos abaixo produz as mesmas posições e avaliações, exceto o tempo de cada
análise. O custo, porém, é alto: centenas de horas de CPU, executadas em
sessões de 8 horas no Google Colab (`colab/run.ipynb`).

**Posições geradas, Stockfish 17.1.** Duas sessões em paralelo, uma por shard,
repetidas até `status=complete`:

```
chessdb run --db chessdb-sK.sqlite --version 17.1 --seed 1 --games-target 2000 \
  --top-rung 4000000 --max-hours 8 --checkpoint-minutes 5 \
  --drive-dir <pasta> --shards 2 --shard-index K      # K = 0 e 1
chessdb merge --db chessdb-tcc.sqlite --from <checkpoint s0of2> --from <checkpoint s1of2>
```

**Mesmas posições, Stockfish 16.1.** Partindo do banco anterior, com os mesmos
shards e `--games-target 2000`, que não gera partidas novas. A primeira sessão
usou `--top-rung 4000000` e as seguintes `--top-rung 1000000`, por custo; por
isso só 5.809 posições têm o degrau de 4 milhões no 16.1. Depois:

```
chessdb merge --db chessdb-tcc.sqlite --from <checkpoint s0of2> --from <checkpoint s1of2>
chessdb metrics --db chessdb-tcc.sqlite --top-rung 1000000
chessdb export --db chessdb-tcc.sqlite --out chessdb-tcc.parquet \
  --metric-version 2 --columns core,metrics,cp,raw,bestmove,actuals
```

**Validação com posições da Lichess**, executada localmente:

```
python paper/scripts/lichess_sample.py --out paper/dados/lichess
chessdb import-epd --db chessdb-lichess-tcc.sqlite --epd-file paper/dados/lichess/candidatos.epd --version 17.1
chessdb run --db chessdb-lichess-tcc.sqlite --version 17.1 --seed 1 --games-target 0 --top-rung 1000000 --max-hours 4
chessdb run --db chessdb-lichess-tcc.sqlite --version 16.1 --seed 1 --games-target 0 --top-rung 1000000 --max-hours 4
chessdb metrics --db chessdb-lichess-tcc.sqlite --top-rung 1000000
chessdb export --db chessdb-lichess-tcc.sqlite --out chessdb-lichess-tcc.parquet \
  --metric-version 2 --columns core,metrics,cp,raw,bestmove,actuals
```

`lichess_sample.py` lê as 10.000 primeiras partidas do dump, guarda as
posições do 8º ao 79º "ply", remove duplicatas e sorteia 6.000 com semente 1
(parâmetros em `dados/lichess/metadados.json`). `import-epd` aplica a mesma
triagem das posições geradas e manteve 5.683.

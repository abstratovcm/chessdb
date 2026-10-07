"""Monta o .docx do artigo a partir de paper/tcc_artigo.md usando o template do curso,
que não acompanha o repositório.

Uso:
    python paper/scripts/build_docx.py --md paper/tcc_artigo.md \
        --template <template.docx> --figuras paper/figuras --out paper/tcc.docx

Mantém do template tudo (estilos, cabeçalho, rodapé com paginação, margens) e
substitui só o corpo de word/document.xml. Formatação direta igual à do
template: Arial 11, justificado, 1,5 no texto, simples em resumo/tabelas/
legendas, recuo de 1,25 cm na primeira linha, títulos em negrito à esquerda.
"""

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

LARGURA_TEXTO_EMU = 9070 * 635  # 11906 - 2*1418 twips = 9070 twips; 1 twip = 635 EMU
ALTURA_MAX_EMU = int(20.0 / 2.54 * 914400)


# runs e parágrafos
def runs(texto: str, base_rpr: str = "") -> str:
    """Converte **negrito**, *itálico* e `código` em runs."""
    out = []
    texto = texto.replace("\\*", "*")
    padrao = re.compile(r"(\*\*.+?\*\*|\*[^*]+?\*|`[^`]+`)")
    for parte in padrao.split(texto):
        if not parte:
            continue
        rpr = base_rpr
        if parte.startswith("**"):
            parte, rpr = parte[2:-2], base_rpr + "<w:b/><w:bCs/>"
        elif parte.startswith("*"):
            parte, rpr = parte[1:-1], base_rpr + "<w:i/><w:iCs/>"
        elif parte.startswith("`"):
            parte, rpr = (
                parte[1:-1],
                base_rpr
                + '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/><w:sz w:val="20"/>',
            )
        # sobrescritos unicode ¹ ² viram vertAlign para ficarem iguais ao template
        for tok in re.split(r"([¹²])", parte):
            if not tok:
                continue
            r = rpr
            t = tok
            if tok in "¹²":
                r = rpr + '<w:vertAlign w:val="superscript"/>'
                t = {"¹": "1", "²": "2"}[tok]
            out.append(
                f'<w:r><w:rPr>{r}</w:rPr><w:t xml:space="preserve">{escape(t)}</w:t></w:r>'
            )
    return "".join(out)


def par(
    texto: str,
    *,
    linha: int = 360,
    jc: str | None = None,
    recuo: bool = False,
    negrito: bool = False,
    rpr: str = "",
    antes: int = 0,
    depois: int = 0,
    keep_next: bool = False,
    sz: int | None = None,
) -> str:
    ppr = [
        f'<w:spacing w:before="{antes}" w:after="{depois}" w:line="{linha}" w:lineRule="auto"/>'
    ]
    if recuo:
        ppr.append('<w:ind w:firstLine="709"/>')
    if jc:
        ppr.append(f'<w:jc w:val="{jc}"/>')
    if keep_next:
        ppr.insert(0, "<w:keepNext/>")
    base = (
        rpr
        + ("<w:b/><w:bCs/>" if negrito else "")
        + (f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>' if sz else "")
    )
    return f"<w:p><w:pPr>{''.join(ppr)}<w:rPr>{base}</w:rPr></w:pPr>{runs(texto, base)}</w:p>"


def vazio(linha: int = 360) -> str:
    return f'<w:p><w:pPr><w:spacing w:after="0" w:line="{linha}" w:lineRule="auto"/></w:pPr></w:p>'


# tabelas
def tabela(linhas: list[str]) -> str:
    celulas = [
        [c.strip() for c in l.strip().strip("|").split("|")]
        for l in linhas
        if not re.match(r"^\|\s*-", l)
    ]
    ncol = len(celulas[0])
    largura = 9070
    # larguras proporcionais ao conteúdo mais longo de cada coluna (cabeçalho pesa menos,
    # porque pode quebrar linha), com piso para colunas curtas
    pesos = []
    for j in range(ncol):
        corpo = max((len(l[j]) for l in celulas[1:]), default=1)
        maior_palavra = (
            max(len(w) for l in celulas for w in l[j].split()) if celulas else 1
        )
        cab = len(celulas[0][j]) / 1.6
        pesos.append(max(7.0, corpo, cab, maior_palavra * 1.5))
    total = sum(pesos)
    colw = [int(largura * w / total) for w in pesos]
    colw[-1] += largura - sum(colw)
    sz = 22  # Arial 11 em todas as tabelas (manual de formatação do curso, Tabela 9)
    xml = [
        '<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:jc w:val="center"/>'  # noqa: UP031
        '<w:tblBorders><w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
        '<w:left w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        '<w:tblCellMar><w:left w:w="57" w:type="dxa"/><w:right w:w="57" w:type="dxa"/></w:tblCellMar>'
        '<w:tblLook w:val="04A0"/></w:tblPr>' % largura
    ]
    xml.append(
        "<w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{w}"/>' for w in colw)
        + "</w:tblGrid>"
    )
    for i, linha in enumerate(celulas):
        xml.append("<w:tr>" + ("<w:trPr><w:tblHeader/></w:trPr>" if i == 0 else ""))
        for j, c in enumerate(linha):
            borda = (
                '<w:tcBorders><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders>'
                if i == 0
                else ""
            )
            if i == 0:
                jc = "left" if j == 0 else "center"
            elif j == 0:
                jc = "left"
            else:
                numerico = (
                    re.match(
                        r"^(≈ )?[−\-]?[0-9][0-9.,]*( × 10[⁰-⁹¹²³]*| a [0-9.,]+ mil| mil)?$",
                        c,
                    )
                    or c.startswith("mate em")
                    or c in ("–", "—")
                )
                jc = "right" if numerico else "both"
            xml.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{colw[j]}" w:type="dxa"/>{borda}<w:vAlign w:val="center"/></w:tcPr>'
                + par(c, linha=240, jc=jc, sz=sz)
                + "</w:tc>"
            )
        xml.append("</w:tr>")
    xml.append("</w:tbl>")
    return "".join(xml)


# figuras
class Imagens:
    def __init__(self, tpl_dir: Path, figuras: Path):
        self.tpl_dir, self.figuras, self.n = tpl_dir, figuras, 0
        self.rels: list[str] = []

    def inserir(self, arquivo: str) -> str:
        self.n += 1
        src = self.figuras / arquivo
        dest = self.tpl_dir / "word" / "media" / f"fig{self.n}.png"
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(src, dest)
        rid = f"rIdFig{self.n}"
        self.rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/fig{self.n}.png"/>'
        )
        w, h = Image.open(src).size
        cx = LARGURA_TEXTO_EMU
        cy = int(cx * h / w)
        if cy > ALTURA_MAX_EMU:
            cy = ALTURA_MAX_EMU
            cx = int(cy * w / h)
        return (
            '<w:p><w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{100 + self.n}" name="Figura {self.n}"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{100 + self.n}" name="fig{self.n}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
        )


# markdown para o corpo
def construir(md: str, imgs: Imagens) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)
    linhas = md.split("\n")
    # lista de figuras (mapa número → arquivo, legenda, fonte)
    figuras: dict[int, tuple[str, str, str]] = {}
    if "## Lista de figuras" in md:
        bloco = md[md.index("## Lista de figuras") :]
        for m in re.finditer(r"- Figura (\d+): (\S+) — (.+?)\. Fonte: (.+)", bloco):
            figuras[int(m.group(1))] = (
                Path(m.group(2)).name,
                m.group(3).strip(),
                m.group(4).strip(),
            )
        linhas = md[: md.index("## Lista de figuras")].split("\n")

    corpo: list[str] = []
    inseridas: set[int] = set()
    secao = ""
    i = 0
    titulo = ""
    while i < len(linhas):
        l = linhas[i].rstrip()
        if not l.strip():
            i += 1
            continue
        if l.startswith("# "):
            titulo = l[2:].strip()
            corpo.append(par(titulo, linha=240, jc="center", negrito=True))
            corpo.append(vazio(240))
            corpo.append(vazio(240))
            i += 1
            continue
        if l.startswith("## "):
            secao = l[3:].strip()
            if secao == "Resumo":
                # manual de formatação, item 16.2: título, resumo e palavras-chave formam a segunda página
                corpo.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
                corpo.append(par(titulo, linha=240, jc="center", negrito=True))
                corpo.append(vazio(240))
                corpo.append(par("Resumo", linha=240, jc="left", negrito=True))
            elif secao == "Referências":
                corpo.append(vazio(360))
                corpo.append(
                    par(
                        "Referências",
                        linha=360,
                        jc="left",
                        negrito=True,
                        keep_next=True,
                    )
                )
                corpo.append(vazio(240))
            else:
                corpo.append(vazio(360))
                corpo.append(
                    par(secao, linha=360, jc="left", negrito=True, keep_next=True)
                )
                corpo.append(vazio(360))
            i += 1
            continue
        if l.startswith("### "):
            corpo.append(
                par(
                    l[4:].strip(),
                    linha=360,
                    recuo=True,
                    negrito=True,
                    keep_next=True,
                    jc="left",
                )
            )
            i += 1
            continue
        if l.startswith("|"):
            bloco = []
            while i < len(linhas) and linhas[i].startswith("|"):
                bloco.append(linhas[i])
                i += 1
            corpo.append(tabela(bloco))
            continue
        if re.match(r"^Tabela \d+\. ", l):
            corpo.append(par(l, linha=240, jc="left", keep_next=True, antes=120))
            i += 1
            continue
        if l.startswith(("Fonte:", "Nota:")):
            corpo.append(
                par(
                    l,
                    linha=240,
                    jc="left",
                    depois=120 if l.startswith("Fonte:") else 60,
                )
            )
            i += 1
            continue
        if secao == "Resumo":
            if l.startswith("**Palavras-chave:**"):
                corpo.append(par(l, linha=240))
            else:
                corpo.append(par(l, linha=240))
            i += 1
            continue
        if secao == "Referências":
            corpo.append(par(l, linha=240, jc="left", depois=120))
            i += 1
            continue
        if not secao:  # folha de rosto: autores e afiliações
            if l.startswith("**"):
                corpo.append(par(l, linha=240, jc="center", sz=18))
                corpo.append(vazio(240))
            else:
                corpo.append(par(l, linha=240, jc="left", sz=18))
            i += 1
            continue
        # parágrafo de corpo
        corpo.append(par(l, linha=360, recuo=True))
        i += 1
        # figuras citadas pela primeira vez neste parágrafo entram logo abaixo
        for num in sorted(
            {int(n) for n in re.findall(r"Figuras? (\d+)", l)}
            | {int(n) for n in re.findall(r"Figuras \d+ e (\d+)", l)}
        ):
            if num in figuras and num not in inseridas:
                arq, legenda, fonte = figuras[num]
                inseridas.add(num)
                corpo.append(imgs.inserir(arq))
                corpo.append(
                    par(
                        f"Figura {num}. {legenda}", linha=240, jc="both", keep_next=True
                    )
                )
                corpo.append(par(f"Fonte: {fonte}", linha=240, jc="left", depois=120))
    return "".join(corpo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, type=Path)
    ap.add_argument("--template", required=True, type=Path)
    ap.add_argument("--figuras", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="tcc_docx_"))
    with zipfile.ZipFile(args.template) as z:
        z.extractall(tmp)
    doc_path = tmp / "word" / "document.xml"
    xml = doc_path.read_text(encoding="utf8")
    inicio = xml.index("<w:body>") + len("<w:body>")
    fim = xml.index("<w:sectPr")
    imgs = Imagens(tmp, args.figuras)
    corpo = construir(args.md.read_text(encoding="utf8"), imgs)
    xml = xml[:inicio] + corpo + xml[fim:]
    doc_path.write_text(xml, encoding="utf8")

    for h in (tmp / "word").glob("header*.xml"):
        t = h.read_text(encoding="utf8")
        t = t.replace(
            " _________ (Nome do curso) – ____ (ano da defesa)",
            " Engenharia de Software – 2026",
        )
        h.write_text(t, encoding="utf8")

    rels_path = tmp / "word" / "_rels" / "document.xml.rels"
    rels = rels_path.read_text(encoding="utf8")
    rels = rels.replace("</Relationships>", "".join(imgs.rels) + "</Relationships>")
    rels_path.write_text(rels, encoding="utf8")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(tmp.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(tmp).as_posix())
    shutil.rmtree(tmp)
    print(args.out, f"({imgs.n} figuras)")


if __name__ == "__main__":
    main()

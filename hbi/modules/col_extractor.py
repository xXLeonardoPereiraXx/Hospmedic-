"""Módulo ``col_extractor``: leitura de itens por POSIÇÃO de coluna.

Alguns editais vêm de sistemas que imprimem um relatório (não uma tabela com
grade): sem linhas desenhadas, com colunas alinhadas por posição. A ordem em
que o PDF despeja o texto desses arquivos não segue as linhas visuais — o
código do produto sai depois da descrição, a quantidade no meio dela, o título
de um item embaralhado com a numeração (visto no edital de Londrina,
PE 131/2026). A leitura por âncoras, que trabalha sobre o texto já achatado em
linhas, herda essa bagunça.

Aqui o texto não é achatado: cada palavra é atribuída a uma coluna pela sua
coordenada x, e a uma linha pela coordenada y. O cabeçalho da tabela define
onde começa cada coluna, então nada é fixo no código — vale para qualquer
relatório com cabeçalho "Item ... Descrição ... Quantidade ... Total".

Esta estratégia é tentada quando a leitura por âncoras ficou com descrições
contaminadas (colunas de código e quantidade misturadas ao texto) e só é
adotada se reproduzir exatamente os mesmos números (ver ``table_extractor``).
"""
from __future__ import annotations

import re

from hbi.models.edital import ItemEdital
from hbi.utils import cancelamento
from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)

_MONEY = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
_QTD = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:[.,]\d{1,2})?$|^\d+$")
_LOTE_TITULO = re.compile(r"^Lote:?$", re.I)
_FIM_LOTE = re.compile(r"^PRE[ÇC]O$", re.I)  # "PREÇO MÁXIMO DO LOTE:" / "DA LICITAÇÃO:"
_TOL_LINHA = 3.0          # pt: palavras com tops próximos pertencem à mesma linha
_TOL_PRIMEIRA = 4.5       # pt: tolerância maior para os campos da linha do item


def _para_float(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _qtd_para_float(s: str) -> float:
    """'175.00' -> 175.0 | '6.350' -> 6350.0 | '1.200,50' -> 1200.5"""
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    m = re.fullmatch(r"(\d+)\.(\d{2})", s)   # decimal com ponto: "175.00"
    if m:
        return float(s)
    return float(s.replace(".", ""))          # milhar com ponto: "6.350"


def _cabecalho(palavras) -> dict | None:
    """Posições das colunas, lidas das palavras do cabeçalho da tabela."""
    def acha(rotulos, minimo_top=None):
        cand = [w for w in palavras
                if re.fullmatch(rotulos, w["text"], re.I)
                and (minimo_top is None or w["top"] >= minimo_top)]
        return sorted(cand, key=lambda w: (w["top"], w["x0"]))
    desc = acha(r"Descri[çc][ãa]o|DESCRI[ÇC][ÃA]O")
    qtd = acha(r"Quantidade|QUANT\.?|QTDE?\.?")
    item = acha(r"Item|ITEM")
    if not (desc and qtd and item):
        return None
    # o cabeçalho é a ocorrência de "Descrição" que tem "Quantidade" por perto
    for d in desc:
        q = next((w for w in qtd if abs(w["top"] - d["top"]) <= 8 and w["x0"] > d["x0"]), None)
        i = next((w for w in item if abs(w["top"] - d["top"]) <= 8 and w["x0"] < d["x0"]), None)
        if q and i:
            return {"x_item": i["x0"], "x_desc": d["x0"], "x_qtd": q["x0"]}
    return None


def _linhas(palavras, tol=_TOL_LINHA):
    """Agrupa palavras em linhas visuais pelo top; cada linha ordenada por x."""
    grupos: list[list[dict]] = []
    for w in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
        if grupos and abs(w["top"] - grupos[-1][0]["top"]) <= tol:
            grupos[-1].append(w)
        else:
            grupos.append([w])
    return [sorted(g, key=lambda w: w["x0"]) for g in grupos]


def extrair_por_colunas(caminho, paginas: list[int] | None = None) -> list[ItemEdital]:
    """Extrai itens atribuindo cada palavra à coluna pela posição x.

    Args:
        caminho: PDF do edital.
        paginas: índices (0-based) das páginas a ler; ``None`` lê todas.
    """
    import pdfplumber

    itens: list[ItemEdital] = []
    lote: int | None = None
    with pdfplumber.open(str(caminho)) as pdf:
        indices = paginas if paginas is not None else range(len(pdf.pages))
        for n in indices:
            cancelamento.checar()
            palavras = pdf.pages[n].extract_words(x_tolerance=2, y_tolerance=2)
            cab = _cabecalho(palavras)
            if cab is None:
                continue
            x_desc, x_qtd = cab["x_desc"] - 3, cab["x_qtd"] - 3

            # eventos verticais da página: início de item, início de lote e
            # fim de lote — delimitam até onde vai cada descrição
            linhas = _linhas(palavras)
            eventos = []   # (top, tipo, dados)
            for ln in linhas:
                top = ln[0]["top"]
                direita = [w for w in ln if w["x0"] >= x_qtd]
                dinheiro = [w for w in direita if _MONEY.match(w["text"])]
                if (ln[0]["x0"] < 30 and _LOTE_TITULO.match(ln[0]["text"]) and len(ln) > 1):
                    m = re.match(r"\d+", ln[1]["text"])
                    if m:
                        eventos.append((top, "lote", int(m.group())))
                    continue
                if _FIM_LOTE.match(ln[0]["text"]) and any("LOTE" in w["text"].upper() or
                                                          "LICITA" in w["text"].upper() for w in ln):
                    eventos.append((top, "fim", None))
                    continue
                if len(dinheiro) >= 2:
                    eventos.append((top, "item", ln))
                if any(re.fullmatch(r"Item|ITEM", w["text"]) for w in ln) and \
                        any(re.match(r"Descri", w["text"], re.I) for w in ln):
                    eventos.append((top, "cabecalho", None))
            eventos.sort(key=lambda e: e[0])

            for k, (top, tipo, dado) in enumerate(eventos):
                if tipo == "lote":
                    lote = dado
                    continue
                if tipo != "item":
                    continue
                ln = dado
                # fim da faixa vertical deste item: o próximo evento relevante
                fim = next((t for t, tp, _ in eventos[k + 1:]), pdf.pages[n].height)
                # campos numéricos da linha do item (à direita da descrição)
                direita = [w for w in palavras
                           if w["x0"] >= x_qtd and abs(w["top"] - top) <= _TOL_PRIMEIRA]
                direita.sort(key=lambda w: w["x0"])
                dinheiro = [w for w in direita if _MONEY.match(w["text"])]
                unit, total = _para_float(dinheiro[-2]["text"]), _para_float(dinheiro[-1]["text"])
                qtd_tok = next((w["text"] for w in direita if _QTD.match(w["text"])
                                and not _MONEY.match(w["text"])), None)
                if qtd_tok is None:
                    continue
                unidade = next((w["text"] for w in direita
                                if re.fullmatch(r"[A-Za-zÀ-ú.]{1,12}", w["text"])), "")
                # descrição: na linha do item, só a coluna de descrição (à
                # direita dela ficam quantidade e preços); nas linhas
                # seguintes o texto detalhado corre por baixo das colunas
                # numéricas, ocupando a largura toda — por isso ali não há
                # limite à direita, só à esquerda (onde ficam grupo,
                # subgrupo e código do produto, que não são descrição)
                desc = [w for w in palavras
                        if w["x0"] >= x_desc and w["top"] < fim - 1
                        and (w["x0"] < x_qtd if abs(w["top"] - top) <= _TOL_PRIMEIRA
                             else w["top"] > top + _TOL_PRIMEIRA)]
                texto = " ".join(" ".join(w["text"] for w in l)
                                 for l in _linhas(desc))
                itens.append(ItemEdital(
                    item=len(itens) + 1, descricao=normalizar_espacos(texto),
                    unidade=unidade, quantidade=_qtd_para_float(qtd_tok),
                    valor_estimado=unit, valor_total=total, pagina=n + 1, lote=lote,
                ))
    log.info("Itens extraídos: %d (posição das colunas)", len(itens))
    return itens

"""Módulo ``grid_extractor``: extração por células, para tabelas com grade.

A leitura por âncoras (ver ``table_extractor``) trabalha sobre o texto já
achatado em linhas. Isso funciona na maioria dos editais, mas falha quando o
PDF entrelaça as colunas ao linearizar — e aí uma coluna cai no meio da
descrição, ou um valor é partido entre três linhas:

    'CONCENTRAÇÃO: A 10%, FORMA        R$      R$'
    '4  FR  208'
    'FARMACEUTICA: SOLUÇÃO AQUOSA. 1  88,51  18.410,08'

Quando o PDF desenha a tabela (bordas de célula), existe informação melhor do
que o texto: a própria grade. Lendo célula a célula, cada campo sai inteiro e
no lugar certo — inclusive colunas que a leitura linear nem enxergaria, como
a de marcas aprovadas.

Esta estratégia é tentada quando há grade e a leitura por âncoras ficou
incompleta; o resultado só é adotado se for melhor (ver ``table_extractor``).
"""
from __future__ import annotations

import re
from collections import Counter

from hbi.models.edital import ItemEdital
from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)

_MONEY = re.compile(r"^R?\$?\s*\d{1,3}(?:\.\d{3})*,\d{2,4}$")
_INT = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$")
# Unidades de fornecimento: vocabulário curto, só para reconhecer a coluna.
_UNID = re.compile(
    r"^(UN|UND|UNID|UNIDADE|PC|PCT|PACOTE|CX|CAIXA|CAI|FR|FRA|FRASCO|ROLO|RL"
    r"|PAR|KG|G|L|ML|MT|M|AMP|AMPOLA|TB|GL|KIT|PEÇA|PECA|RESMA|GALÃO|GALAO"
    r"|SC|SACO|BAG|BISNAGA|TUBO|LATA|BARRA|BOBINA|ENV|ENVELOPE|DZ|FD|JOGO)S?$",
    re.I,
)


def _txt(c) -> str:
    return normalizar_espacos((c or "").replace("\n", " "))


def _para_float(s: str) -> float | None:
    s = re.sub(r"[R$\s]", "", s or "")
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _colunas_dominantes(pdf, paginas: list[int]) -> list[float]:
    """Posições x das bordas verticais que se repetem na maioria das páginas.

    Fixar as colunas para o documento inteiro evita que cada página seja
    fatiada de um jeito — o pdfplumber, sozinho, varia o número de colunas
    conforme o conteúdo de cada página.
    """
    cont: Counter = Counter()
    for i in paginas:
        for e in pdf.pages[i].vertical_edges:
            cont[round(e["x0"])] += 1
    if not cont:
        return []
    limite = max(cont.values()) * 0.25
    xs = sorted(x for x, n in cont.items() if n >= limite)
    # junta bordas quase coincidentes (traço duplo da mesma linha)
    juntos: list[float] = []
    for x in xs:
        if not juntos or x - juntos[-1] > 6:
            juntos.append(float(x))
    return juntos


def _mapear_colunas(linhas: list[list[str]]) -> dict | None:
    """Descobre qual índice de coluna é item, unidade, quantidade e valores.

    O mapeamento é deduzido do conteúdo — e não de uma ordem fixa — porque a
    posição das colunas varia entre editais. São usadas as linhas que parecem
    itens completos, e vence o índice que mais vezes se comportou como cada
    tipo de dado.
    """
    papel: dict[str, Counter] = {k: Counter() for k in
                                 ("item", "unid", "qtd", "unit", "total")}
    for row in linhas:
        money = [j for j, c in enumerate(row) if _MONEY.match(c)]
        if len(money) < 2:
            continue
        unid = [j for j, c in enumerate(row) if _UNID.match(c)]
        itens = [j for j, c in enumerate(row)
                 if c.isdigit() and 0 < int(c) < 10000]
        if not itens:
            continue
        papel["item"][itens[0]] += 1
        papel["unit"][money[-2]] += 1
        papel["total"][money[-1]] += 1
        if unid:
            papel["unid"][unid[-1]] += 1
            qtd = [j for j, c in enumerate(row)
                   if _INT.match(c) and unid[-1] < j < money[-2]]
            if qtd:
                papel["qtd"][qtd[0]] += 1

    if not papel["item"] or not papel["total"]:
        return None
    mapa = {k: (v.most_common(1)[0][0] if v else None) for k, v in papel.items()}
    # a descrição é a coluna de texto mais longa que não tem papel numérico
    usados = {v for v in mapa.values() if v is not None}
    larguras: Counter = Counter()
    for row in linhas:
        for j, c in enumerate(row):
            if j not in usados and len(c) > 15:
                larguras[j] += len(c)
    mapa["desc"] = larguras.most_common(1)[0][0] if larguras else None
    # colunas de texto restantes (ex.: marcas aprovadas) viram informação extra
    usados |= {mapa["desc"]}
    mapa["extras"] = [
        j for j, _ in larguras.most_common() if j not in usados
    ][:2]
    return mapa


def _corrigir_separador(qtd, unit, total):
    """Resolve o ponto ambíguo (milhar ou decimal) pela conta do próprio edital.

    Há editais que imprimem o preço ora com vírgula ("1,332") ora com ponto
    ("1.332") na mesma tabela. Lido como milhar, R$ 1,332 vira R$ 1.332,00 e o
    item fica mil vezes mais caro. Como a linha traz quantidade e total, a
    própria aritmética diz qual leitura é a correta — e só se ela passar a
    fechar é que a interpretação é trocada.
    """
    if not (qtd and unit and total):
        return unit, qtd
    if abs(qtd * unit - total) <= 0.5:
        return unit, qtd
    for divisor in (1000, 100):
        if abs(qtd * (unit / divisor) - total) <= 0.5:
            return unit / divisor, qtd
    return unit, qtd


def extrair_por_grade(caminho) -> tuple[list[ItemEdital], dict[int, str]]:
    """Extrai itens lendo as células da tabela desenhada no PDF.

    Returns:
        ``(itens, extras)`` — os itens e, quando existir uma coluna de texto
        adicional (tipicamente marcas aprovadas), um dicionário
        ``item -> conteúdo`` para quem quiser registrá-la à parte.
    """
    import pdfplumber

    with pdfplumber.open(str(caminho)) as pdf:
        # Nem todo PDF desenha a tabela com retângulos: alguns usam apenas
        # traços. Ambos servem como indício de grade.
        paginas = [
            i for i, pg in enumerate(pdf.pages)
            if len(pg.rects) > 20 or len(pg.vertical_edges) >= 8
        ]
        if not paginas:
            return [], {}

        # Duas formas de cortar as colunas, cada uma melhor num tipo de PDF:
        #  - colunas fixas do documento, quando a tabela é a mesma em todas as
        #    páginas (evita que cada página seja fatiada de um jeito);
        #  - colunas por página, quando o arquivo mistura tabelas diferentes e
        #    um corte global picotaria o texto.
        # Em vez de adivinhar, as duas são medidas e vence a que reconhece
        # mais linhas de item.
        base = {"horizontal_strategy": "lines", "intersection_tolerance": 5}
        tentativas = [base | {"vertical_strategy": "lines"}]
        cols = _colunas_dominantes(pdf, paginas)
        if len(cols) >= 4:
            tentativas.insert(0, base | {"vertical_strategy": "explicit",
                                         "explicit_vertical_lines": cols})

        brutas: list[tuple[int, list[str]]] = []
        melhor = -1
        for ts in tentativas:
            linhas: list[tuple[int, list[str]]] = []
            for i in paginas:
                try:
                    tabela = pdf.pages[i].extract_table(ts) or []
                except Exception:  # noqa: BLE001 — estratégia inviável nesta página
                    continue
                for row in tabela:
                    linhas.append((i + 1, [_txt(c) for c in row]))
            pontos = sum(
                1 for _, r in linhas
                if sum(1 for c in r if _MONEY.match(c)) >= 2
                and any(c.isdigit() for c in r)
            )
            if pontos > melhor:
                melhor, brutas = pontos, linhas
        log.info("Grade: %d linhas de item reconhecidas.", melhor)

    if not brutas:
        return [], {}

    mapa = _mapear_colunas([r for _, r in brutas])
    if not mapa or mapa.get("desc") is None:
        log.info("Grade encontrada, mas sem colunas reconhecíveis.")
        return [], {}

    def val(row, chave):
        j = mapa.get(chave)
        return row[j] if j is not None and j < len(row) else ""

    itens: list[ItemEdital] = []
    extras: dict[int, str] = {}
    atual: ItemEdital | None = None
    esperado = 1
    for pagina, row in brutas:
        n_txt = val(row, "item")
        unit = _para_float(val(row, "unit"))
        total = _para_float(val(row, "total"))
        if n_txt.isdigit() and (unit or total):
            num = int(n_txt)
            if not (esperado - 2 <= num <= esperado + 30):
                continue  # número fora de sequência: não é linha de item
            qtd = _para_float(val(row, "qtd"))
            if not qtd and unit and total and unit > 0:
                qtd = round(total / unit, 4)
            if unit is None and total and qtd:
                unit = round(total / qtd, 4)
            if total is None and unit and qtd:
                total = round(unit * qtd, 2)
            unit, qtd = _corrigir_separador(qtd, unit, total)
            atual = ItemEdital(
                item=num, descricao=val(row, "desc"), unidade=val(row, "unid"),
                quantidade=qtd or 0.0, valor_estimado=unit or 0.0,
                valor_total=total or 0.0, pagina=pagina,
            )
            itens.append(atual)
            esperado = num + 1
            for j in mapa.get("extras", []):
                if j < len(row) and row[j]:
                    extras[num] = normalizar_espacos(
                        (extras.get(num, "") + " " + row[j]).strip()
                    )
        elif atual is not None:
            # linha de continuação: completa a descrição e as colunas extras
            cont = val(row, "desc")
            if cont:
                atual.descricao = normalizar_espacos(f"{atual.descricao} {cont}")
            for j in mapa.get("extras", []):
                if j < len(row) and row[j]:
                    extras[atual.item] = normalizar_espacos(
                        (extras.get(atual.item, "") + " " + row[j]).strip()
                    )

    # Um mesmo item pode reaparecer noutra tabela do documento (anexo de
    # amostras, quadro retificado). Fica a ocorrência cuja conta fecha —
    # e, em caso de empate, a primeira, que é a tabela principal.
    unicos: dict[int, ItemEdital] = {}
    for i in itens:
        fecha = abs(i.quantidade * i.valor_estimado - i.valor_total) <= 0.5
        anterior = unicos.get(i.item)
        if anterior is None:
            unicos[i.item] = i
            continue
        antes_fecha = abs(
            anterior.quantidade * anterior.valor_estimado - anterior.valor_total
        ) <= 0.5
        if fecha and not antes_fecha:
            unicos[i.item] = i
    if len(unicos) != len(itens):
        log.info("Itens repetidos em outra tabela: %d descartados.",
                 len(itens) - len(unicos))
    itens = [unicos[k] for k in sorted(unicos)]

    log.info("Itens extraídos: %d (células da tabela)", len(itens))
    return itens, extras

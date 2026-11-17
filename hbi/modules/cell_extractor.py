"""Leitura da tabela de itens pelas células desenhadas no PDF.

A causa do "item comendo a descrição do vizinho" é que as outras leituras
trabalham com linhas de texto e ADIVINHAM onde um item termina (número no
começo da linha, espaçamento, equilíbrio de linhas). Quando a tabela tem
bordas desenhadas, não é preciso adivinhar: cada linha da tabela é a faixa
entre duas bordas horizontais, e cada palavra pertence à faixa e à coluna
onde está o seu centro. A borda é a fronteira — a descrição de um item não
tem como cair na célula de outro.

Detalhes que esta leitura resolve:

* bordas desenhadas célula a célula (dezenas de segmentos curtos): os
  segmentos são somados por altura e viram uma borda só;
* faixas decorativas na margem (Missal): só contam as bordas verticais
  dentro da extensão das bordas horizontais da tabela;
* tabela deslocada entre páginas (São José dos Pinhais): as colunas são
  mapeadas pela posição RELATIVA à largura da tabela, não pelo x absoluto;
* cabeçalho com "QUANT. UND" numa célula e as páginas seguintes com duas
  colunas: a quantidade é separada da unidade pelo texto;
* item cortado pela quebra de página: a primeira faixa da página seguinte,
  sem número, é o resto da descrição (e, se for o caso, dos valores);
* cabeçalho/rodapé de página dentro da grade: faixas repetidas em 3+ páginas
  são ignoradas.

A leitura informa as faixas com texto que ficaram sem dono no meio da tabela
(``orfas``). Com qualquer órfã, quem chama não deve adotá-la: seria perder
texto em silêncio.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from hbi.models.edital import ItemEdital
from hbi.utils.logger import get_logger

log = get_logger(__name__)

_MONEY = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2,4}$")

# Papel de cada coluna pelo texto do cabeçalho (ordem = prioridade).
_PAPEIS = [("desc", r"DESCRI|ESPECIFICA|DISCRIMINA"),
           ("unit", r"UNIT|M[ÉE]DI[OA]"),
           ("total", r"TOTAL"),
           ("qtd", r"QUANT|QTD|QTDE|QNT"),
           ("und", r"^UNI|^UND|^UN\b|EMBAL|MEDIDA"),
           ("cod", r"CATMAT|C[ÓO]D|CATSER"),
           ("item", r"^ITEM|^N[º°O]\.?$|^ITENS|^LOTE")]
_DESC_RESERVA = r"PRODUTO|OBJETO"


def _agrupar(vals, tol=2.0):
    vals = sorted(vals, key=lambda t: t[0])
    g: list[list[float]] = []
    for y, c in vals:
        if g and y - g[-1][0] <= tol:
            g[-1][1] += c
        else:
            g.append([y, c])
    return g


def _uniao(intervalos):
    """Comprimento coberto por uma lista de intervalos (sem contar sobreposição)."""
    tot, fim = 0.0, None
    for a, b in sorted(intervalos):
        if fim is None or a > fim:
            tot += b - a
            fim = b
        elif b > fim:
            tot += b - fim
            fim = b
    return tot


def _fronteiras(p):
    """(ys das bordas horizontais, xs das bordas verticais) da tabela da página.

    Uma borda de linha é uma altura onde os segmentos horizontais cobrem quase
    toda a largura da tabela. Mede-se a extensão COBERTA (união), não a soma:
    PDFs que desenham cada célula como retângulo repetem o mesmo trecho várias
    vezes, e retângulos internos da célula de descrição não podem passar por
    borda da tabela inteira.
    """
    hs = [e for e in p.edges if e["orientation"] == "h" and e["x1"] - e["x0"] > 0.5]
    vs = [e for e in p.edges if e["orientation"] == "v" and e["bottom"] - e["top"] > 0.5]
    if not hs or not vs:
        return None
    grupos: list[list] = []
    for e in sorted(hs, key=lambda e: e["top"]):
        if grupos and e["top"] - grupos[-1][0] <= 2:
            grupos[-1][1].append((e["x0"], e["x1"]))
        else:
            grupos.append([e["top"], [(e["x0"], e["x1"])]])
    cobertura = [(y, _uniao(iv), min(a for a, _ in iv), max(b for _, b in iv)) for y, iv in grupos]
    # Largura de referência: a maior que se repete 3+ vezes na página (as
    # linhas da tabela se repetem; fios decorativos de cabeçalho/rodapé, mais
    # largos que a tabela, aparecem uma ou duas vezes). Sem repetição, a maior.
    largas = sorted((c for _, c, _, _ in cobertura if c >= 0.4 * p.width), reverse=True)
    if not largas:
        return None
    ref = next((c for c in largas
                if sum(1 for d in largas if abs(d - c) <= 0.02 * c) >= 3), largas[0])
    linhas = [(y, a, b) for y, c, a, b in cobertura if 0.85 * ref <= c <= 1.05 * ref]
    if len(linhas) < 2:
        return None
    ys = [y for y, _, _ in linhas]
    x0 = sorted(a for _, a, _ in linhas)[len(linhas) // 2]
    x1 = sorted(b for _, _, b in linhas)[len(linhas) // 2]
    vs = [e for e in vs if x0 - 2 <= e["x0"] <= x1 + 2 and e["bottom"] > ys[0] and e["top"] < ys[-1]]
    if not vs:
        return None
    alt = ys[-1] - ys[0]
    xs = [x for x, c in _agrupar([(e["x0"], e["bottom"] - e["top"]) for e in vs])
          if c >= 0.3 * alt]
    if len(xs) < 3:
        return None
    return ys, xs


def _faixas(p, ys, xs):
    """Texto de cada célula, faixa a faixa."""
    ws = p.extract_words(x_tolerance=3, y_tolerance=2)
    for a, b in zip(ys, ys[1:]):
        cel = defaultdict(list)
        for w in ws:
            yc = (w["top"] + w["bottom"]) / 2
            xc = (w["x0"] + w["x1"]) / 2
            if a <= yc < b and xs[0] <= xc <= xs[-1]:
                ci = max(i for i, x in enumerate(xs[:-1]) if x <= xc)
                cel[ci].append(w)
        textos = []
        for ci in range(len(xs) - 1):
            lw = sorted(cel.get(ci, []), key=lambda w: (round(w["top"]), w["x0"]))
            textos.append(" ".join(w["text"] for w in lw))
        if any(textos):
            yield textos


def _mapa_colunas(textos, larguras=None):
    """Papel de cada coluna pelo texto do cabeçalho.

    O texto é comparado também sem espaços ("LOT E" -> "LOTE", "UN D" ->
    "UND"), porque alguns PDFs espaçam as letras. Sem coluna chamada
    "Descrição", a descrição é a coluna mais larga ainda sem papel (editais
    que chamam a coluna de descrição de "ITEM" e a de número de "LOTE").
    """
    nomes = [t.upper().strip() for t in textos]
    juntos = [re.sub(r"\s+", "", t) for t in nomes]
    m: dict[str, int] = {}
    for papel, pat in _PAPEIS:
        for i, (T, J) in enumerate(zip(nomes, juntos)):
            if i in m.values() or not T:
                continue
            if papel == "unit" and "TOTAL" in J:
                continue
            if papel == "und" and re.search(r"QUANT|QTD|QNT", J):
                continue
            if re.search(pat, T) or re.search(pat, J):
                m[papel] = i
                break
    if "desc" not in m:
        for i, J in enumerate(juntos):
            if i not in m.values() and re.search(_DESC_RESERVA, J):
                m["desc"] = i
                break
    if "desc" not in m and larguras and ("total" in m or "unit" in m):
        livres = [i for i in range(len(nomes)) if nomes[i] and i not in m.values()]
        # "ITEM" ocupando a coluna larga: é a descrição, e o número é o LOTE
        if "item" in m and nomes[m["item"]].startswith("ITE") and \
                larguras[m["item"]] == max(larguras) and any(j.startswith("LOT") for j in juntos):
            m["desc"] = m.pop("item")
            m["item"] = next(i for i, j in enumerate(juntos) if j.startswith("LOT"))
        elif livres:
            larga = max(livres, key=lambda i: larguras[i])
            if larguras[larga] == max(larguras):
                m["desc"] = larga
    if "item" in m and "desc" in m and m["item"] == m["desc"]:
        return None
    return m if "desc" in m and ("total" in m or "unit" in m) else None


def _junta_digitos(t: str) -> str:
    """'1.00 0' -> '1.000' (dígitos que o PDF espaçou)."""
    return re.sub(r"(?<=[\d.,])\s+(?=[\d.,]*\d)", "", t)


def _num(t: str) -> float | None:
    try:
        return float(t.replace("R$", "").replace(".", "").replace(",", ".").strip())
    except (ValueError, AttributeError):
        return None


def _qtd(t: str) -> float | None:
    """Quantidade: '1.000' é mil; '1,5' é um e meio."""
    t = t.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return float(t.replace(".", ""))
    return _num(t)


def extrair_por_celulas(caminho) -> tuple[list[ItemEdital], int]:
    """Itens lidos pelas células desenhadas e o número de faixas órfãs."""
    import pdfplumber

    from hbi.utils import cancelamento

    paginas = []
    with pdfplumber.open(str(caminho)) as pdf:
        for npg, p in enumerate(pdf.pages, 1):
            cancelamento.checar()
            fr = _fronteiras(p)
            if fr:
                paginas.append((npg, fr[1], list(_faixas(p, *fr))))
            p.flush_cache()
    if not paginas:
        return [], 0

    # assinatura sem dígitos: "Página 3 | 117" e "Página 4 | 117" são a mesma
    # (só em faixa curta e sem valor em R$ — nunca numa linha de item)
    def assinatura(t):
        txt = " | ".join(t)
        if len("".join(t)) <= 40 and not any(_MONEY.match(x.replace("R$", "").strip()) for x in t):
            return re.sub(r"\d+", "#", txt)
        return txt
    rep = Counter(assinatura(t) for _, _, fs in paginas for t in {tuple(x) for x in fs})
    repetidas = {k for k, n in rep.items() if n >= 3}

    brutos: list[dict] = []
    orfas = 0
    pendentes: list[int] = []   # páginas de faixas sem dono desde o último item
    cab = None
    for npg, xs, faixas in paginas:
        larg = xs[-1] - xs[0]
        rel = lambda x: (x - xs[0]) / larg  # noqa: E731
        antes_do_primeiro = True
        for textos in faixas:
            if assinatura(textos) in repetidas:
                continue
            cm = _mapa_colunas(textos, [xs[k + 1] - xs[k] for k in range(len(xs) - 1)])
            if cm:
                inv = {v: k for k, v in cm.items()}
                cab = [(rel(xs[i]), rel(xs[i + 1]), inv.get(i)) for i in range(len(xs) - 1)]
                pendentes = []          # troca de tabela: nada ficou entre dois itens
                continue
            if not cab:
                continue
            por = defaultdict(list)
            for ci, t in enumerate(textos):
                xc = rel((xs[ci] + xs[ci + 1]) / 2)
                papel = next((pp for a, b, pp in cab if a - 0.01 <= xc <= b + 0.01), None)
                if papel and t:
                    por[papel].append(t)
            g = lambda k: " ".join(por.get(k, [])).strip()  # noqa: E731
            num = re.sub(r"\D", "", g("item").split(" ")[0]) if g("item") else ""
            tot = _junta_digitos(g("total").replace("R$", "")).strip()
            uni = _junta_digitos(g("unit").replace("R$", "")).strip()
            qtd, und = _junta_digitos(g("qtd")), g("und")
            if qtd and not re.fullmatch(r"[\d.,]+", qtd):
                m = re.match(r"^\s*(\d[\d.,]*)\s*(.*)$", qtd)
                if m:
                    qtd, und = m.group(1), und or m.group(2).strip()
            ult = brutos[-1] if brutos else None
            incompleto = ult and not (_MONEY.match(ult["total"]) and _MONEY.match(ult["unit"]))
            if (incompleto and antes_do_primeiro and not num and ult["pg_fim"] == npg - 1
                    and (_MONEY.match(tot) or _MONEY.match(uni))):
                # linha cortada pela quebra de página, valores do outro lado
                if g("desc"):
                    ult["desc"] += " " + g("desc")
                ult["pg_fim"] = npg
                if _MONEY.match(tot) and not _MONEY.match(ult["total"]):
                    ult["total"] = tot
                if _MONEY.match(uni) and not _MONEY.match(ult["unit"]):
                    ult["unit"] = uni
                continue
            if num and (_MONEY.match(tot) or _MONEY.match(uni)):
                # faixa sem dono ENTRE este item e o anterior, na mesma
                # página e na mesma sequência: texto que seria perdido
                if ult and int(num) == ult["n"] + 1:
                    orfas += sum(1 for pg in pendentes if pg == npg)
                pendentes = []
                brutos.append(dict(n=int(num), desc=g("desc"), und=und, qtd=qtd,
                                   unit=uni, total=tot, pg=npg, pg_fim=npg))
                antes_do_primeiro = False
            elif (ult and antes_do_primeiro and ult["pg_fim"] == npg - 1
                  and not num and g("desc") and not tot and not uni):
                ult["desc"] += " " + g("desc")   # resto da descrição cortada pela página
                ult["pg_fim"] = npg
            elif brutos and g("desc") and not num:
                pendentes.append(npg)


    itens: list[ItemEdital] = []
    lote = 1
    reinicia = any(b["n"] == 1 for b in brutos[1:])
    for k, b in enumerate(brutos):
        if k and b["n"] == 1:
            lote += 1
        q, u, t = _qtd(b["qtd"]), _num(b["unit"]), _num(b["total"])
        if u is None and q and t is not None:
            u = round(t / q, 4)
        if t is None and q is not None and u is not None:
            t = round(q * u, 2)
        if q is None and u and t is not None:
            q = round(t / u, 4)
        itens.append(ItemEdital(
            item=b["n"], descricao=re.sub(r"\s+", " ", b["desc"]).strip(),
            unidade=b["und"], quantidade=q or 0.0, valor_estimado=u or 0.0,
            valor_total=t or 0.0, pagina=b["pg"], lote=lote if reinicia else None))
    log.info("Itens extraídos: %d (células desenhadas; %d faixas órfãs)", len(itens), orfas)
    return itens, orfas


def sequencia_ok(itens) -> bool:
    """Numeração 1..N sem saltos (podendo reiniciar a cada lote)."""
    if not itens or itens[0].item != 1:
        return False
    return all(b.item == a.item + 1 or b.item == 1 for a, b in zip(itens, itens[1:]))

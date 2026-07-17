"""Módulo ``table_extractor``: extração genérica da tabela de itens.

Estratégia independente de coordenadas de coluna, validada em layouts
distintos (edital com grade de células e edital em texto corrido):

1. **Âncora numérica**: uma linha que começa com um inteiro e termina com
   dois valores monetários (valor unitário e valor total). Ela marca a
   fronteira de cada item e é a fonte confiável dos valores.
2. **Contagem incremental**: a âncora só é aceita se o número for o próximo
   esperado (1, 2, 3, ...). Isso rejeita falsos-positivos de dígitos soltos.
3. **Descrição**: linhas de texto entre âncoras, atribuídas à âncora mais
   próxima dentro de uma janela máxima de linhas.
4. **Quantidade**: derivada de ``valor_total / valor_unitario`` (os dois
   dados mais confiáveis da linha); o parse do "miolo" da âncora serve como
   verificação cruzada.

Substitui a abordagem anterior por coordenadas fixas, que não generalizava
entre layouts de edital diferentes.
"""
from __future__ import annotations

import re

from hbi.config import settings
from hbi.models.edital import ItemEdital
from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)

_MONEY = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_ANCHOR = re.compile(r"^\s*(\d+)\b(.*?)(" + _MONEY + r")\s+(" + _MONEY + r")\s*$")
_NOISE = re.compile(
    r"(MUNIC[ÍI]PIO|Estado do Paran|ANEXO|^Item\b|^Und\b|^Forne|^\d+\.\d"
    r"|CNPJ|e-mail|Telefone|^Rua |HAVENDO|OBJETO CONSTANTE|EDITAL\."
    r"|CONDI[ÇC][ÕO]ES GERAIS|Registro de Pre|PREFEIT|ADVOGADO|CONTRATANTE"
    r"|Valor Uni|MÉDIA|PRODUTO|Descrição)",
    re.I,
)


def _to_float(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _quantidade_parse(miolo: str) -> float | None:
    """Último grupo inteiro do miolo da âncora (coluna de quantidade)."""
    toks = re.findall(r"\b\d{1,3}(?:\.\d{3})*\b", miolo)
    if not toks:
        return None
    return float(toks[-1].replace(".", ""))


_UNIDADE_RE = re.compile(
    r"\b(CX|CAIXA|UNID|UND|UNI|UN|PCT|PACOTE|ROLO|LITRO|EMB|FRASCO|PAR|KG"
    r"|ML|CONJ|BOLSA|GAL[ÃA]O|BOMBA|AMPOLA|FR|L|G)\b",
    re.I,
)


def _parse_miolo(miolo: str) -> tuple[str, str]:
    """Separa (descrição, unidade) do miolo da âncora, em layouts compactos.

    Em editais que colocam a descrição na própria linha-âncora
    (ex.: ``. 93656 397513 AGULHA DESCARTÁVEL ... CX COM 1000 NÃO``), a
    descrição vem antes do token de unidade e depois dos códigos numéricos
    (CATMAT). Em layouts onde a descrição fica nas linhas vizinhas, o miolo
    é curto (ex.: ``Cx 5 10 20``) e esta função devolve descrição vazia,
    deixando o chamador cair para as linhas de descrição próximas.
    """
    m = re.sub(r"^[.\-\s]+", "", miolo.strip())
    m = re.sub(r"\s+(NÃO|SIM)\s*$", "", m, flags=re.I)  # flag de amostra
    um = _UNIDADE_RE.search(m)
    if um:
        desc = m[: um.start()].strip()
        unidade = um.group(1)
    else:
        desc, unidade = m, ""
    # remove grupos de códigos numéricos iniciais (CATMAT etc.)
    desc = re.sub(r"^(?:\d{3,}\s+){0,3}", "", desc).strip()
    # se o "resto" for basicamente numérico (colunas de qtd), não é descrição
    if desc and len(re.sub(r"[\d\s.,]", "", desc)) < 3:
        desc = ""
    return desc, unidade
    return float(toks[-1].replace(".", ""))


def _coletar_linhas(reader, pagina_inicio: int, pagina_fim: int | None) -> list[str]:
    linhas: list[str] = []
    paginas = list(reader.paginas())
    fim = pagina_fim if pagina_fim is not None else len(paginas)
    for pi in range(pagina_inicio, min(fim, len(paginas))):
        texto = paginas[pi].extract_text() or ""
        for ln in texto.split("\n"):
            linhas.append((ln.strip(), pi + 1))  # guarda a página (rastreabilidade)
    return linhas


def extrair_itens(
    reader,
    pagina_inicio: int = 0,
    pagina_fim: int | None = None,
    janela_descricao: int = 8,
) -> list[ItemEdital]:
    """Extrai os itens do Termo de Referência de forma genérica.

    Args:
        reader: Instância de ``PdfReader`` já aberta.
        pagina_inicio: Índice (0-based) da primeira página a varrer.
        pagina_fim: Índice (0-based, exclusivo) da última. ``None`` = fim.
        janela_descricao: Distância máxima (em linhas) para atribuir uma
            linha de descrição a uma âncora.

    Returns:
        Lista de :class:`ItemEdital`, ordenada por número de item.
    """
    linhas_pag = _coletar_linhas(reader, pagina_inicio, pagina_fim)
    linhas = [lp[0] for lp in linhas_pag]
    paginas = [lp[1] for lp in linhas_pag]

    # 1) âncoras com contagem incremental
    anchors = []  # (idx, num, miolo, vunit, vtot, pagina)
    esperado = 1
    for idx, ln in enumerate(linhas):
        m = _ANCHOR.match(ln)
        if m and int(m.group(1)) == esperado:
            anchors.append(
                (idx, esperado, m.group(2).strip(),
                 _to_float(m.group(3)), _to_float(m.group(4)), paginas[idx])
            )
            esperado += 1

    if not anchors:
        log.warning("Nenhuma âncora de item encontrada nas páginas varridas.")
        return []

    # 2) atribui linhas de descrição à âncora mais próxima (dentro da janela)
    aidx = [a[0] for a in anchors]
    anchor_set = set(aidx)
    desc: dict[int, list[tuple[int, str]]] = {k: [] for k in range(len(anchors))}
    for i, ln in enumerate(linhas):
        if i in anchor_set or not ln or _NOISE.search(ln):
            continue
        melhor, bk = 10**9, None
        for k, ai in enumerate(aidx):
            d = abs(ai - i)
            if d < melhor:
                melhor, bk = d, k
        if bk is not None and melhor <= janela_descricao:
            desc[bk].append((i, ln))

    # 3) monta os itens
    itens: list[ItemEdital] = []
    for k, (idx, num, miolo, vunit, vtot, pagina) in enumerate(anchors):
        # descrição/unidade a partir do próprio miolo (layouts compactos)
        desc_miolo, unid_miolo = _parse_miolo(miolo)

        # descrição das linhas vizinhas (layouts multi-linha)
        partes = [ln for _, ln in sorted(desc[k])]
        desc_vizinhas = normalizar_espacos(" ".join(partes))

        # Preferência: se o miolo já traz uma descrição substancial (layout
        # compacto, 1 item por linha), usa-a isoladamente — nesses editais a
        # descrição não se estende para as linhas vizinhas. Caso contrário
        # (layout multi-linha), usa as linhas de descrição próximas.
        if len(desc_miolo) >= 8:
            texto_desc = desc_miolo
        else:
            texto_desc = desc_vizinhas
        unidade = unid_miolo or _unidade_do_miolo(miolo)

        # quantidade: derivada de total/unit; parse como verificação
        q_parse = _quantidade_parse(miolo)
        q_deriv = None
        if vunit > 0:
            r = vtot / vunit
            if abs(r - round(r)) < 0.01:
                q_deriv = float(round(r))
        quantidade = q_deriv if q_deriv is not None else (q_parse or 0.0)

        itens.append(
            ItemEdital(
                item=num,
                descricao=normalizar_espacos(texto_desc),
                unidade=unidade,
                quantidade=quantidade,
                valor_estimado=vunit,
                valor_total=vtot,
                pagina=pagina,
            )
        )

    log.info("Itens extraídos: %d (âncora genérica)", len(itens))
    return itens


def _unidade_do_miolo(miolo: str) -> str:
    """Tenta identificar a unidade de fornecimento no miolo da âncora.

    Procura um token de unidade comum (Cx, Un, Uni, Pct, Rolo, L, ...). Se
    não encontrar, devolve string vazia — campo de revisão humana.
    """
    tokens = re.findall(r"[A-Za-zÀ-ú]{1,10}", miolo)
    conhecidas = {
        "cx", "un", "uni", "und", "unidade", "pct", "pacote", "rolo",
        "litro", "l", "emb", "frasco", "par", "kg", "g", "ml", "conj",
        "bolsa", "galao", "bomba",
    }
    for t in tokens:
        if t.lower() in conhecidas:
            return t
    return tokens[0] if tokens else ""

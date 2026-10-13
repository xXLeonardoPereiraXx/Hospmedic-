"""Termos críticos destacados na descrição (negrito + vermelho).

Certos detalhes da especificação decidem se o produto cotado serve ou não —
e passam despercebidos no meio de um parágrafo de descrição técnica. Uma luva
"com pó" e uma "sem pó" são produtos diferentes no catálogo; uma seringa
"com dispositivo de segurança" (NR 32) tem outro preço e outro fornecedor.
Cotar errado nesses pontos significa desclassificação ou prejuízo na entrega.

Cada regra tem um **gatilho** (o produto, que determina quando a regra vale) e
os **termos** a destacar. O gatilho evita ruído: "sintética" só interessa em
luva, não numa sonda de material sintético.

Para acrescentar uma regra basta incluir uma entrada nesta lista — nenhum
outro arquivo precisa mudar.
"""
from __future__ import annotations

import re
import unicodedata

# (nome da regra, gatilhos do produto, termos a destacar)
REGRAS: list[tuple[str, list[str], list[str]]] = [
    (
        "Luvas — presença de pó / material",
        ["luva"],
        [
            "com pó", "c/pó", "c/ pó",
            "sem pó", "s/pó", "s/ pó",
            "isenta de pó", "isento de pó",
            "lubrifica",          # pega lubrificada, lubrificante, lubrificado
            "talcada", "talco",
            "sintética", "sintetica",
        ],
    ),
    (
        "Cateter intravenoso periférico — segurança NR 32",
        ["cateter intravenoso periférico", "cateter intravenoso", "abocath"],
        [
            "com dispositivo de segurança", "c/dispositivo de segurança",
            "c/ dispositivo de segurança", "dispositivo de segurança",
            "conforme NR 32", "NR 32", "NR-32",
        ],
    ),
    (
        "Scalp / escalpe — segurança NR 32",
        ["scalpe", "escalpe", "scalp"],
        [
            "com dispositivo de segurança", "c/dispositivo de segurança",
            "c/ dispositivo de segurança", "dispositivo de segurança",
            "conforme NR 32", "NR 32", "NR-32",
        ],
    ),
    (
        "Seringa e agulha — segurança NR 32",
        ["seringa", "agulha"],
        [
            "com dispositivo de segurança", "c/dispositivo de segurança",
            "c/ dispositivo de segurança", "dispositivo de segurança",
            "conforme NR 32", "NR 32", "NR-32",
        ],
    ),
]


def _sem_acento(texto: str) -> str:
    """Remove acentos para comparar 'pó' com 'po' e 'sintética' com 'sintetica'."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _padrao(termos: list[str]) -> re.Pattern:
    """Monta o padrão que casa qualquer um dos termos, ignorando acento e caixa.

    Os termos são ordenados do mais longo para o mais curto para que
    "com dispositivo de segurança" seja destacado inteiro, em vez de o trecho
    menor "dispositivo de segurança" vencer primeiro.
    """
    ordenados = sorted(termos, key=len, reverse=True)
    partes = []
    for termo in ordenados:
        # cada caractere do termo aceita a forma com ou sem acento
        escapado = re.escape(_sem_acento(termo))
        # espaço do termo casa qualquer espaçamento do texto
        escapado = escapado.replace(r"\ ", r"\s+")
        partes.append(escapado)
    return re.compile("(" + "|".join(partes) + ")", re.I)


_GATILHOS = [
    (nome, re.compile("|".join(re.escape(_sem_acento(g)) for g in gatilhos), re.I),
     _padrao(termos))
    for nome, gatilhos, termos in REGRAS
]


def trechos_destacados(descricao: str) -> list[tuple[int, int]]:
    """Posições (início, fim) a destacar na descrição, já unificadas.

    Devolve lista vazia quando nenhuma regra se aplica — o caso comum, em que
    a célula é escrita como texto simples.
    """
    if not descricao:
        return []
    plano = _sem_acento(descricao)

    achados: list[tuple[int, int]] = []
    for _nome, gatilho, termos in _GATILHOS:
        if not gatilho.search(plano):
            continue
        for m in termos.finditer(plano):
            achados.append((m.start(), m.end()))

    if not achados:
        return []

    # Regras diferentes podem marcar o mesmo trecho (ex.: "seringa" e "agulha"
    # na mesma descrição): sobreposições viram um único intervalo.
    achados.sort()
    unidos = [achados[0]]
    for ini, fim in achados[1:]:
        if ini <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fim))
        else:
            unidos.append((ini, fim))
    return unidos

"""Condições comerciais do edital, com evidência textual.

Campos lidos (cada um com valor e trecho do edital):

* validade mínima dos produtos (prazo de validade exigido na entrega);
* prazo de pagamento;
* prazo de entrega;
* vigência da ata de registro de preços (ARP / contrato).

A validade da proposta fica em ``info_edital`` e não é repetida aqui.

Assim como o resto da análise, isto é leitura por padrões de texto: cada
campo sai com o trecho de onde veio, para o conferente validar. Quando nada
bate, o campo sai como "não identificado no edital" — nunca um chute.
"""
from __future__ import annotations

import re

from hbi.utils.text import normalizar_espacos

# Quantidade com o extenso entre parênteses: "30 (trinta) dias".
_NUM = r"(\d{1,4})\s*(?:\([^)]{2,40}\))?"
_UNID = r"(dias?\s+(?:[úu]teis|corridos)|dias?|meses|anos?)"
_FRASE = r"[^.;]{0,%d}?"  # trecho sem fim de frase


def _trecho(texto: str, ini: int, fim: int, folga: int = 60) -> str:
    return "…" + normalizar_espacos(texto[max(0, ini - folga): fim + folga]) + "…"


def _unidade(u: str) -> str:
    u = normalizar_espacos(u).lower()
    if u.startswith("ano"):
        return "ano(s)"
    if u.startswith("mes"):
        return "mês(es)"
    return u.replace("dia", "dia", 1)


def _resultado(valor: str, texto: str, m: re.Match) -> dict:
    return {"valor": valor, "evidencia": _trecho(texto, m.start(), m.end())}


def _primeiro(texto: str, padroes, montar, excluir: re.Pattern | None = None) -> dict:
    """Primeiro padrão que bate (na ordem de preferência) e não cai em
    trecho excluído (ex.: prazo de entrega de amostra)."""
    for pat in padroes:
        for m in pat.finditer(texto):
            if excluir and excluir.search(texto[max(0, m.start() - 40): m.end() + 40]):
                continue
            valor = montar(m)
            if valor:
                return _resultado(valor, texto, m)
    return {}


# ---------------------------------------------------------------- validade
_VALIDADE_PRODUTO = [
    # "prazo de validade ... não inferior a 80% ..." ou "... 24 meses"
    re.compile(r"prazo\s+de\s+validade[^.;]{0,120}?"
               r"(?:n[ãa]o\s+inferior|m[íi]nim[oa]|no\s+m[íi]nimo|igual\s+ou\s+superior|"
               r"maior\s+ou\s+igual|correspondente\s+a)[^.;]{0,80}?"
               r"(\d{1,3})\s*(%|(?:\([^)]{2,40}\))?\s*" + _UNID + r")", re.I),
    # "validade mínima de 12 meses"
    re.compile(r"validade\s+m[íi]nima\s+(?:de\s+|d[ae]\s+)?" + _NUM + r"\s*" + _UNID, re.I),
    # "80% do prazo de validade"
    re.compile(r"(\d{1,3})\s*%\s*(?:\([^)]{2,40}\))?\s*(?:do|de|d[oa]\s+seu)\s+"
               r"(?:prazo\s+(?:total\s+)?de\s+validade)", re.I),
]


def _montar_validade(m: re.Match) -> str:
    if m.re is _VALIDADE_PRODUTO[2]:
        return f"{m.group(1)}% do prazo total de validade"
    if m.re is _VALIDADE_PRODUTO[0]:
        if m.group(2) == "%":
            return f"{m.group(1)}% do prazo total de validade"
        return f"{m.group(1)} {_unidade(m.group(3))}"
    return f"{m.group(1)} {_unidade(m.group(2))}"


# ---------------------------------------------------------------- pagamento
_PAGAMENTO = [
    re.compile(r"pagamento[^.;]{0,160}?(?:em\s+at[ée]|no\s+prazo\s+(?:n[ãa]o\s+superior|"
               r"de\s+at[ée]|m[áa]ximo\s+de|de)|prazo\s+(?:n[ãa]o\s+superior|m[áa]ximo|de))"
               r"[^.;]{0,30}?" + _NUM + r"\s*" + _UNID, re.I),
    re.compile(r"prazo\s+de\s+pagamento[^.;]{0,80}?" + _NUM + r"\s*" + _UNID, re.I),
]


def _montar_pagamento(m: re.Match) -> str:
    return f"{m.group(1)} {_unidade(m.group(2))}"


# ---------------------------------------------------------------- entrega
_EXCL_AMOSTRA = re.compile(r"amostra", re.I)
_EXCL_PROPOSTA = re.compile(r"proposta", re.I)  # validade da proposta não é do produto
_ENTREGA = [
    re.compile(r"prazo\s+(?:para\s+|de\s+)entrega[^.;]{0,120}?" + _NUM + r"\s*" + _UNID, re.I),
    re.compile(r"entrega\s+(?:dos\s+\w+\s+|do\s+objeto\s+|dos\s+bens\s+|dos\s+itens\s+)?"
               r"(?:[ée]\s+de\s+|ser[áa]\s+|dever[áa]\s+ocorrer\s+em\s+|n[ãa]o\s+dever[áa]\s+"
               r"ultrapassar\s+|em\s+at[ée]\s+|no\s+m[áa]ximo\s+(?:de\s+)?)"
               + _NUM + r"\s*" + _UNID, re.I),
]


def _montar_entrega(m: re.Match) -> str:
    return f"{m.group(1)} {_unidade(m.group(2))}"


# ---------------------------------------------------------------- vigência ARP
_VIGENCIA = [
    re.compile(r"(?:vig[êe]ncia|validade)\s+(?:da|do|d[ae]s)\s+(?:ata|registro|"
               r"ARP|contrato)[^.;]{0,100}?" + _NUM + r"\s*" + _UNID, re.I),
    re.compile(r"(?:ata|registro\s+de\s+pre[çc]os|ARP)[^.;]{0,120}?"
               r"(?:vig[êe]ncia|validade)[^.;]{0,80}?" + _NUM + r"\s*" + _UNID, re.I),
]


def _montar_vigencia(m: re.Match) -> str:
    return f"{m.group(1)} {_unidade(m.group(2))}"


def extrair(texto: str) -> dict:
    """Retorna os campos de condições comerciais; ausente = ``{}``."""
    if not texto:
        return {}
    return {
        "validade_produtos": _primeiro(texto, _VALIDADE_PRODUTO, _montar_validade,
                                       excluir=_EXCL_PROPOSTA),
        "prazo_pagamento": _primeiro(texto, _PAGAMENTO, _montar_pagamento),
        "prazo_entrega": _primeiro(texto, _ENTREGA, _montar_entrega, excluir=_EXCL_AMOSTRA),
        "vigencia_arp": _primeiro(texto, _VIGENCIA, _montar_vigencia),
    }

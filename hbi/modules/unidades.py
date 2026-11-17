"""Whitelist de unidades de fornecimento e limpeza do campo de unidade.

A leitura por texto precisa adivinhar qual palavra é a unidade, e erra de
três jeitos: letras espaçadas pelo PDF ("UN D", "PC T", "ME TR O"), nome do
produto tomado por unidade ("Luva", "Bota") e unidade vazia. Esta lista diz
o que é unidade de verdade; o resto é tratado como suspeito.

Regras (nesta ordem, cada uma só age quando o resultado é unidade da lista):

1. letras espaçadas: tirar os espaços ("RO L" -> "ROL");
2. unidade fora da lista: procurar na descrição a quantidade do item seguida
   de uma unidade da lista ("340,0 PA") — é a coluna de unidade que a leitura
   por texto juntou à descrição.

Nenhuma regra inventa unidade: sem evidência, o campo fica como veio, e
``suspeita`` diz que precisa de conferência.
"""
from __future__ import annotations

import re

# Formas aceitas (sem ponto final, em maiúsculas, sem acento opcional).
_LISTA = r"""
UN UND UNID UNI UNIDADE UNIDADES UM U
CX CAIXA CAIXAS CXA
PCT PCTE PC PCS PACOTE PACOTES PAC
FR FRS FRC FRASCO FRASCOS FA FRA FRASCO-AMPOLA
AMP AMPOLA AMPOLAS
RL ROL ROLO ROLOS BOB BOBINA BOBINAS
L LT LTS LITRO LITROS ML G GR KG MG
M MT MTS METRO METROS M2 M3 CM
PAR PARES PA PR JOGO JOGOS JG
KIT KITS CONJ CONJUNTO CONJUNTOS CJ CONJU
GL GALAO GALOES BOMBONA BB
BOLSA BOLSAS BL BLOCO
TB TUBO TUBOS BISNAGA BISNAGAS BG
EMB EMBALAGEM EMBALAGENS ENV ENVELOPE ENVELOPES
SACHE SACHES SC SACO SACOS FD FARDO FARDOS
CR CARTELA CARTELAS BLISTER
DZ DUZIA DUZIAS CENTO MILHEIRO MIL
PECA PECAS PC PÇ
POTE POTES LATA LATAS BALDE BALDES TAMBOR
RESMA RESMAS FOLHA FOLHAS
SER SERINGA SERINGAS
CP COMPRIMIDO COMPRIMIDOS CAPSULA CAPSULAS
SV SERVICO SERVICOS
CAI CAIX
"""
_UNIDADES = set(_LISTA.split())

_SEM_ACENTO = str.maketrans("ÁÀÂÃÉÊÍÓÔÕÚÇ", "AAAAEEIOOOUC")


def _chave(u: str) -> str:
    return u.upper().translate(_SEM_ACENTO).strip().rstrip(".").replace(" ", "")


def eh_unidade(u: str) -> bool:
    """Unidade da lista? Aceita a primeira palavra ("PCT 100 UN.", "GALÃO 5L")."""
    if not u or not u.strip():
        return False
    primeira = u.strip().split()[0]
    return _chave(primeira) in _UNIDADES or _chave(u) in _UNIDADES


def juntar_letras(u: str) -> str:
    """'UN D' -> 'UND', 'ME TR O' -> 'METRO' — só quando vira unidade da lista."""
    if not u or " " not in u.strip():
        return u
    partes = u.strip().split()
    if not all(re.fullmatch(r"[A-Za-zÀ-ú.]+", p) for p in partes):
        return u          # "PCT 100 UN." é unidade com conteúdo, não letras espaçadas
    junto = "".join(partes)
    if _chave(junto) in _UNIDADES:
        return junto
    return u


def _num(t: str) -> float | None:
    t = t.strip()
    try:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
            return float(t.replace(".", ""))
        return float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None


_QTD_UND = re.compile(r"(?<![\d.,])(\d[\d.,]*)\s+([A-Za-zÀ-ú]{1,10})\.?(?![A-Za-zÀ-ú])")


# Medidas: depois de um número na descrição são capacidade/tamanho ("CAP 160
# ML", "500 G"), não a unidade de fornecimento — nunca vêm da descrição.
_MEDIDAS = {"L", "LT", "LTS", "LITRO", "LITROS", "ML", "G", "GR", "KG", "MG",
            "M", "MT", "MTS", "METRO", "METROS", "M2", "M3", "CM", "U", "UM", "MIL"}


def eh_medida(u: str) -> bool:
    """ML, L, G, KG, M, CM...: pode ser medida da descrição, não da coluna."""
    return _chave(u) in _MEDIDAS


def da_descricao(descricao: str, quantidade: float) -> str:
    """Unidade que a leitura por texto deixou na descrição: '340,0 PA' com qtd 340."""
    for m in _QTD_UND.finditer(descricao or ""):
        q = _num(m.group(1))
        chave = _chave(m.group(2))
        if (q is not None and abs(q - quantidade) < 0.01 and chave in _UNIDADES
                and chave not in _MEDIDAS):
            return m.group(2)
    return ""


def corrigir(itens) -> int:
    """Aplica as regras da whitelist aos itens; devolve quantos mudaram."""
    mudou = 0
    for it in itens:
        antes = it.unidade or ""
        u = juntar_letras(antes)
        if not eh_unidade(u):
            achada = da_descricao(it.descricao, it.quantidade)
            if achada:
                u = achada
        if u != antes:
            it.unidade = u
            mudou += 1
    return mudou


def suspeitas(itens) -> list[int]:
    """Itens cuja unidade está vazia ou fora da lista (para conferência)."""
    return [it.item for it in itens if not eh_unidade(it.unidade or "")]

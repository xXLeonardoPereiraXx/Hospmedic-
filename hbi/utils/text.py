"""Utilitários de texto e conversão de números no padrão brasileiro."""
from __future__ import annotations

import re


def normalizar_espacos(texto: str) -> str:
    """Colapsa espaços/quebras de linha em um único espaço e apara as bordas."""
    return re.sub(r"\s+", " ", texto or "").strip()


def brl_para_float(valor: str) -> float:
    """Converte um número no formato brasileiro (``"1.256,00"``) para float.

    Args:
        valor: Texto numérico com ponto de milhar e vírgula decimal.

    Returns:
        O valor como ``float``.

    Raises:
        ValueError: Se ``valor`` não contiver dígitos.
    """
    limpo = re.sub(r"[^\d,.-]", "", valor or "")
    if not re.search(r"\d", limpo):
        raise ValueError(f"valor não numérico: {valor!r}")
    limpo = limpo.replace(".", "").replace(",", ".")
    return float(limpo)


def float_para_brl(valor: float) -> str:
    """Formata um float como moeda brasileira sem símbolo (``"1.256,00"``)."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def eh_inteiro_texto(texto: str) -> bool:
    """Indica se o texto representa um inteiro (ignorando pontos de milhar)."""
    t = (texto or "").replace(".", "").strip()
    return t.isdigit()

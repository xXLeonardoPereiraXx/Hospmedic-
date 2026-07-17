"""Configuração de logging do HBI.

Um logger simples de console + arquivo, para dar rastreabilidade ao
pipeline sem introduzir dependências externas.
"""
from __future__ import annotations

import logging
from pathlib import Path

from hbi.config import settings

_CONFIGURADO = False


def get_logger(nome: str = "hbi") -> logging.Logger:
    """Retorna um logger configurado (idempotente).

    Args:
        nome: Nome do logger, tipicamente ``__name__`` do módulo chamador.

    Returns:
        Instância de :class:`logging.Logger` pronta para uso.
    """
    global _CONFIGURADO
    logger = logging.getLogger(nome)
    if _CONFIGURADO:
        return logger

    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    arquivo = logging.FileHandler(
        Path(settings.LOG_DIR) / "hbi.log", encoding="utf-8"
    )
    arquivo.setFormatter(fmt)

    root = logging.getLogger("hbi")
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(arquivo)
    root.propagate = False

    _CONFIGURADO = True
    return logger

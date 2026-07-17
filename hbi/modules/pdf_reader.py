"""Módulo ``pdf_reader``: leitura de baixo nível do edital em PDF.

Responsabilidade única: abrir o PDF e expor seu conteúdo (texto integral e
objetos de página do pdfplumber) para os demais módulos. Não interpreta
tabelas nem regras — apenas lê.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pdfplumber

from hbi.utils.logger import get_logger

log = get_logger(__name__)


class PdfReader:
    """Encapsula o acesso ao PDF do edital.

    Uso típico::

        with PdfReader(caminho) as leitor:
            texto = leitor.texto_completo()
            for pagina in leitor.paginas():
                ...
    """

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)
        if not self.caminho.exists():
            raise FileNotFoundError(f"PDF não encontrado: {self.caminho}")
        self._pdf: pdfplumber.PDF | None = None

    def __enter__(self) -> "PdfReader":
        self._pdf = pdfplumber.open(self.caminho)
        log.info("PDF aberto: %s (%d páginas)", self.caminho.name, len(self._pdf.pages))
        return self

    def __exit__(self, *exc) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None

    @property
    def _doc(self) -> pdfplumber.PDF:
        if self._pdf is None:
            raise RuntimeError("PdfReader deve ser usado dentro de um bloco 'with'.")
        return self._pdf

    def num_paginas(self) -> int:
        """Número de páginas do documento."""
        return len(self._doc.pages)

    def paginas(self) -> Iterator["pdfplumber.page.Page"]:
        """Itera sobre as páginas do PDF."""
        yield from self._doc.pages

    def texto_completo(self, limite_paginas: int | None = None) -> str:
        """Concatena o texto de todas as páginas (ou das ``limite_paginas`` primeiras).

        Args:
            limite_paginas: Se informado, lê apenas as N primeiras páginas —
                útil para validação de critérios, que ficam no início do edital.
        """
        paginas = self._doc.pages
        if limite_paginas is not None:
            paginas = paginas[:limite_paginas]
        partes = [(p.extract_text() or "") for p in paginas]
        return "\n".join(partes)

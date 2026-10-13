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

from hbi.utils.cancelamento import AnaliseCancelada  # noqa: E402

log = get_logger(__name__)


def sem_marca_dagua(pagina):
    """Devolve a página sem os caracteres da marca d'água (carimbo rotacionado).

    Editais publicados por portais de protocolo (ex.: FEAS/Curitiba) trazem um
    carimbo diagonal sobre todas as páginas. O extrator de texto intercala
    esses caracteres com o conteúdo real, partindo palavras no meio
    (``"para que ha" + "j a3 melhor ajuste"``) e inserindo linhas de 1–2
    caracteres — o que inviabiliza tanto a leitura das descrições quanto o
    casamento das âncoras.

    O carimbo se distingue por estar **rotacionado**: sua matriz de
    transformação tem o termo de inclinação não nulo, enquanto o texto normal
    tem exatamente zero. Filtrar por essa propriedade remove o carimbo sem
    tocar em nenhum caractere do corpo do documento.
    """
    return pagina.filter(
        lambda o: o.get("object_type") != "char"
        or abs(o.get("matrix", (1, 0, 0, 1, 0, 0))[1]) < 0.01
    )


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

    def paginas_indexadas(self, inicio: int = 0, fim: int | None = None):
        """Itera as páginas do intervalo **sem materializar a lista inteira**.

        Cada página do pdfplumber carrega seus objetos sob demanda e os mantém
        em cache. Guardar todas as páginas numa lista faz o consumo de memória
        crescer com o tamanho do documento; percorrer uma a uma (e liberar o
        cache depois de usar) mantém o pico baixo e constante — o que permite
        rodar editais de centenas de páginas em instâncias pequenas.
        """
        paginas = self._doc.pages
        ultimo = len(paginas) if fim is None else min(fim, len(paginas))
        for i in range(inicio, ultimo):
            yield paginas[i]

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

        Usa pdfplumber (preciso, porém mais lento). Para a validação de
        critérios — que só faz busca textual — prefira ``texto_rapido``.

        Args:
            limite_paginas: Se informado, lê apenas as N primeiras páginas.
        """
        paginas = self._doc.pages
        if limite_paginas is not None:
            paginas = paginas[:limite_paginas]
        partes = [(p.extract_text() or "") for p in paginas]
        return "\n".join(partes)

    def texto_rapido(self, limite_paginas: int | None = None) -> str:
        """Extrai o texto do documento inteiro com pypdf — bem mais rápido.

        A validação de critérios varre todo o edital (a habilitação costuma
        ficar no meio/fim), então a velocidade importa: o pypdf é ~4x mais
        rápido que o pdfplumber para extração puramente textual, com cobertura
        equivalente para busca de termos. Não use quando precisar de
        posicionamento/coordenadas — para isso, ``texto_completo``/``paginas``.
        """
        from pypdf import PdfReader as _PyPdf

        try:
            leitor = _PyPdf(str(self.caminho))
            paginas = leitor.pages
            if limite_paginas is not None:
                paginas = paginas[:limite_paginas]
            from hbi.utils import cancelamento

            partes = []
            for pg in paginas:
                cancelamento.checar()  # ponto seguro: troca de página
                partes.append(pg.extract_text() or "")
            bruto = "\n".join(partes)
            # O pypdf frequentemente fragmenta o texto, colocando cada palavra
            # (ou o espaço entre elas) em sua própria linha:
            #   "Atestado\n \nde\n \ncapacidade\n \ntécnica"
            # Isso quebraria tanto as buscas por termo quanto as regras que
            # usam [^\n] para limitar proximidade. A normalização abaixo
            # reconstrói o fluxo do texto:
            import re as _re

            t = bruto
            # 1) remove linhas que contêm só espaços (separadores do pypdf)
            t = _re.sub(r"\n[ \t]*\n", "\n", t)
            # 2) junta quebras que caem no meio de uma frase — quando a linha
            #    seguinte começa com minúscula/dígito, era continuação de texto
            t = _re.sub(r"\n(?=[a-zà-ú0-9])", " ", t)
            # 3) colapsa espaços/tabs repetidos
            t = _re.sub(r"[ \t]+", " ", t)
            return t
        except AnaliseCancelada:
            # Cancelamento não é falha de leitura: precisa subir, senão o
            # pedido do usuário seria engolido e — pior — o fallback abaixo
            # recomeçaria o trabalho com o extrator lento.
            raise
        except Exception as exc:  # noqa: BLE001
            # Em caso de PDF problemático, cai para o extrator preciso.
            log.warning("texto_rapido falhou (%s); usando pdfplumber.", exc)
            return self.texto_completo(limite_paginas)

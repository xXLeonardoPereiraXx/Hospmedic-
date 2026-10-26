"""Serviço de orquestração do pipeline HBI (fluxo TO-BE).

Encadeia os módulos independentes na ordem do fluxo desejado:

    seleção do PDF -> leitura -> validação -> extração -> organização
    -> preenchimento -> (revisão humana)

A revisão humana permanece fora do pipeline automatizado, por design.
"""
from __future__ import annotations

from pathlib import Path

from hbi.config import settings
from hbi.models.edital import Edital
from hbi.modules import info_edital
from hbi.modules import (
    edital_validator, excel_exporter, spec_extractor, table_extractor,
)
from hbi.modules.pdf_reader import PdfReader
from hbi.utils.logger import get_logger

log = get_logger(__name__)

# Páginas iniciais que concentram as regras de participação do edital.
# A validação de critérios varre o documento inteiro: os documentos de
# habilitação (regularidade fiscal, econômico-financeira, declarações) costumam
# ficar no meio ou no fim do edital, não no preâmbulo. Ler só as primeiras
# páginas gerava falsos "ausente". None = sem limite.
PAGINAS_VALIDACAO = None


def processar_edital(
    caminho_pdf: str | Path,
    destino_xlsx: str | Path | None = None,
    nome_original: str | None = None,
) -> Edital:
    """Executa o pipeline completo para um edital em PDF.

    Args:
        caminho_pdf: Caminho do edital.
        destino_xlsx: Caminho de saída da planilha. Se ``None``, grava em
            ``data/output/<nome_do_pdf>.xlsx``.

    Returns:
        O :class:`Edital` populado (itens + validação), já exportado.
    """
    caminho_pdf = Path(caminho_pdf)
    log.info("Processando edital: %s", caminho_pdf.name)

    with PdfReader(caminho_pdf) as leitor:
        # 1) Validação de critérios (usa apenas as páginas iniciais).
        texto_ini = leitor.texto_rapido(limite_paginas=PAGINAS_VALIDACAO)
        metadados = edital_validator.detectar_metadados(texto_ini)
        validacao = edital_validator.validar(texto_ini)
        info = info_edital.extrair_informacoes(
            texto_ini, nome_original or caminho_pdf.name, metadados["orgao"],
            metadados["numero_pregao"])

        # 2) Extração da tabela de itens (varre o documento inteiro; as
        #    âncoras numéricas se autoidentificam, sem depender de páginas fixas).
        itens, extras_grade = table_extractor.melhor_extracao(leitor, caminho_pdf)

        # 3) Descritivos técnicos completos, quando o edital os mantém em
        #    seção separada da tabela (padrão SESA/Curitiba). O join usa lote
        #    ou número do item, conforme a indexação do próprio documento.
        tipo_chave, descritivos = spec_extractor.extrair_descritivos(texto_ini)
        diag_descritivos = spec_extractor.aplicar_descritivos(
            itens, tipo_chave, descritivos
        )

    edital = Edital(
        origem=str(caminho_pdf),
        orgao=metadados["orgao"],
        numero_pregao=metadados["numero_pregao"],
        valor_total_estimado=metadados["valor_total_estimado"],
        valores_declarados=metadados.get("valores_declarados", []),
        itens=itens,
        validacao=validacao,
        info=info,
    )
    edital.diagnostico_descritivos = diag_descritivos

    # 4) Preenchimento da planilha padrão.
    if destino_xlsx is None:
        destino_xlsx = settings.OUTPUT_DIR / (caminho_pdf.stem + ".xlsx")
    excel_exporter.exportar(edital, destino_xlsx)

    return edital


def validar_edital(caminho_pdf: str | Path, nome_original: str | None = None) -> Edital:
    """Executa **apenas** a validação de critérios (GO/NO-GO), sem extrair
    itens nem gerar planilha.

    Útil para uma triagem rápida: decidir se vale a pena seguir com a
    análise completa do edital.

    Args:
        caminho_pdf: Caminho do edital.

    Returns:
        Um :class:`Edital` preenchido apenas com metadados e validação
        (``itens`` vazio).
    """
    caminho_pdf = Path(caminho_pdf)
    log.info("Validando edital (somente critérios): %s", caminho_pdf.name)

    with PdfReader(caminho_pdf) as leitor:
        texto_ini = leitor.texto_rapido(limite_paginas=PAGINAS_VALIDACAO)
        metadados = edital_validator.detectar_metadados(texto_ini)
        validacao = edital_validator.validar(texto_ini)
        info = info_edital.extrair_informacoes(
            texto_ini, nome_original or caminho_pdf.name, metadados["orgao"],
            metadados["numero_pregao"])

    return Edital(
        origem=str(caminho_pdf),
        orgao=metadados["orgao"],
        numero_pregao=metadados["numero_pregao"],
        valor_total_estimado=metadados["valor_total_estimado"],
        valores_declarados=metadados.get("valores_declarados", []),
        itens=[],
        validacao=validacao,
        info=info,
    )

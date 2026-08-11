"""Módulo ``excel_exporter``: preenchimento da planilha padrão da HospMedic.

Carrega a planilha-modelo (``TEMPLATE_XLSX``), que já traz as fórmulas de
custo/lance/total pré-montadas, e escreve os dados extraídos **apenas** nas
colunas de entrada (Descrição, Unidade, Quantidade, Estimado Edital),
preservando as fórmulas existentes — princípio de "preservar templates".

Acrescenta ainda uma coluna **Confere** (conferência automática de
``qtd × valor == total``) para apoiar a revisão humana, que permanece como
etapa final do fluxo.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

from hbi.config import settings
from hbi.models.edital import Edital
from hbi.utils.logger import get_logger

log = get_logger(__name__)


def _mapa_colunas(ws) -> dict[str, int]:
    """Lê o cabeçalho e devolve ``{rótulo: índice_de_coluna}``."""
    linha = settings.PLANILHA_LINHA_CABECALHO
    mapa: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=linha, column=col).value
        if val is not None:
            mapa[str(val).strip()] = col
    return mapa


def exportar(edital: Edital, destino: str | Path) -> Path:
    """Preenche a planilha-modelo com os itens do edital e salva em ``destino``.

    Args:
        edital: Edital já extraído e validado.
        destino: Caminho de saída do ``.xlsx``.

    Returns:
        O :class:`~pathlib.Path` do arquivo gerado.
    """
    destino = Path(destino)
    wb = load_workbook(settings.TEMPLATE_XLSX)
    ws = wb[settings.PLANILHA_ABA]
    rotulo_para_col = _mapa_colunas(ws)

    # Resolve as colunas de entrada a partir do mapa de configuração.
    col_idx = {}
    for rotulo, campo in settings.PLANILHA_MAPA_COLUNAS.items():
        if rotulo in rotulo_para_col:
            col_idx[campo] = rotulo_para_col[rotulo]
        else:
            log.warning("Coluna '%s' ausente na planilha-modelo.", rotulo)

    # Coluna extra de conferência, ancorada logo após a última coluna do
    # cabeçalho real (evita o max_column inflado que o modelo .ods carrega).
    col_confere = max(rotulo_para_col.values()) + 1
    cab = settings.PLANILHA_LINHA_CABECALHO
    ws.cell(row=cab, column=col_confere, value="Confere")
    ws.cell(row=cab, column=col_confere).font = Font(bold=True)

    # Em editais organizados por lote, a disputa acontece por lote — o número
    # precisa ficar visível para quem vai lançar a proposta.
    usa_lotes = any(it.lote is not None for it in edital.itens)
    col_lote = col_confere + 1 if usa_lotes else None
    if col_lote:
        ws.cell(row=cab, column=col_lote, value="Lote")
        ws.cell(row=cab, column=col_lote).font = Font(bold=True)

    # Limpa qualquer conteúdo residual do modelo abaixo do cabeçalho
    # (o modelo vem com fórmulas/totais pré-montados para ~185 itens; vamos
    # regravá-los conforme a quantidade real de itens deste edital).
    primeira_dados = settings.PLANILHA_PRIMEIRA_LINHA_DADOS
    for r in range(primeira_dados, ws.max_row + 1):
        for c in range(1, max(rotulo_para_col.values()) + 2):
            ws.cell(row=r, column=c).value = None

    linha = primeira_dados

    # Índices das colunas de fórmula/defaults da planilha-modelo (por rótulo).
    c_icms = rotulo_para_col.get("ICMS")
    c_frete = rotulo_para_col.get("Frete")
    c_margem = rotulo_para_col.get("Margem")
    c_lance = rotulo_para_col.get("Lance Minimo")
    c_total = rotulo_para_col.get("Total ") or rotulo_para_col.get("Total")
    c_total_ed = rotulo_para_col.get("Total Edital")
    c_h = rotulo_para_col.get("Quantidade")
    c_i = rotulo_para_col.get("Custo")
    c_o = rotulo_para_col.get("Estimado Edital")

    def col_letter(idx: int) -> str:
        from openpyxl.utils import get_column_letter
        return get_column_letter(idx)

    primeira = linha
    alerta = PatternFill("solid", start_color="FFF2CC")  # amarelo suave
    for it in edital.itens:
        # dados de entrada
        for campo, col in col_idx.items():
            ws.cell(row=linha, column=col, value=getattr(it, campo))
        # zera defaults numéricos que alimentam as fórmulas (se ainda vazios)
        for c in (c_icms, c_frete, c_margem):
            if c and ws.cell(row=linha, column=c).value is None:
                ws.cell(row=linha, column=c, value=0)
        # garante as fórmulas da linha (replicando o padrão do modelo)
        if c_lance and c_i:
            ws.cell(row=linha, column=c_lance,
                    value=f"=SUM({col_letter(c_icms)}{linha}:{col_letter(c_margem)}{linha})"
                          f"*{col_letter(c_i)}{linha}+{col_letter(c_i)}{linha}")
        if c_total and c_lance and c_h:
            ws.cell(row=linha, column=c_total,
                    value=f"={col_letter(c_lance)}{linha}*{col_letter(c_h)}{linha}")
        if c_total_ed and c_o and c_h:
            ws.cell(row=linha, column=c_total_ed,
                    value=f"=({col_letter(c_o)}{linha}*{col_letter(c_h)}{linha})")

        confere = "OK" if it.confere_total(settings.TOLERANCIA_TOTAL) else "REVISAR"
        cel = ws.cell(row=linha, column=col_confere, value=confere)
        if confere != "OK":
            cel.fill = alerta
        if col_lote and it.lote is not None:
            ws.cell(row=linha, column=col_lote, value=it.lote)
        linha += 1

    ultima = linha - 1
    # Linha de totais logo após o último item (com um espaçamento de 1 linha).
    linha_tot = linha + 1
    if c_total:
        ws.cell(row=linha_tot, column=c_total - 1, value="TOTAL")
        ws.cell(row=linha_tot, column=c_total - 1).font = Font(bold=True)
        ws.cell(row=linha_tot, column=c_total,
                value=f"=SUM({col_letter(c_total)}{primeira}:{col_letter(c_total)}{ultima})")
        ws.cell(row=linha_tot, column=c_total).font = Font(bold=True)
    if c_total_ed:
        ws.cell(row=linha_tot, column=c_total_ed,
                value=f"=SUM({col_letter(c_total_ed)}{primeira}:{col_letter(c_total_ed)}{ultima})")
        ws.cell(row=linha_tot, column=c_total_ed).font = Font(bold=True)

    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    log.info("Planilha gerada: %s (%d itens)", destino.name, len(edital.itens))
    return destino

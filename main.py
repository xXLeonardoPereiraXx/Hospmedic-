"""Ponto de entrada (CLI) do HBI.

Uso:
    # pipeline completo (validação + extração + planilha)
    python main.py <edital.pdf> [--out saida.xlsx] [--relatorio rel.txt]

    # somente validação de critérios (GO/NO-GO), sem extrair itens
    python main.py <edital.pdf> --somente-validacao [--relatorio rel.txt]

Executa o pipeline e imprime o relatório de validação (GO/NO-GO) para
apoiar a revisão humana.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hbi.config import settings
from hbi.services import pipeline, report
from hbi.utils.logger import get_logger

log = get_logger("hbi.main")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hbi",
        description="HospMedic Bid Intelligence — análise automática de editais.",
    )
    parser.add_argument("pdf", help="Caminho do edital em PDF.")
    parser.add_argument("--out", help="Caminho da planilha de saída (.xlsx).")
    parser.add_argument(
        "--relatorio",
        help="Caminho para salvar o relatório em .txt (opcional).",
    )
    parser.add_argument(
        "--somente-validacao",
        action="store_true",
        help="Roda apenas a validação de critérios (GO/NO-GO), sem extrair "
             "itens nem gerar planilha.",
    )
    args = parser.parse_args(argv)

    pdf = Path(args.pdf)
    if not pdf.exists():
        log.error("PDF não encontrado: %s", pdf)
        return 2

    # --- Modo somente validação ---------------------------------------------
    if args.somente_validacao:
        edital = pipeline.validar_edital(pdf)
        texto = report.montar_relatorio_validacao(edital)
        print("\n" + texto)
        if args.relatorio:
            caminho = report.salvar_relatorio_validacao(edital, args.relatorio)
            log.info("Relatório de validação salvo em: %s", caminho)
        return 0

    # --- Pipeline completo ---------------------------------------------------
    destino = Path(args.out) if args.out else settings.OUTPUT_DIR / (pdf.stem + ".xlsx")
    edital = pipeline.processar_edital(pdf, destino)

    texto = report.montar_relatorio(edital)
    print("\n" + texto)

    if args.relatorio:
        caminho = report.salvar_relatorio(edital, args.relatorio)
        log.info("Relatório salvo em: %s", caminho)

    print(f"\nPlanilha preenchida: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

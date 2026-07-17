"""Módulos independentes do HBI (cada um com responsabilidade única)."""
from hbi.modules import edital_validator, excel_exporter, pdf_reader, table_extractor

__all__ = ["edital_validator", "excel_exporter", "pdf_reader", "table_extractor"]

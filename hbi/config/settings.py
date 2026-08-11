"""Configuração central do HBI.

Concentra caminhos, constantes de layout de tabela e regras de validação,
de modo que a lógica dos módulos permaneça livre de valores mágicos.
Sem banco de dados no MVP — tudo é arquivo/estrutura em memória.
"""
from __future__ import annotations

from pathlib import Path

# --- Caminhos base -----------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

# Planilha modelo da HospMedic (layout de saída padrão).
TEMPLATE_XLSX = DATA_DIR / "Modelo_de_Planilha_de_Licitacao.xlsx"

# Tolerância (R$) na conferência quantidade × valor unitário == valor total.
TOLERANCIA_TOTAL = 0.5

# --- Mapeamento das colunas da planilha modelo -------------------------------
# A planilha da HospMedic tem cabeçalho na linha 3 e dados a partir da linha 4.
PLANILHA_ABA = "Planilha1"
PLANILHA_LINHA_CABECALHO = 3
PLANILHA_PRIMEIRA_LINHA_DADOS = 4
# Nome da coluna (cabeçalho) -> campo do ItemEdital que a preenche.
PLANILHA_MAPA_COLUNAS = {
    "Item": "item",
    "Descrição Edital": "descricao",
    "Unidade": "unidade",
    "Quantidade": "quantidade",
    "Estimado Edital": "valor_estimado",
}

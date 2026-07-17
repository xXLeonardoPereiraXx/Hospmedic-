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

# --- Layout da tabela de itens (extração por coordenadas) --------------------
# Fronteiras horizontais das colunas, em pontos PDF. Derivadas dos retângulos
# de célula do Termo de Referência (padrão de editais no formato usado).
# Ordem: item | descrição | unidade | quantidade | valor unit. | valor total.
COLUNAS_X = [46, 71, 363, 413, 451, 511, 563]
COLUNAS_NOMES = ["item", "desc", "unid", "qtde", "media", "total"]

# Número máximo plausível de itens (filtra falsos-positivos de dígitos soltos).
MAX_ITEM = 250

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

# --- Regras de validação GO/NO-GO --------------------------------------------
# Cada regra: (nome, padrão_regex, impacto). Impacto:
#   "no_go"   -> se presente, tende a bloquear a participação da HospMedic;
#   "atencao" -> exige análise/documento; entra como ponto de revisão humana;
#   "go"      -> sinal esperado/favorável de um edital compatível.
# A HospMedic é distribuidora de produtos hospitalares; as regras refletem
# os documentos do "Espelho de Documentos" que ela consegue (ou não) atender.
REGRAS_VALIDACAO = [
    (
        "Exclusiva ME/EPP",
        r"exclusiv[ao][^.]{0,60}(me/epp|microempresa|empresa de pequeno porte|epp)",
        "atencao",
    ),
    ("Exige AFE (ANVISA)", r"\bAFE\b|autoriza[çc][ãa]o de funcionamento", "atencao"),
    (
        "Exige Atestado de Capacidade Técnica",
        r"atestado de capacidade t[ée]cnica",
        "atencao",
    ),
    ("Exige registro de produtos na ANVISA", r"registro[^.]{0,30}anvisa", "atencao"),
    ("Exige Licença Sanitária", r"licen[çc]a sanit[áa]ria|vigil[âa]ncia sanit[áa]ria", "atencao"),
    ("Exige SICAF", r"\bSICAF\b", "atencao"),
    ("Exige amostras", r"\bamostra", "atencao"),
    ("Menor preço por item", r"menor pre[çc]o por item", "go"),
    ("Modo de disputa aberto", r"modo de disputa[^.]{0,20}aberto", "go"),
]

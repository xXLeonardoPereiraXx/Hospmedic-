"""Módulo ``edital_validator``: validação de critérios de participação.

Aplica as regras de ``settings.REGRAS_VALIDACAO`` sobre o texto do edital e
produz um veredito **GO / NO-GO / REVISAR**, com a evidência textual de cada
critério (rastreabilidade). As regras derivam do "Espelho de Documentos de
Licitação Hospitalar" — os documentos e exigências que definem se a HospMedic
consegue participar de um certame.

Filosofia (documento mestre): o sistema sinaliza; a decisão final é humana.
Por isso o veredito padrão para exigências detectadas é *revisar*, e não uma
recusa automática.
"""
from __future__ import annotations

import re

from hbi.config import settings
from hbi.models.edital import CriterioValidacao, ResultadoValidacao
from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)


def _evidencia(texto: str, match: re.Match) -> str:
    """Retorna um trecho curto ao redor do match, para rastreabilidade."""
    ini = max(0, match.start() - 40)
    fim = min(len(texto), match.end() + 40)
    return normalizar_espacos(texto[ini:fim])


def validar(texto_edital: str) -> ResultadoValidacao:
    """Avalia os critérios de participação e devolve o veredito.

    Args:
        texto_edital: Texto integral (ou das primeiras páginas) do edital.

    Returns:
        :class:`ResultadoValidacao` com todos os critérios e o veredito.
    """
    criterios: list[CriterioValidacao] = []
    for nome, padrao, impacto in settings.REGRAS_VALIDACAO:
        m = re.search(padrao, texto_edital, re.IGNORECASE)
        criterios.append(
            CriterioValidacao(
                nome=nome,
                presente=bool(m),
                impacto=impacto,
                evidencia=_evidencia(texto_edital, m) if m else "",
            )
        )

    impeditivos = [c for c in criterios if c.impacto == "no_go" and c.presente]
    atencoes = [c for c in criterios if c.impacto == "atencao" and c.presente]

    if impeditivos:
        veredito = "no_go"
        justificativa = "Critério(s) impeditivo(s): " + ", ".join(
            c.nome for c in impeditivos
        )
    elif atencoes:
        veredito = "revisar"
        justificativa = (
            "Sem impeditivo automático, mas há exigências que precisam de "
            "conferência documental: " + ", ".join(c.nome for c in atencoes)
        )
    else:
        veredito = "go"
        justificativa = "Nenhuma exigência crítica detectada no texto analisado."

    resultado = ResultadoValidacao(
        criterios=criterios, veredito=veredito, justificativa=justificativa
    )
    log.info("Validação: veredito=%s (%d critérios)", veredito, len(criterios))
    return resultado


# --- Extração de metadados do edital ----------------------------------------

def detectar_metadados(texto_edital: str) -> dict:
    """Extrai metadados básicos (órgão, número do pregão, valor global).

    Retorna um dicionário com chaves ``orgao``, ``numero_pregao`` e
    ``valor_total_estimado`` (qualquer uma pode ser ``None``).
    """
    dados: dict[str, object] = {
        "orgao": None,
        "numero_pregao": None,
        "valor_total_estimado": None,
    }

    m_orgao = re.search(
        r"(?:MUNIC[ÍI]PIO|PREFEITURA MUNICIPAL)\s+DE\s+"
        r"([A-ZÀ-Ú][A-ZÀ-Ú\s\-]{2,40})",
        texto_edital,
    )
    if m_orgao:
        dados["orgao"] = normalizar_espacos(m_orgao.group(1)).title()

    m_preg = re.search(
        r"PREG[ÃA]O\s*\(?ELETR[ÔO]NICO\)?\s*(?:SRP\s*)?N[º°]?\s*([\d]+/\d{4})",
        texto_edital,
        re.IGNORECASE,
    )
    if m_preg:
        dados["numero_pregao"] = "PE " + m_preg.group(1)

    m_val = re.search(
        r"valor m[áa]ximo estimado[^R]*R\$\s*([\d.]+,\d{2})",
        texto_edital,
        re.IGNORECASE,
    )
    if m_val:
        from hbi.utils.text import brl_para_float

        dados["valor_total_estimado"] = brl_para_float(m_val.group(1))

    return dados

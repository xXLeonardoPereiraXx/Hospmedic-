"""Módulo ``edital_validator``: validação de critérios de participação.

Aplica o catálogo de critérios de ``config/criterios_espelho.py`` sobre o
texto do edital e produz um veredito **GO / NO-GO / REVISAR**, com a
evidência textual de cada critério (rastreabilidade). Os critérios derivam do
"Espelho de Documentos de Licitação Hospitalar" — os documentos e exigências
que definem se a HospMedic consegue participar de um certame.

Filosofia (documento mestre): o sistema sinaliza; a decisão final é humana.
Por isso o veredito padrão para exigências detectadas é *revisar*, e não uma
recusa automática.
"""
from __future__ import annotations

import re

from hbi.config import criterios_espelho, settings
from hbi.models.edital import CriterioValidacao, ResultadoValidacao
from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)


def _evidencia(texto: str, match: re.Match) -> str:
    """Retorna um trecho curto ao redor do match, para rastreabilidade."""
    ini = max(0, match.start() - 40)
    fim = min(len(texto), match.end() + 40)
    return normalizar_espacos(texto[ini:fim])


# Detecta rótulos de resumo do edital respondidos com "NÃO". Muitos editais
# trazem um quadro-resumo ("EXCLUSIVO ME/EPP/EQUIPARADAS: NÃO"), onde o termo
# aparece mas a resposta o nega. A janela cobre o rótulo até o ':' e a resposta
# logo depois, tolerando o restante do rótulo entre o match e os dois-pontos.
_NEGACAO_APOS_ROTULO = re.compile(
    r"[^\n:]{0,30}:\s*n[ãa]o\b", re.IGNORECASE
)


def _negado_como_resposta(texto: str, match: re.Match) -> bool:
    """True se o match for um rótulo de resumo respondido com "NÃO".

    Ex.: ``"EXCLUSIVO ME/EPP/EQUIPARADAS:\\nNÃO"`` — o termo existe, mas a
    resposta nega. A checagem parte do fim do match e admite alguns caracteres
    do próprio rótulo (ex.: ``/EQUIPARADAS``) antes do ``:`` e do ``NÃO``.
    """
    trecho = texto[match.end(): match.end() + 40]
    return bool(_NEGACAO_APOS_ROTULO.match(trecho))


def resposta_exclusiva_me_epp(texto: str) -> tuple[bool | None, str]:
    """Lê a resposta do quadro-resumo sobre licitação exclusiva ME/EPP.

    Muitos editais trazem um quadro ("Licitação Exclusiva ME/EPP: Sim/Não").
    Detectar exclusividade por texto corrido é enganoso — a palavra aparece em
    muitos contextos, inclusive negada. Esta função procura o rótulo e lê o
    Sim/Não associado, que é a fonte autoritativa.

    Returns:
        (True, evidência)  se o quadro responde "Sim";
        (False, evidência) se responde "Não";
        (None, "")         se não há quadro-resumo identificável (aí o critério
                           fica a cargo da varredura por variantes).
    """
    # Formato A — rótulo seguido diretamente do valor:
    #   "EXCLUSIVO ME/EPP/EQUIPARADAS: NÃO"
    a = re.search(
        r"exclusiv[oa]\s+me\s*/?\s*epp[^\n:]{0,15}:\s*\n?\s*(sim|n[ãa]o)\b",
        texto,
        re.IGNORECASE,
    )
    if a:
        return a.group(1).lower().startswith("s"), _evidencia(texto, a)

    # Formato B — quadro de 4 colunas achatado pelo PDF, onde "Licitação
    # Exclusiva" é a 1ª coluna e o 1º "Sim/Não" da linha de valores é a
    # resposta dela: "Licitação Exclusiva Cota reservada ... \n Sim Sim ...".
    b = re.search(
        r"licita[çc][ãa]o exclusiva[^\n]{0,80}\n[^\n]{0,40}\n\s*(sim|n[ãa]o)\b",
        texto,
        re.IGNORECASE,
    )
    if b:
        return b.group(1).lower().startswith("s"), _evidencia(texto, b)

    return None, ""


def _primeira_variante(texto: str, variantes: list[str]) -> re.Match | None:
    """Procura, em ordem, cada variante/sinônimo e devolve o primeiro match.

    Basta uma variante casar para o critério ser considerado presente. As
    variantes são testadas na ordem em que aparecem no catálogo (da mais
    específica para a mais genérica, por convenção). Um match que seja um
    rótulo de resumo respondido com "NÃO" é ignorado (segue procurando).
    """
    for padrao in variantes:
        for m in re.finditer(padrao, texto, re.IGNORECASE):
            if _negado_como_resposta(texto, m):
                continue  # "campo: NÃO" — não conta como presente
            return m
    return None


def validar(texto_edital: str) -> ResultadoValidacao:
    """Avalia os critérios de participação e devolve o veredito.

    Args:
        texto_edital: Texto integral (ou das primeiras páginas) do edital.

    Returns:
        :class:`ResultadoValidacao` com todos os critérios e o veredito.
    """
    # O quadro-resumo (quando existe) é a fonte autoritativa para a
    # exclusividade ME/EPP; tem prioridade sobre a varredura por texto.
    resumo_exclusiva, ev_exclusiva = resposta_exclusiva_me_epp(texto_edital)

    criterios: list[CriterioValidacao] = []
    for _id, nome, categoria, variantes, impacto in criterios_espelho.CRITERIOS:
        if _id == "exclusiva_me_epp" and resumo_exclusiva is not None:
            criterios.append(
                CriterioValidacao(
                    nome=nome,
                    presente=resumo_exclusiva,
                    impacto=impacto,
                    evidencia=ev_exclusiva,
                    categoria=categoria,
                )
            )
            continue

        # Cada critério casa se QUALQUER uma de suas variantes/sinônimos
        # aparecer no texto — é isso que torna a busca robusta a diferenças
        # de redação entre editais.
        m = _primeira_variante(texto_edital, variantes)
        criterios.append(
            CriterioValidacao(
                nome=nome,
                presente=bool(m),
                impacto=impacto,
                evidencia=_evidencia(texto_edital, m) if m else "",
                categoria=categoria,
            )
        )

    # O veredito considera apenas os critérios de DECISÃO; os documentos de
    # habilitação ('checklist') compõem a lista de conferência, mas não
    # transformam sozinhos um edital em NO-GO.
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
        "valores_declarados": [],
    }

    # O nome do órgão vem logo após "MUNICÍPIO DE"/"PREFEITURA MUNICIPAL DE".
    # Captura palavras em maiúsculas até encontrar um delimitador comum
    # (ESTADO, PARANÁ, quebra de linha, CNPJ...), evitando engolir o cabeçalho
    # inteiro quando o extrator junta tudo numa linha só.
    m_orgao = re.search(
        r"(?:MUNIC[ÍI]PIO|PREFEITURA MUNICIPAL)\s+DE\s+"
        r"([A-ZÀ-Ú][A-ZÀ-Ú]*(?:\s+(?!ESTADO|PARAN[ÁA]|PA[ÇC]O|CNPJ|RUA|AV|"
        r"CEP|FONE|EDITAL|PREG[ÃA]O|PROCESSO|SECRETARIA|ESTADO)[A-ZÀ-Ú]{2,})*)",
        texto_edital,
    )
    if m_orgao:
        dados["orgao"] = normalizar_espacos(m_orgao.group(1)).title()

    m_preg = re.search(
        r"PREG[ÃA]O\s*(?:\(?ELETR[ÔO]NICO\)?)?"
        r"(?:[\s\S]{0,50}?(?:REGISTRO|PRE[ÇC]OS|SRP))?"
        r"[\s\S]{0,15}?N[º°]?\s*([\d]+/\d{4})",
        texto_edital,
        re.IGNORECASE,
    )
    if m_preg:
        dados["numero_pregao"] = "PE " + m_preg.group(1)

    # Aceita as várias formas de declarar o valor global do certame, na mesma
    # linha: "valor máximo estimado", "preço máximo global estimado",
    # "valor total estimado"... e o R$ com ou sem espaço antes do número.
    # Um mesmo edital pode declarar mais de um valor (e eles nem sempre
    # concordam), então todos são coletados.
    from hbi.utils.text import brl_para_float

    candidatos: list[tuple[str, float]] = []
    for m in re.finditer(
        r"((?:valor|pre[çc]o)[^\n]{0,60}?estimad[oa][^\n]{0,60}?)R\$\s*([\d.]+,\d{2})",
        texto_edital,
        re.IGNORECASE,
    ):
        candidatos.append((m.group(1).lower(), brl_para_float(m.group(2))))

    # Fallback: alguns editais trazem só "Valor: R$ ..." ou "Valor máximo da
    # licitação: R$ ..." no resumo, sem a palavra "estimado".
    if not candidatos:
        for m in re.finditer(
            r"(valor[^\n]{0,40}?)R\$\s*([\d.]+,\d{2})",
            texto_edital,
            re.IGNORECASE,
        ):
            candidatos.append((m.group(1).lower(), brl_para_float(m.group(2))))

    if candidatos:
        # Preferência pelo rótulo mais específico da tabela de itens
        # ("valor total estimado da contratação"); na ausência dele, o
        # primeiro valor encontrado.
        escolhido = next(
            (v for ctx, v in candidatos if "contrata" in ctx),
            candidatos[0][1],
        )
        dados["valor_total_estimado"] = escolhido
        vistos: list[float] = []
        for _, v in candidatos:
            if v not in vistos:
                vistos.append(v)
        dados["valores_declarados"] = vistos

    return dados

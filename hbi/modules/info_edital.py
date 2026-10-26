"""Módulo ``info_edital``: informações gerais do certame para o espelho.

Complementa a validação de critérios com o que a equipe consulta antes de
decidir participar: quando é a sessão, por quanto tempo a proposta precisa
valer, se há preferência para empresas locais/regionais, e com quem e onde
tratar (contatos, pregoeiro, portal de disputa).

Cada campo vem com a **evidência** (o trecho do edital em que foi achado), no
mesmo espírito da validação: a ferramenta mostra de onde tirou a informação,
para que a conferência humana seja rápida.

Duas fontes são usadas:

1. o **texto do edital** (fonte principal);
2. o **nome do arquivo**, quando segue o padrão adotado pela HospMedic —
   ``"28-10-2026 - 07 30 hrs - PE 50-2026 - Iguaraçu PR (Portal BLL).pdf"``.
   Ele serve para conferir o que foi lido do texto e para preencher o que o
   texto não trouxer; divergências entre as duas fontes são apontadas.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from hbi.utils.text import normalizar_espacos

# --- portais de disputa ------------------------------------------------------
# (nome exibido, padrões que o identificam). A ordem não importa: vence o
# portal mais citado no texto.
_PORTAIS = [
    ("BLL Compras", r"bll\.(?:org|com)\.br|bllcompras|bolsa de licita[çc][õo]es e leil"),
    ("Compras.gov.br", r"compras\.gov\.br|gov\.br/compras|comprasnet|comprasgovernamentais"),
    ("Licitanet", r"licitanet"),
    ("BNC Compras", r"bnccompras|bnc\.org\.br|bolsa nacional de compras"),
    ("Portal de Compras Públicas", r"portaldecompraspublicas"),
    ("Compras Paraná (e-compras)", r"comprasparana|e-compras"),
    ("BBMNET", r"bbmnet"),
    ("Licitações-e (Banco do Brasil)", r"licitacoes-e"),
    ("Licita+ Brasil", r"licitamaisbrasil"),
]
# PNCP é portal de PUBLICAÇÃO, não de disputa: só aparece se for o único.
_PNCP = r"pncp\.gov\.br"

_UF_POR_NOME = {
    "PARANÁ": "PR", "PARANA": "PR", "SANTA CATARINA": "SC", "SÃO PAULO": "SP",
    "SAO PAULO": "SP", "RIO GRANDE DO SUL": "RS", "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG",
}

# Nome de arquivo no padrão da equipe:
#   "28-10-2026 - 07 30 hrs - PE 50-2026 - Iguaraçu PR (Portal BLL).pdf"
_NOME_ARQUIVO = re.compile(
    r"(?P<data>\d{2}-\d{2}-\d{4})\s*-\s*(?P<hora>\d{1,2})(?:\s+(?P<min>\d{2}))?\s*hrs?"
    r"\s*-\s*PE\s*(?P<pe>\d+-\d{4})\s*-\s*(?P<local>.+?)\s+(?P<uf>[A-Z]{2})\s*"
    # parênteses opcionais: o upload troca "(Portal BLL)" por "_Portal_BLL_"
    r"\(?\s*(?:Portal\s+)?(?P<portal>[^()]+?)\s*\)?\s*$",
    re.I,
)


def _trecho(texto: str, ini: int, fim: int, folga: int = 70) -> str:
    return "…" + normalizar_espacos(texto[max(0, ini - folga): fim + folga]) + "…"


def _do_nome_arquivo(nome: str | None) -> dict:
    if not nome:
        return {}
    m = _NOME_ARQUIVO.search(Path(nome).stem.replace("#U00e9", "é").replace("_", " "))
    if not m:
        return {}
    hora = f"{int(m['hora']):02d}:{m['min'] or '00'}"
    return {
        "data_sessao": m["data"].replace("-", "/"),
        "hora_sessao": hora,
        "pregao": "PE " + m["pe"].replace("-", "/"),
        "municipio": normalizar_espacos(m["local"]).strip(" -"),
        "uf": m["uf"].upper(),
        "portal": normalizar_espacos(m["portal"]),
    }


def _sessao(texto: str) -> dict:
    """Data e hora da sessão pública (abertura/disputa)."""
    chave = re.compile(
        r"(sess[ãa]o\s+p[úu]blica|abertura\s+d[ao]s?\s+(?:sess|propost)|in[íi]cio\s+da\s+"
        r"(?:sess|disputa)|disputa\s+de\s+lances|data\s+(?:da|de)\s+(?:sess|abertura|realiza))",
        re.I,
    )
    data_re = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})")
    hora_re = re.compile(r"(\d{1,2})\s*(?:h|:|hs|horas)\s*(\d{2})?\s*(?:min)?", re.I)
    for m in chave.finditer(texto):
        janela = texto[m.end(): m.end() + 160]
        d = data_re.search(janela)
        if not d:
            continue
        # a hora vem logo depois da data ("09/07/2026 às 9h"); procurar desde
        # a palavra-chave pegaria números do local ("Avenida ..., 717")
        h = hora_re.search(janela, d.end(), d.end() + 60)
        hora = None
        if h and 0 <= int(h.group(1)) <= 23:
            hora = f"{int(h.group(1)):02d}:{h.group(2) or '00'}"
        return {
            "data_sessao": f"{int(d.group(1)):02d}/{int(d.group(2)):02d}/{d.group(3)}",
            "hora_sessao": hora,
            "evidencia": _trecho(texto, m.start(), m.end() + d.end()),
        }
    return {}


def _validade_proposta(texto: str) -> dict:
    """Prazo mínimo de validade da proposta, em dias."""
    m = re.search(
        r"validade\s+(?:m[íi]nima\s+)?d[ae]s?\s+propostas?[^.;]{0,140}?"
        r"(\d{2,3})\s*(?:\([^)]{3,40}\))?\s*dias",
        texto, re.I,
    ) or re.search(
        r"propostas?[^.;]{0,60}?validade[^.;]{0,80}?(\d{2,3})\s*(?:\([^)]{3,40}\))?\s*dias",
        texto, re.I,
    )
    if not m:
        return {}
    return {"validade_proposta_dias": int(m.group(1)),
            "evidencia": _trecho(texto, m.start(), m.end())}


def _local_regional(texto: str) -> dict:
    """Preferência ou exclusividade para empresas locais/regionais.

    Base legal típica: LC 123/2006, art. 48, §3º (prioridade a ME/EPP
    sediadas local ou regionalmente, até 10% do melhor preço válido). Alguns
    editais vão além e reservam cota ou itens a "empresas locais".
    """
    padroes = [
        # "sediadas no Município" aparece em exigência de certidão municipal
        # e NÃO indica preferência — só a fórmula da LC 123 conta
        r"sediad[ao]s?\s+local(?:mente)?(?:\s+ou\s+regional(?:mente)?)?",
        r"(?:micro\s*(?:empresas)?|ME|EPP)[^.\n]{0,60}\b(?:locais|regionais)\b",
        r"empresas\s+(?:locais|regionais|sediadas\s+na\s+regi)",
        r"art\.?\s*48,?\s*§\s*3",
        r"prioridade\s+de\s+contrata[çc][ãa]o[^.\n]{0,80}(?:local|regional)",
        # ("âmbito regional" fica de fora: descreve o mercado fornecedor —
        # "ampla disponibilidade em âmbito regional" — e não preferência)
    ]
    achados = []
    for p in padroes:
        for m in re.finditer(p, texto, re.I):
            ctx = texto[max(0, m.start() - 200): m.end() + 200].lower()
            cota = bool(re.search(r"exclusiv|reservad|cota", ctx))
            achados.append((cota, m))
    if achados:
        # cota/exclusividade é mais restritiva que a prioridade de 10% e é a
        # que decide se a HospMedic pode disputar: se existir, é ela que sai
        cota, m = max(achados, key=lambda x: x[0])
        return {"local_regional": True,
                "tipo": "cota/exclusividade para ME/EPP locais" if cota
                        else "prioridade de contratação (até 10%)",
                "evidencia": _trecho(texto, m.start(), m.end())}
    return {"local_regional": False}


def _contatos(texto: str) -> dict:
    emails = []
    for m in re.finditer(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", texto):
        e = m.group(0).strip(".").lower()
        if e not in emails:
            emails.append(e)
    telefones = []
    for m in re.finditer(
        r"(?:\(\s*\d{2}\s*\)|\b\d{2}\b)[\s.-]*(?:9\s?)?\d{4}[\s.-]?\d{4}\b", texto
    ):
        bruto = re.sub(r"\D", "", m.group(0))
        if len(bruto) in (10, 11) and not bruto.startswith(("00", "0800")):
            fmt = f"({bruto[:2]}) {bruto[2:-4]}-{bruto[-4:]}"
            # telefone precisa de contexto de telefone por perto: evita CNPJ,
            # CEP e números de processo que têm o mesmo formato de dígitos
            ctx = texto[max(0, m.start() - 40): m.start()].lower()
            if re.search(r"fone|tel|contato|whats|ramal|fax", ctx) and fmt not in telefones:
                telefones.append(fmt)
    pregoeiro = None
    m = re.search(
        r"pregoeir[oa](?:\(a\))?\s*(?:oficial|municipal)?\s*[:\-–,]?\s*(?:o\(a\)\s*|sr\.?\(?a?\)?\s*)?"
        r"([A-ZÀ-Ú][a-zà-ú]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ú][a-zà-ú]+){1,5})",
        texto,
    )
    if m:
        pregoeiro = normalizar_espacos(m.group(1))
    do_portal = re.compile(r"@(?:bll|bnc|licitanet|bbmnet|portaldecompraspublicas)\.")
    return {"emails": [e for e in emails if not do_portal.search(e)][:6],
            "emails_portal": [e for e in emails if do_portal.search(e)][:3],
            "telefones": telefones[:6], "pregoeiro": pregoeiro}


def _portal(texto: str) -> dict:
    baixo = texto.lower()
    contagem = Counter()
    for nome, padrao in _PORTAIS:
        n = len(re.findall(padrao, baixo))
        if n:
            contagem[nome] = n
    if contagem:
        nome, _ = contagem.most_common(1)[0]
        return {"portal": nome, "portais_citados": [n for n, _ in contagem.most_common()]}
    if re.search(_PNCP, baixo):
        return {"portal": "PNCP (publicação)", "portais_citados": ["PNCP"]}
    return {}


def _uf(texto: str) -> str | None:
    m = re.search(r"ESTADO\s+D[EO]\s+(PARAN[ÁA]|SANTA\s+CATARINA|S[ÃA]O\s+PAULO|"
                  r"RIO\s+GRANDE\s+DO\s+SUL|MATO\s+GROSSO\s+DO\s+SUL|MINAS\s+GERAIS)",
                  texto[:20000], re.I)
    if m:
        return _UF_POR_NOME.get(normalizar_espacos(m.group(1)).upper())
    return None


def extrair_informacoes(texto: str, nome_arquivo: str | None = None,
                        orgao: str | None = None, pregao_texto: str | None = None) -> dict:
    """Reúne as informações gerais do certame, com evidências.

    Returns:
        Dicionário com ``sessao``, ``validade``, ``local_regional``,
        ``contatos``, ``portal``, ``origem`` e ``divergencias`` (diferenças
        entre o texto e o nome do arquivo, para conferência).
    """
    arq = _do_nome_arquivo(nome_arquivo)
    sessao = _sessao(texto)
    portal = _portal(texto)
    info = {
        "sessao": sessao,
        "validade": _validade_proposta(texto),
        "local_regional": _local_regional(texto),
        "contatos": _contatos(texto),
        "portal": portal,
        "origem": {
            "orgao": orgao or arq.get("municipio"),
            "uf": _uf(texto) or arq.get("uf"),
        },
        "nome_arquivo": arq,
        "divergencias": [],
    }
    # O nome do arquivo completa e confere o que veio do texto.
    if arq:
        if pregao_texto and arq.get("pregao"):
            norm = lambda s: re.sub(r"\b0+(\d)", r"\1", re.sub(r"[^\d/]", "", s))
            if norm(pregao_texto) != norm(arq["pregao"]):
                info["divergencias"].append(
                    f"Número do pregão: texto diz {pregao_texto}, nome do arquivo diz {arq['pregao']}")
        if not sessao and arq.get("data_sessao"):
            info["sessao"] = {"data_sessao": arq["data_sessao"],
                              "hora_sessao": arq["hora_sessao"],
                              "evidencia": "(do nome do arquivo)"}
        elif sessao and not sessao.get("hora_sessao") and arq.get("hora_sessao") \
                and sessao["data_sessao"] == arq["data_sessao"]:
            info["sessao"]["hora_sessao"] = arq["hora_sessao"] + " (do nome do arquivo)"
        elif (sessao and sessao.get("hora_sessao") and arq.get("hora_sessao")
              and sessao["data_sessao"] == arq["data_sessao"]
              and sessao["hora_sessao"] != arq["hora_sessao"]):
            info["divergencias"].append(
                f"Hora da sessão: edital diz {sessao['hora_sessao']}, "
                f"nome do arquivo diz {arq['hora_sessao']} (vale o edital)")
        elif sessao and arq.get("data_sessao") and sessao["data_sessao"] != arq["data_sessao"]:
            info["divergencias"].append(
                f"Data da sessão: texto diz {sessao['data_sessao']}, "
                f"nome do arquivo diz {arq['data_sessao']}")
        if not portal and arq.get("portal"):
            info["portal"] = {"portal": arq["portal"] + " (do nome do arquivo)"}
        elif portal and arq.get("portal"):
            a = re.sub(r"[^a-z]", "", arq["portal"].lower())
            p = re.sub(r"[^a-z]", "", portal["portal"].lower())
            if a and a[:3] not in p and p[:3] not in a:
                info["divergencias"].append(
                    f"Portal: texto indica {portal['portal']}, nome do arquivo diz {arq['portal']}")
    return info

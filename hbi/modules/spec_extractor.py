"""Módulo ``spec_extractor``: descritivos técnicos completos fora da tabela.

Muitos editais (padrão SESA/Curitiba e derivados) separam o item em **duas
partes do documento**:

1. a **tabela**, com quantidade, unidade e valores (lida por
   ``table_extractor``), onde a descrição vem resumida; e
2. uma **seção de especificações técnicas**, onde cada produto aparece com o
   descritivo íntegro, indexado por um rótulo.

Este módulo lê a segunda parte e devolve um índice ``chave -> descritivo``,
que o pipeline concatena ao item correspondente. São suportadas as duas
formas de indexação encontradas nesses editais:

* **por lote** — ``"LOTES 1 E 2: CURATIVO FIX CATÉTER CURTA PERMANÊNCIA."``
  (edital organizado em lotes, cada um com item único);
* **por item** — ``"ITEM 5: SERINGA DESCARTÁVEL 20 ml"`` (edital com itens
  soltos, numeração corrida).

A chave usada é decidida **por documento**, pela contagem de rótulos de cada
tipo, e não fixada em código: um mesmo edital pode escrever "LOTE 17 e 18"
(singular, conectivo minúsculo) e "LOTES 1 E 2" na mesma seção.

Estratégia (independente de layout):

1. **Localizar a seção**: o cabeçalho de especificações técnicas
   (ex.: ``"1.2 ESPECIFICAÇÕES TÉCNICAS"``). Sem cabeçalho explícito, a
   varredura considera o documento inteiro — os rótulos se autoidentificam.
2. **Segmentar por âncoras de rótulo**: cada bloco vai do seu rótulo até o
   rótulo seguinte (ou até o fim da seção). O texto NÃO é removido do
   documento: fatiar preserva as fronteiras originais.
3. **Expandir o rótulo em chaves**: ``"LOTES 1 E 2"`` indexa o mesmo
   descritivo para os lotes 1 e 2 (rótulo → várias chaves).
4. **Limpar o corpo**: rodapés repetidos, cabeçalhos de página e numeração
   de seção não fazem parte do descritivo.
"""
from __future__ import annotations

import re

from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)

# --- Localização da seção de especificações ---------------------------------
# Aceita a numeração de item de edital ("1.2") ou o título isolado.
_INICIO_SECAO = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s*)?"
    r"(?:ESPECIFICA[ÇC][ÕO]ES\s+T[ÉE]CNICAS"
    r"|DESCRI[ÇC][ÕO]ES?\s+(?:T[ÉE]CNICAS?|DETALHADAS?|COMPLETAS?)"
    r"|ESPECIFICA[ÇC][ÃA]O\s+DOS?\s+(?:ITENS|PRODUTOS|OBJETOS?))\s*:?\s*$",
    re.I,
)

# Fim da seção: volta a numeração de subitens do edital (ex.: "1.2.1
# Requisitos da contratação") ou começa outro capítulo ("2. DA JUSTIFICATIVA").
_FIM_SECAO = re.compile(
    r"^\s*\d+(?:\.\d+){1,3}\s+[A-ZÀ-Ú][^\n]{3,}"
    r"|^\s*\d+\s*[.\-–]\s*(?:DA|DO|DAS|DOS)\s+[A-ZÀ-Ú]",
)

# --- Rótulos que abrem um bloco de descritivo -------------------------------
# "LOTES 1 E 2:", "LOTE 17 e 18:", "ITEM 5 -", "ITENS 3 E 4:".
# O conectivo aceita "E"/"e"/","/"a" e o separador final ":" ou "-".
_NUMEROS = r"\d+(?:\s*(?:,|E|e|/)\s*\d+)*"
_ROTULO = re.compile(
    r"^\s*(LOTES?|ITE(?:M|NS))\s+(" + _NUMEROS + r")\s*[:\-–—]\s*(.*)$",
    re.I,
)

# Ruído de página que pode cair dentro de um bloco (rodapé institucional,
# cabeçalho repetido, marca d'água de protocolo).
_RUIDO_LINHA = re.compile(
    r"Procuradoria-Geral|Minuta Padronizada|Atualiza[çc][ãa]o:\s*\w+/\d{4}"
    r"|^Protocolo n|^ESTADO DO |^SECRETARIA DE ESTADO|^\s*CPL\s*[–\-]"
    r"|COMISS[ÃA]O PERMANENTE|p[áa]gina\s+\d+\s+de\s+\d+",
    re.I,
)


def _expandir_chaves(texto_numeros: str) -> list[int]:
    """Converte o miolo do rótulo em lista de números.

    ``"1 E 2"`` -> ``[1, 2]``; ``"17 e 18"`` -> ``[17, 18]``; ``"5"`` -> ``[5]``.
    """
    return [int(n) for n in re.findall(r"\d+", texto_numeros)]


def _limpar_corpo(linhas: list[str]) -> str:
    """Junta as linhas do bloco, descartando ruído de página."""
    uteis = [ln for ln in linhas if ln.strip() and not _RUIDO_LINHA.search(ln)]
    return normalizar_espacos(" ".join(uteis))


def extrair_descritivos(texto: str) -> tuple[str | None, dict[int, str]]:
    """Extrai os descritivos técnicos completos e o tipo de chave usado.

    Args:
        texto: Texto integral do edital.

    Returns:
        Uma tupla ``(tipo_chave, descritivos)``, onde ``tipo_chave`` é
        ``"lote"``, ``"item"`` ou ``None`` (nenhum descritivo encontrado), e
        ``descritivos`` mapeia o número da chave para o texto completo.
    """
    linhas = texto.split("\n")

    # 1) Delimita a seção de especificações, quando houver cabeçalho próprio.
    ini = 0
    for i, ln in enumerate(linhas):
        if _INICIO_SECAO.match(ln):
            ini = i + 1
            break

    fim = len(linhas)
    if ini:  # só procura o fim se a seção foi realmente identificada
        for j in range(ini, len(linhas)):
            if _FIM_SECAO.match(linhas[j]) and not _ROTULO.match(linhas[j]):
                fim = j
                break

    # 2) Segmenta por âncoras de rótulo.
    blocos: list[tuple[str, list[int], str, list[str]]] = []  # tipo, chaves, título, corpo
    for i in range(ini, fim):
        m = _ROTULO.match(linhas[i])
        if not m:
            if blocos:
                blocos[-1][3].append(linhas[i])
            continue
        tipo = "lote" if m.group(1).lower().startswith("lote") else "item"
        chaves = _expandir_chaves(m.group(2))
        titulo = normalizar_espacos(m.group(3))
        blocos.append((tipo, chaves, titulo, []))

    if not blocos:
        log.info("Nenhum descritivo técnico separado encontrado.")
        return None, {}

    # 3) Decide a chave do documento pela predominância dos rótulos. Um edital
    #    pode ter rótulos avulsos do outro tipo em textos vizinhos; a maioria
    #    manda, e blocos do tipo minoritário são descartados para não misturar
    #    numerações de espaços diferentes.
    contagem = {"lote": 0, "item": 0}
    for tipo, chaves, _, _ in blocos:
        contagem[tipo] += len(chaves)
    tipo_chave = max(contagem, key=lambda k: contagem[k])

    # 4) Monta o índice chave -> descritivo (título + corpo).
    descritivos: dict[int, str] = {}
    for tipo, chaves, titulo, corpo in blocos:
        if tipo != tipo_chave:
            continue
        texto_bloco = _limpar_corpo(corpo)
        completo = normalizar_espacos(f"{titulo} {texto_bloco}".strip())
        if len(completo) < 20:  # rótulo sem conteúdo real
            continue
        for k in chaves:
            # Rótulos repetidos (o edital reimprime blocos): mantém o maior,
            # que tende a ser o descritivo íntegro e não uma menção de passagem.
            if k not in descritivos or len(completo) > len(descritivos[k]):
                descritivos[k] = completo

    log.info(
        "Descritivos técnicos extraídos: %d (indexados por %s)",
        len(descritivos), tipo_chave,
    )
    return tipo_chave, descritivos


def aplicar_descritivos(itens, tipo_chave: str | None, descritivos: dict[int, str]):
    """Concatena cada descritivo ao item correspondente (join).

    A chave do join é o **lote** ou o **número do item**, conforme o tipo
    detectado. A descrição resumida da tabela é preservada e o descritivo
    completo vem em seguida — a planilha da HospMedic precisa do texto do
    edital, e a parte resumida traz códigos (GMS/CATMAT) que não se repetem
    na seção de especificações.

    Args:
        itens: Lista de :class:`~hbi.models.edital.ItemEdital`.
        tipo_chave: ``"lote"``, ``"item"`` ou ``None``.
        descritivos: Índice devolvido por :func:`extrair_descritivos`.

    Returns:
        Um dicionário de diagnóstico do join (para o relatório).
    """
    diag = {
        "tipo_chave": tipo_chave,
        "descritivos": len(descritivos),
        "itens_enriquecidos": 0,
        "itens_sem_descritivo": [],
        "descritivos_orfaos": [],
    }
    if not tipo_chave or not descritivos:
        return diag

    usadas: set[int] = set()
    for it in itens:
        chave = it.lote if tipo_chave == "lote" else it.item
        if chave is None:
            continue
        texto = descritivos.get(chave)
        if not texto:
            diag["itens_sem_descritivo"].append(it.item)
            continue
        usadas.add(chave)
        # Editais sem tabela (itens em blocos de texto) já trazem o descritivo
        # embutido na própria descrição: nesses casos o "join" apenas confirma
        # o texto, e concatenar duplicaria o parágrafo inteiro. A checagem
        # abaixo cobre os dois sentidos de contenção e mantém o texto maior.
        atual = it.descricao or ""
        nucleo = normalizar_espacos(atual).lower()[:60]
        if nucleo and nucleo in texto.lower():
            it.descricao = texto if len(texto) > len(atual) else atual
        elif texto.lower()[:60] in nucleo:
            it.descricao = atual
        else:
            it.descricao = normalizar_espacos(f"{atual} {texto}")
        diag["itens_enriquecidos"] += 1

    diag["descritivos_orfaos"] = sorted(set(descritivos) - usadas)
    log.info(
        "Join de descritivos: %d itens enriquecidos, %d sem descritivo, %d órfãos",
        diag["itens_enriquecidos"], len(diag["itens_sem_descritivo"]),
        len(diag["descritivos_orfaos"]),
    )
    return diag

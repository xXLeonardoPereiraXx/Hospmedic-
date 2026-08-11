"""Módulo ``table_extractor``: extração genérica da tabela de itens.

Estratégia independente de coordenadas de coluna, validada em layouts
distintos (edital com grade de células e edital em texto corrido):

1. **Âncora numérica**: uma linha que começa com um inteiro e termina com
   dois valores monetários (valor unitário e valor total). Ela marca a
   fronteira de cada item e é a fonte confiável dos valores.
2. **Contagem incremental**: a âncora só é aceita se o número for o próximo
   esperado (1, 2, 3, ...). Isso rejeita falsos-positivos de dígitos soltos.
3. **Descrição**: linhas de texto entre âncoras, atribuídas à âncora mais
   próxima dentro de uma janela máxima de linhas.
4. **Quantidade**: derivada de ``valor_total / valor_unitario`` (os dois
   dados mais confiáveis da linha); o parse do "miolo" da âncora serve como
   verificação cruzada.

Substitui a abordagem anterior por coordenadas fixas, que não generalizava
entre layouts de edital diferentes.
"""
from __future__ import annotations

import bisect
import re

from hbi.models.edital import ItemEdital
from hbi.utils.logger import get_logger
from hbi.utils.text import normalizar_espacos

log = get_logger(__name__)

# 2 a 4 casas decimais: há editais que publicam preço unitário com milésimos
# de real (ex.: "R$ 21,735" e "R$ 2,3150" no TR da 5ª Brigada).
_MONEY = r"\d{1,3}(?:\.\d{3})*,\d{2,4}"
_MONEY_RE = re.compile(_MONEY)
# Prefixo monetário opcional: há editais que imprimem "R$ 14,17" e até
# "R$708,50" (sem espaço) na própria linha do item — ex.: Paranacity.
_RS = r"(?:R\$\s*)?"
# Sufixo tolerado após o último valor: colunas finais da tabela que não são
# valores — vazias ("- - - -") ou de margem de preferência ("MedNac 5%
# MedIFANac 10%"), como no Termo de Referência da 5ª Brigada. Cada token do
# sufixo NÃO pode ser um valor monetário: isso garante que os dois valores
# capturados sejam sempre os DOIS ÚLTIMOS da linha (unitário e total).
_SUFIXO = r"(?:\s+(?!(?:R\$\s*)?" + _MONEY + r")\S+){0,6}[\s\-–]*$"
_ANCHOR = re.compile(
    r"^\s*(\d+)\b(.*?)" + _RS + r"(" + _MONEY + r")\s+" + _RS + r"(" + _MONEY + r")" + _SUFIXO
)

# Para o layout INVERTIDO (Florianópolis): linha de valores que NÃO começa com
# número (começa com a descrição) e termina em dois valores monetários; e a
# linha seguinte, que começa com o número do item seguido da descrição.
_ANCHOR_SEM_NUMERO = re.compile(
    r"^\s*([^\d].*?)" + _RS + r"(" + _MONEY + r")\s+" + _RS + r"(" + _MONEY + r")\s*$"
)
_NUMERO_INICIO = re.compile(r"^\s*(\d+)\s+([A-Za-zÀ-ú].*)$")

# Layout com VALOR QUEBRADO (Paranacity, TR da 5ª Brigada): o extrator de
# texto parte um dos valores da linha do item em pedaços — um "R$" órfão numa
# linha vizinha e o número deslocado para a linha seguinte — deixando a
# linha-âncora com UM único valor monetário. Ex. (Paranacity):
#   "R$"
#   "238 KIT LARINGOSCÓPIO ADULTO UN 4 R$4.000,00"
#   "1.000,00"
# Na Brigada o valor deslocado pode ainda vir MISTURADO a texto de descrição
# ("Unidades 1.023,75") e a linha do item termina em traços de colunas vazias.
_ANCHOR_VALOR_QUEBRADO = re.compile(
    r"^\s*(\d+)\b(.*?)" + _RS + r"(" + _MONEY + r")" + _SUFIXO
)

# Salto máximo tolerado na numeração de itens. Cobre lacunas causadas por itens
# de layout atípico (descrição multi-linha, valor em linha separada) que não
# formam âncora — inclusive blocos de vários itens seguidos assim. Mantido
# baixo o bastante para não capturar números espúrios (datas, códigos). A
# checagem de consistência (qtd × valor == total) filtra o que passar.
_SALTO_MAXIMO = 12

# --- Fronteiras estruturais da tabela ----------------------------------------
# Editais organizados por lote (portal BLL e similares) abrem cada bloco com
# "Lote: N" e o encerram com uma linha "TOTAL <valor>". O cabeçalho da tabela
# se repete a cada lote/página. As três marcações delimitam blocos de item.
_LOTE = re.compile(r"^[^\w]{0,40}Lote:\s*(\d+)", re.I)
_TOTAL_LINHA = re.compile(r"^\s*TOTAL\s+" + _MONEY + r"\s*$", re.I)

# Palavras que nomeiam colunas da tabela de itens. O cabeçalho é reconhecido
# pela densidade delas na linha, e não por um formato fixo: há editais que
# imprimem o cabeçalho quebrado ou até com a palavra "ITEM" na vertical
# (uma letra por linha), caso em que a linha útil não começa por "Item".
_PALAVRAS_CABECALHO = (
    r"item|c[óo]digo|catmat|descri[çc][ãa]o|produto|servi[çc]o|unidade|unid"
    r"|und|qtde|qtd|quant|pre[çc]o|valor|total|m[ée]dia|aritm[ée]tica"
    r"|marca|amostra"
)
_CABECALHO_RE = re.compile(_PALAVRAS_CABECALHO, re.I)


def _eh_cabecalho_tabela(linha: str) -> bool:
    """True se a linha parece o cabeçalho da tabela de itens."""
    if len(linha) > 140:
        return False
    achados = {m.group(0).lower() for m in _CABECALHO_RE.finditer(linha)}
    return len(achados) >= 3
_NOISE = re.compile(
    r"(MUNIC[ÍI]PIO|Estado do Paran|ANEXO|^Item\b|^Und\b|^Forne|^\d+\.\d"
    r"|CNPJ|e-mail|Telefone|^Rua |HAVENDO|OBJETO CONSTANTE|EDITAL\."
    r"|CONDI[ÇC][ÕO]ES GERAIS|Registro de Pre|PREFEIT|ADVOGADO|CONTRATANTE"
    r"|Valor Uni|Valor Total|MÉDIA|PRODUTO|Descrição|P[áa]gina\s*:"
    # fragmentos de cabeçalho de tabela quebrado em várias linhas pelo PDF
    # (ex.: "Nome do produto/serviço" vira "produto/se" + "rviço")
    r"|^produto/|^rvi[çc]o\b|^dade\s+m[áa]ximo|^servi[çc]o\b|ARITM[ÉE]TICA)",
    re.I,
)


def _to_float(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _linha_predominantemente_numerica(linha: str) -> bool:
    """True se a linha é basicamente números (linha de totais/colunas).

    Descrição de produto é texto; uma linha com vários números e quase nenhuma
    letra é resíduo de tabela (subtotais, colunas de valores) e não deve
    entrar na descrição.
    """
    letras = sum(1 for c in linha if c.isalpha())
    numeros = len(re.findall(r"\d[\d.,]*", linha))
    return numeros >= 3 and letras < len(linha) * 0.3


def _quantidade_parse(miolo: str) -> float | None:
    """Último grupo inteiro do miolo da âncora (coluna de quantidade)."""
    toks = re.findall(r"\b\d{1,3}(?:\.\d{3})*\b", miolo)
    if not toks:
        return None
    return float(toks[-1].replace(".", ""))


_UNIDADE_RE = re.compile(
    r"\b(CX|CAIXA|UNID|UND|UNI|UN|PCT|PC|PACOTE|ROLO|RL|LITRO|LT|EMB|FRASCO"
    r"|FRS|FR|PAR|KG|ML|MT|CONJ|BOLSA|GAL[ÃA]O|GL|BOMBA|AMPOLA|AMP|TB|DZ"
    r"|L|G)\b",
    re.I,
)


def _limpar_quantidade(descricao: str, quantidade: float) -> str:
    """Remove do fim da descrição o número que repete a quantidade.

    Em layouts onde a coluna de quantidade fica encostada na descrição, o
    valor acaba grudado no texto (ex.: ``"ÁGUA OXIGENADA 300,00"``). A
    remoção só acontece quando o número no fim **é** a quantidade já
    confirmada por ``valor_total / valor_unitário`` — assim números que
    fazem parte do produto (ex.: ``"AGULHA 13 X 4,5"``) são preservados.
    """
    if not descricao or not quantidade:
        return descricao
    q = int(quantidade) if float(quantidade).is_integer() else quantidade
    formas = {f"{q}", f"{q:,}".replace(",", "."), f"{q},00"}
    if isinstance(q, int):
        formas.add(f"{q:,}".replace(",", ".") + ",00")
    for forma in sorted(formas, key=len, reverse=True):
        alvo = re.escape(forma)
        novo = re.sub(rf"\s*\b{alvo}\s*[.,;]?\s*$", "", descricao)
        if novo != descricao:
            return novo.strip()
    return descricao


def _parse_miolo(miolo: str) -> tuple[str, str]:
    """Separa (descrição, unidade) do miolo da âncora, em layouts compactos.

    Em editais que colocam a descrição na própria linha-âncora
    (ex.: ``. 93656 397513 AGULHA DESCARTÁVEL ... CX COM 1000 NÃO``), a
    descrição vem antes do token de unidade e depois dos códigos numéricos
    (CATMAT). Em layouts onde a descrição fica nas linhas vizinhas, o miolo
    é curto (ex.: ``Cx 5 10 20``) e esta função devolve descrição vazia,
    deixando o chamador cair para as linhas de descrição próximas.
    """
    m = re.sub(r"^[.\-\s]+", "", miolo.strip())
    m = re.sub(r"\s+(NÃO|SIM)\s*$", "", m, flags=re.I)  # flag de amostra
    # A unidade de fornecimento é o ÚLTIMO token de unidade do miolo (vem
    # logo antes da quantidade). Usar o primeiro quebraria descrições de
    # produtos que COMEÇAM com palavra-unidade (ex.: "BOLSA RESGATE ... UN 1").
    achados_unidade = list(_UNIDADE_RE.finditer(m))
    um = achados_unidade[-1] if achados_unidade else None
    if um:
        desc = m[: um.start()].strip()
        unidade = um.group(1)
    else:
        desc, unidade = m, ""
    # remove grupos de códigos numéricos iniciais (CATMAT etc.)
    desc = re.sub(r"^(?:\d{3,}\s+){0,3}", "", desc).strip()
    # se o "resto" for basicamente numérico (colunas de qtd), não é descrição
    if desc and len(re.sub(r"[\d\s.,]", "", desc)) < 3:
        desc = ""
    return desc, unidade


def _coletar_linhas(reader, pagina_inicio: int, pagina_fim: int | None) -> list[str]:
    linhas: list[str] = []
    paginas = list(reader.paginas())
    fim = pagina_fim if pagina_fim is not None else len(paginas)
    for pi in range(pagina_inicio, min(fim, len(paginas))):
        texto = paginas[pi].extract_text() or ""
        for ln in texto.split("\n"):
            linhas.append((ln.strip(), pi + 1))  # guarda a página (rastreabilidade)
    return linhas


def extrair_itens(
    reader,
    pagina_inicio: int = 0,
    pagina_fim: int | None = None,
    janela_borda: int = 12,
) -> list[ItemEdital]:
    """Extrai os itens do Termo de Referência de forma genérica.

    Args:
        reader: Instância de ``PdfReader`` já aberta.
        pagina_inicio: Índice (0-based) da primeira página a varrer.
        pagina_fim: Índice (0-based, exclusivo) da última. ``None`` = fim.
        janela_borda: Distância máxima (em linhas) para aproveitar texto que
            esteja FORA do intervalo da tabela (antes da primeira âncora ou
            depois da última). Dentro da tabela não há limite: o bloco é
            delimitado pelas âncoras vizinhas e pelas fronteiras estruturais.

    Returns:
        Lista de :class:`ItemEdital`, ordenada por número de item.
    """
    linhas_pag = _coletar_linhas(reader, pagina_inicio, pagina_fim)
    linhas = [lp[0] for lp in linhas_pag]
    paginas = [lp[1] for lp in linhas_pag]

    # 1) âncoras, com contagem incremental sensível a lotes.
    #    Em editais organizados por lote (ex.: portal BLL), a numeração de item
    #    REINICIA em 1 a cada lote. Sem tratar isso, a contagem incremental
    #    global aceitaria apenas o primeiro item de todo o documento.
    #
    #    A contagem tolera PEQUENOS SALTOS para frente: alguns editais têm itens
    #    cujo layout impede a formação da âncora (descrição multi-linha com os
    #    valores em linha separada), fazendo a numeração "pular" (ex.: 59 -> 62).
    #    Aceitar num >= esperado (dentro de uma folga) recupera os itens de
    #    layout normal em vez de parar no primeiro salto. Saltos grandes são
    #    rejeitados para não capturar números espúrios (datas, códigos).
    anchors = []  # (idx, num, miolo, vunit, vtot, pagina, lote)
    esperado = 1
    lote_atual: int | None = None
    consumidas_invertido: set[int] = set()  # linhas já usadas por âncora invertida
    for idx, ln in enumerate(linhas):
        m_lote = _LOTE.match(ln)
        if m_lote:
            lote_atual = int(m_lote.group(1))
            esperado = 1  # a numeração de item recomeça dentro do lote
            continue
        m = _ANCHOR.match(ln)
        if not m:
            # Layout INVERTIDO (visto no edital de Florianópolis): a linha de
            # valores vem primeiro (descrição + qtd + un + 2 valores, mas SEM
            # começar por número) e a linha SEGUINTE começa com o número do
            # item + continuação da descrição. Detecta-se pelo par:
            #   "<desc> <qtd> <un> <vunit> <vtot>"   (esta linha, sem número)
            #   "<num> <resto da descrição>"          (linha seguinte)
            m_val = _ANCHOR_SEM_NUMERO.match(ln)
            if m_val and idx + 1 < len(linhas):
                m_next = _NUMERO_INICIO.match(linhas[idx + 1])
                if m_next:
                    num = int(m_next.group(1))
                    if esperado <= num <= esperado + _SALTO_MAXIMO:
                        # descrição = parte textual desta linha + a da próxima
                        desc_val = m_val.group(1).strip()
                        desc_next = m_next.group(2).strip()
                        miolo = (desc_val + " " + desc_next).strip()
                        anchors.append(
                            (idx, num, miolo,
                             _to_float(m_val.group(2)), _to_float(m_val.group(3)),
                             paginas[idx], lote_atual)
                        )
                        esperado = num + 1
                        # ambas as linhas foram consumidas: não devem vazar
                        # como descrição de itens vizinhos
                        consumidas_invertido.add(idx)
                        consumidas_invertido.add(idx + 1)
                        continue
            # Layout com VALOR QUEBRADO: a linha do item traz UM valor no fim
            # e o outro valor está sozinho na linha seguinte. A âncora só é
            # aceita se (a) o número segue a sequência esperada e (b) a
            # conferência qtd × unitário == total fecha para alguma das duas
            # atribuições possíveis — o que também decide qual valor é qual.
            m_q = _ANCHOR_VALOR_QUEBRADO.match(ln)
            if m_q and idx + 1 < len(linhas):
                num_q = int(m_q.group(1))
                if esperado <= num_q <= esperado + _SALTO_MAXIMO:
                    v_linha = _to_float(m_q.group(3))
                    miolo = m_q.group(2).strip()
                    # quantidades candidatas vindas do miolo: o último número
                    # inteiro (coluna de quantidade) e a soma de todos eles
                    # (editais que somam quantidades de mais de um destinatário,
                    # ex.: "410 100" -> 510 no TR da Brigada).
                    toks = re.findall(r"\b\d{1,3}(?:\.\d{3})*\b", miolo)
                    qs = []
                    if toks:
                        qs.append(float(toks[-1].replace(".", "")))
                        if len(toks) > 1:
                            qs.append(sum(float(t.replace(".", "")) for t in toks))
                    # O valor deslocado costuma estar na linha seguinte, mas
                    # pode cair na linha ANTERIOR ou, em quebra de página, ser
                    # empurrado várias linhas adiante (depois do rodapé). Nas
                    # linhas vizinhas imediatas basta a razão inteira; longe
                    # da âncora, só a validação forte (qtd × unit == total).
                    achado = None  # (vunit, vtot, valor_txt, idx_linha)
                    # janela adiante mais longa: em quebra de página o valor
                    # atravessa rodapé + cabeçalho antes de reaparecer.
                    for off in (1, -1, 2, -2, 3, 4, 5, 6, 7, 8, 9, 10):
                        j = idx + off
                        if not (0 <= j < len(linhas)):
                            continue
                        for s in _MONEY_RE.findall(linhas[j]):
                            v_solto = _to_float(s)
                            vunit = min(v_linha, v_solto)  # total >= unitário
                            vtot = max(v_linha, v_solto)
                            if vunit <= 0:
                                continue
                            forte = any(abs(q * vunit - vtot) <= 0.5 for q in qs)
                            r = vtot / vunit
                            fraca = abs(r - round(r)) < 0.01
                            if forte or (abs(off) == 1 and fraca):
                                achado = (vunit, vtot, s, j)
                                break
                        if achado:
                            break
                    if achado is not None:
                        vunit, vtot, s, j = achado
                        anchors.append(
                            (idx, num_q, miolo, vunit, vtot,
                             paginas[idx], lote_atual)
                        )
                        esperado = num_q + 1
                        # remove da linha vizinha só o valor consumido (e um
                        # "R$" encostado), preservando texto de descrição que
                        # esteja misturado nela.
                        linhas[j] = re.sub(
                            r"(?:R\$\s*)?" + re.escape(s), " ",
                            linhas[j], count=1,
                        ).strip()
            continue
        num = int(m.group(1))
        if esperado <= num <= esperado + _SALTO_MAXIMO:
            anchors.append(
                (idx, num, m.group(2).strip(),
                 _to_float(m.group(3)), _to_float(m.group(4)),
                 paginas[idx], lote_atual)
            )
            esperado = num + 1

    if not anchors:
        log.warning("Nenhuma âncora de item encontrada nas páginas varridas.")
        return []

    # 2) Fronteiras estruturais: cabeçalho de tabela, linha de TOTAL e início
    #    de lote delimitam blocos. Elas impedem que uma linha de descrição
    #    "vaze" de um item para outro (ou do texto introdutório para o item 1).
    fronteiras = {
        i for i, ln in enumerate(linhas)
        if _LOTE.match(ln) or _TOTAL_LINHA.match(ln) or _eh_cabecalho_tabela(ln)
    }

    def _mesma_secao(a: int, b: int) -> bool:
        """True se não há fronteira estrutural entre as linhas ``a`` e ``b``."""
        ini, fim = (a, b) if a < b else (b, a)
        return not any(f for f in fronteiras if ini < f < fim)

    # 3) Direção da descrição — varia conforme o layout do edital.
    #    Quando a própria linha-âncora já abre a descrição (layout compacto,
    #    um item por linha), o texto que sobra CONTINUA nas linhas seguintes,
    #    e atribuir pela menor distância partiria essa continuação com o item
    #    de baixo. Quando o miolo é só numérico (colunas de qtd/valor), a
    #    descrição vem nas linhas ANTES da âncora. A proporção de âncoras cujo
    #    miolo traz texto decide o modo, por documento.
    miolos_com_texto = sum(
        1 for a in anchors if len(_parse_miolo(a[2])[0]) >= 8
    )
    modo_avante = miolos_com_texto / len(anchors) >= 0.8

    aidx = [a[0] for a in anchors]
    anchor_set = set(aidx)
    primeira_ancora, ultima_ancora = aidx[0], aidx[-1]
    desc: dict[int, list[tuple[int, str]]] = {k: [] for k in range(len(anchors))}
    for i, ln in enumerate(linhas):
        # Linhas de 1–2 caracteres costumam ser restos de cabeçalho impresso
        # na vertical (uma letra por linha) — nunca são descrição de produto.
        if (i in anchor_set or i in fronteiras or i in consumidas_invertido
                or len(ln.strip()) < 3
                or _NOISE.search(ln) or _linha_predominantemente_numerica(ln)):
            continue

        # Fora do intervalo da tabela, só se aceita texto bem próximo da
        # primeira/última âncora: o que vem muito antes é a introdução do
        # edital e o que vem muito depois são cláusulas — nunca descrição.
        if i < primeira_ancora and primeira_ancora - i > janela_borda:
            continue
        if i > ultima_ancora and i - ultima_ancora > janela_borda:
            continue

        # Dentro da tabela, o bloco de descrição é delimitado pelas âncoras
        # vizinhas e pelas fronteiras estruturais — sem limite de linhas,
        # porque o tamanho do bloco varia muito conforme a largura da coluna
        # (de ~5 linhas por item a ~30 em editais de coluna estreita).
        pos = bisect.bisect_left(aidx, i)
        candidatos = []
        if pos > 0:
            candidatos.append(pos - 1)          # âncora acima
        if pos < len(aidx) and not modo_avante:
            candidatos.append(pos)              # âncora abaixo
        melhor, bk = 10**9, None
        for k in candidatos:
            if not _mesma_secao(aidx[k], i):
                continue
            d = abs(aidx[k] - i)
            if d < melhor:
                melhor, bk = d, k
        if bk is not None:
            desc[bk].append((i, ln))

    # 4) monta os itens
    usa_lotes = any(a[6] is not None for a in anchors)
    itens: list[ItemEdital] = []
    for k, (idx, num, miolo, vunit, vtot, pagina, lote) in enumerate(anchors):
        # quantidade: derivada de total/unit; parse do miolo como verificação
        q_parse = _quantidade_parse(miolo)
        q_deriv = None
        if vunit > 0:
            r = vtot / vunit
            if abs(r - round(r)) < 0.01:
                q_deriv = float(round(r))
        quantidade = q_deriv if q_deriv is not None else (q_parse or 0.0)

        # descrição/unidade a partir do próprio miolo (layouts compactos)
        desc_miolo, unid_miolo = _parse_miolo(miolo)
        desc_miolo = _limpar_quantidade(desc_miolo, quantidade)

        # A descrição pode vir ANTES da âncora (ex.: Nova Fátima), DEPOIS dela
        # (ex.: Curiúva) ou dentro do próprio miolo (ex.: Campo Largo). Para
        # montar o texto na ordem de leitura correta em todos os casos, cada
        # fragmento é posicionado pelo índice da linha de onde veio — o miolo
        # ocupa a posição da própria linha-âncora.
        fragmentos: list[tuple[int, str]] = list(desc[k])
        if desc_miolo:
            fragmentos.append((idx, desc_miolo))
        texto_desc = normalizar_espacos(
            " ".join(txt for _, txt in sorted(fragmentos))
        )
        unidade = unid_miolo or _unidade_do_miolo(miolo)

        # Em editais por lote a numeração reinicia a cada lote, então o número
        # do item não é único no documento. Nesse caso a planilha recebe uma
        # numeração global sequencial e o lote fica registrado à parte.
        numero = (k + 1) if usa_lotes else num

        itens.append(
            ItemEdital(
                item=numero,
                descricao=normalizar_espacos(texto_desc),
                unidade=unidade,
                quantidade=quantidade,
                valor_estimado=vunit,
                valor_total=vtot,
                pagina=pagina,
                lote=lote,
            )
        )

    if usa_lotes:
        log.info("Itens extraídos: %d (âncora genérica, edital por lote)", len(itens))
    else:
        log.info("Itens extraídos: %d (âncora genérica)", len(itens))
    return itens


def _unidade_do_miolo(miolo: str) -> str:
    """Tenta identificar a unidade de fornecimento no miolo da âncora.

    Procura um token de unidade conhecido; não havendo, usa a heurística
    posicional de que a unidade costuma vir logo depois da quantidade
    (ex.: ``"300,00 LT"``). Sem candidato plausível, devolve string vazia:
    para um campo de conferência, vazio é melhor que errado.
    """
    m = _UNIDADE_RE.search(miolo)
    if m:
        return m.group(1)
    m_pos = re.search(r"\d[\d.,]*\s+([A-Za-zÀ-ú]{1,6})\b", miolo)
    if m_pos:
        return m_pos.group(1)
    return ""

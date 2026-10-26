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
# Prefixo textual opcional antes do número do item. Editais em formato de
# "ficha por lote" (SESA/Curitiba) rotulam a linha como "ITEM 1 PEÇA 276.315
# R$ 4,28 R$ 1.182.628,20" — o número não abre a linha, vem depois da palavra.
_ITEM_PREFIXO = r"(?:ITE(?:M|NS)\s+)?"
_ANCHOR = re.compile(
    r"^\s*" + _ITEM_PREFIXO + r"(\d+)\b(.*?)" + _RS + r"(" + _MONEY + r")\s+" + _RS
    + r"(" + _MONEY + r")" + _SUFIXO,
    re.I,
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
_LOTE = re.compile(
    r"^[^\w]{0,40}Lote:\s*(\d+)"
    # Cabeçalho de ficha por lote (SESA/Curitiba): "LOTE 1 – AMPLA CONCORRÊNCIA"
    # ou "LOTE 2 – LOTE RESERVADO PARA ME/EPP" — sem dois-pontos após o número.
    r"|^\s*LOTE\s+(\d+)\s*[–\-—]",
    re.I,
)
# Linha de fecho da tabela. Vale tanto o formato curto ("TOTAL  1.234,00")
# quanto o texto por extenso que muitos editais usam ("VALOR TOTAL ESTIMADO DA
# LICITAÇÃO: R$ ..."). É o que impede o texto posterior à tabela — observações,
# modelo de proposta, rodapé — de ser colado no último item.
_TOTAL_LINHA = re.compile(
    r"^\s*TOTAL\s*:?\s*(?:R\$)?\s*" + _MONEY + r"\s*$"
    r"|^\s*(?:VALOR\s+)?TOTAL\s+(?:GERAL|ESTIMADO|GLOBAL|DA\s+LICITA[ÇC][ÃA]O)"
    r"|^\s*OBSERVA[ÇC][ÕO]ES\s*:",
    re.I,
)

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
# Rótulo de regime de participação: abre o bloco de um item em editais que
# marcam a reserva por item (padrão ICS/Curitiba e derivados). Serve como
# fronteira estrutural — o texto que vem depois pertence ao PRÓXIMO item, e
# sem isso a descrição de um item invade a do vizinho.
# Início de descrição de item: muitos editais abrem o texto do produto com o
# código de catálogo seguido do nome ("138951 - PINÇA PROF°. MEDINA..."). Onde
# esse padrão se repete de forma consistente, ele marca com precisão onde um
# item termina e o próximo começa — informação que a distância até a âncora
# não dá quando os blocos têm tamanhos diferentes.
# Assinatura do layout "quantidade + preço unitário" (sem coluna de total):
# o último número da linha vem marcado com "R$" e o penúltimo não — porque o
# penúltimo é a QUANTIDADE, não dinheiro. Ex.:
#   "1 ABAIXADOR DE LÍNGUA ... PACOTE 4.940,00 R$ 6,11"
# Ler isso como (unitário, total) produziria quantidade zero e a conferência
# falharia em todas as linhas, que é exatamente como o erro aparece.
# Linha de valores SEM número de item, com o número no TOPO da descrição,
# algumas linhas acima (layout visto em Cascavel):
#   "19 SONDA GÁSTRICA LONGA LEVINE Nº 18- PARA"     <- número + início do texto
#   "SONDAGEM GÁSTRICA. ESTÉRIL, DESCARTÁVEL,"
#   "470,00 UND 1,75 822,50"                         <- qtd, unidade, valores
# A linha de valores é curta e só tem números e a unidade — sem isso,
# qualquer frase terminada em dois valores viraria âncora.
_VALORES_SEM_NUMERO = re.compile(
    r"^\s*([\d.]+(?:,\d+)?)\s+([A-Za-zÀ-ú]{1,10}\.?)\s+" + _RS + r"(" + _MONEY
    + r")\s+" + _RS + r"(" + _MONEY + r")\s*$"
)
_JANELA_NUMERO_ACIMA = 10

# Rótulos de agrupamento que NÃO reiniciam a numeração dos itens (em
# Cascavel os itens vão de 1 a 58 atravessando 12 lotes): só marcam fronteira,
# para o rótulo não grudar no último item do lote anterior.
#   "LOTE 2"   "GRUPO EXCLUSIVO ME EPP (LOTE 6,7,8 e 12 )"
#   "Valor total do lote 1: R$ 5.810,00 (cinco mil...)"
_ROTULO_GRUPO = re.compile(
    r"^\s*LOTE\s+\d+\s*$"
    r"|^\s*GRUPO\b.*\(\s*LOTES?\s*[\d,\se]+\)\s*$"
    r"|^\s*VALOR\s+TOTAL\s+DO\s+LOTE\s+\d+\s*:",
    re.I,
)

# Fim de descrição pelo código de catálogo: há editais em que toda descrição
# termina com o código BR do produto ("... CALIBRE Nº12 - BR 437443."). Onde
# isso se repete na maioria dos itens, a linha seguinte começa outro item —
# informação que a distância até a âncora não dá quando a descrição de cada
# item começa ACIMA da linha de valores.
_FIM_DESCRICAO = re.compile(
    r"\bBR\s*\d{5,7}\s*\.?\s*$"
    # Iguaraçu: toda descrição fecha com "UNIDADE DE FORNECIMENTO: ROLO"
    # (às vezes partido: "... UNIDADE DE" / "FORNECIMENTO: ROLO")
    r"|\bFORNECIMENTO\s*:\s*(?:\S[^:]{0,60})?$",
    re.I,
)

_SO_ULTIMO_COM_RS = re.compile(
    r"(?<!R\$)(?<!R\$\s)\b(" + _MONEY + r")\s+R\$\s*(" + _MONEY + r")\s*$"
)

_INICIO_DESCRICAO = re.compile(r"^\s*\d{4,7}\s*[-–—]\s*[A-Za-zÀ-ú]")

_REGIME_PARTICIPACAO = re.compile(
    r"^\s*(?:EXCLUSIV[OA]|AMPLA|COTA|RESERVAD[OA]|LOTE\s+RESERVADO)\b"
    r".{0,60}?(?:ME[I]?\s*/|ME/EPP|MEI|EPP|PARTICIPA[ÇC][ÃA]O|CONCORR[ÊE]NCIA)",
    re.I,
)

_NOISE = re.compile(
    # Palavras que também aparecem DENTRO de descrições ("...conforme anexo",
    # "a critério da contratante") só valem como ruído no início da linha;
    # soltas, elas apagariam texto legítimo do produto.
    r"(^\s*MUNIC[ÍI]PIO|Estado do Paran|^\s*ANEXO\b|^Item\b|^Und\b|^Fornecedor(?:es)?\b|^\d+\.\d"
    r"|CNPJ|e-mail|Telefone|^Rua |^\s*HAVENDO\b|OBJETO CONSTANTE|^\s*EDITAL\."
    r"|^\s*CONDI[ÇC][ÕO]ES GERAIS D[OA]S?\s+(?:PREG|EDITAL|CONTRAT|LICITA)|Registro de Pre|PREFEIT|ADVOGADO|^\s*CONTRATANTE\b"
    r"|^Valor Uni|^Valor Total|^M[ÉE]DIA(?:\s+ARITM[ÉE]TICA)?\s*(?:\(?R\$\)?)?\s*$|^PRODUTO(?:\s*/\s*SERVI[ÇC]O)?\s*$"
    # "PRODUTO"/"DESCRIÇÃO" só são cabeçalho quando vêm sozinhos ou seguidos
    # de outro rótulo de coluna; "PRODUTO ESTERILIZADO. TAMANHO 14 FR." é
    # descrição e não pode ser apagada.
    r"|^PRODUTO\s+(?:UNID|UN\b|QUANT|QTD|VALOR|MARCA|DESCRI|C[ÓO]D)"
    r"|^Descri[çc][ãa]o(?:\s+do\s+(?:objeto|produto|item|material)\S*|\s*)$"
    r"|^Descri[çc][ãa]o\s+(?:UNID|UN\b|QUANT|QTD|VALOR|MARCA|C[ÓO]D)"
    r"|P[áa]gina\s*:"
    # cabeçalho de tabela quebrado em duas linhas: "ITEM DESCRIÇÃO UND
    # Quantidade Valor" / "Total Unitário R$"
    r"|^Total\s+Unit[áa]rio|^Quantidade\s+Valor\b"
    # fragmento de cabeçalho partido em várias linhas: a linha inteira é só
    # de rótulos de coluna ("UNIT. (R$) (R$)", "PREÇO MÁXIMO PREÇO TOTAL")
    # Exige "(R$)" ou "PREÇO" na linha: sem essa marca, um "UNID." ou "TOTAL"
    # que sobrou sozinho da quebra de uma descrição seria apagado.
    r"|^(?=.*(?:\(R\$\)|PRE[ÇC]O))\s*(?:UNIT[ÁA]RIO|UNIT\.|\(R\$\)|R\$|PRE[ÇC]O"
    r"|M[ÁA]XIMO|TOTAL|VALOR|QTDE?\.?|UNID\.?|\s)+$"
    # fragmentos de cabeçalho de tabela quebrado em várias linhas pelo PDF
    # (ex.: "Nome do produto/serviço" vira "produto/se" + "rviço")
    r"|^produto/|^rvi[çc]o\b|^dade\s+m[áa]ximo|^servi[çc]o\b|ARITM[ÉE]TICA"
    # fragmentos do cabeçalho das fichas por lote (SESA/Curitiba), que o PDF
    # quebra em linhas soltas: "Exigências / complementar / es do item",
    # "Valor unitário / máximo / (CRITÉRIO DE / ACEITABILIDADE / DE PREÇOS)".
    r"|^es do item|ACEITABILIDADE|^\s*CRIT[ÉE]RIO DE|^complementar|^Exig[êe]ncias"
    r"|^Descri[çc][ãa]o do objeto|^Valor unit|^m[áa]ximo\s*$|^DE PRE[ÇC]OS\)"
    r"|^Lote\s+\d+\s+Descri)",
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
    # UNIDADE(S) por extenso vem antes das abreviações: sem ela, uma descrição
    # que cite "750 ML" no meio do texto teria o ML tomado como a unidade da
    # tabela, truncando tudo o que vem depois.
    # BOB(INA) e CR/CARTELA: unidades de fornecimento vistas em Guarapuava.
    r"\b(UNIDADES?|EMBALAGE(?:M|NS)|KITS?|BOB(?:INA)?S?|CR|CARTELAS?|CX|CAIXA|UNID|UND|UNI|UN|PCT|PC|PACOTE|ROLO|RL|LITRO|LT|EMB|FRASCO"
    r"|FRS|FR|PAR|KG|ML|MT|CONJ|BOLSA|GAL[ÃA]O|GL|BOMBA|AMPOLA|AMP|TB|DZ"
    # PEÇA: unidade padrão das fichas por lote da SESA/Curitiba.
    r"|PE[ÇC]AS?|PÇ"
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
    m_bruto = m  # antes de tirar o NÃO/SIM final (ver abaixo)
    m = re.sub(r"\s+(NÃO|SIM)\s*$", "", m, flags=re.I)  # flag de amostra
    # A unidade de fornecimento é o ÚLTIMO token de unidade do miolo (vem
    # logo antes da quantidade). Usar o primeiro quebraria descrições de
    # produtos que COMEÇAM com palavra-unidade (ex.: "BOLSA RESGATE ... UN 1").
    achados_unidade = list(_UNIDADE_RE.finditer(m))
    # Código de catálogo abrindo a descrição: "1 127 M CATMAT 460728 - TUBO".
    # O código marca com segurança onde a descrição começa, então a palavra
    # curta logo antes dele é a unidade — mesmo fora do vocabulário ("M" de
    # metro, que não pode entrar no vocabulário sem confundir "TAMANHO M").
    m_cat = re.match(
        r"^\s*(?:\d[\d.,]*\s+){1,2}([A-Za-zÀ-ú]{1,6}\.?)\s+((?:CATMAT|C[ÓO]D\.?\s*BR)\b.*)$",
        m_bruto, re.I)
    if m_cat:
        return m_cat.group(2).strip(), m_cat.group(1)
    # Ordem de colunas "quantidade | unidade | descrição" (Guarapuava):
    #   "1 4755 PCT CATMAT 481797 - LENÇOL"
    # Se antes da PRIMEIRA unidade só há números e depois dela há texto, a
    # descrição é o que vem depois. Sem isso o nome do produto ("LENÇOL") era
    # descartado — e, sem texto no miolo, as linhas vizinhas passavam a ser
    # distribuídas por proximidade, colando o fim de um item no seguinte.
    # Se mais adiante houver outra unidade seguida de quantidade (ou fechando
    # o miolo), ESSA é a coluna de unidade, e a primeira é só uma palavra da
    # descrição que coincide com unidade ("BOLSA COLETORA ... UNID 1.800 NÃO",
    # "CAIXA COLETORA ... CX 10"). Nesse caso as regras de "descrição depois
    # da unidade" não se aplicam.
    # Medidas ("50 L", "10 ML") são texto da descrição, nunca a coluna de
    # unidade — nem aqui, nem no início do miolo (ver abaixo).
    _MEDIDAS = {"L", "ML", "G", "KG", "MT", "LT", "LITRO"}
    # Unidade mais adiante seguida de QUANTIDADE ("UNID 1.800"): é a coluna,
    # sem dúvida — anula qualquer leitura de "descrição depois da unidade".
    coluna_adiante = any(
        re.match(r"\s*\d", m_bruto[u.end():])
        for u in achados_unidade[1:] if u.group(1).upper() not in _MEDIDAS
    )
    # Unidade mais adiante FECHANDO o miolo ("... COLETORA PARA ... CX"):
    # pode ser a coluna (Curiúva) ou só texto ("... PEDIATRICO - UNIDADE",
    # Iguaraçu). Ela só desempata contra a evidência fraca (números + palavra
    # de unidade no início); a evidência forte (unidade + quantidade no
    # início, "UN 100 CATETER...") prevalece sobre ela.
    unidade_no_fim = any(
        len(m_bruto) - u.end() <= 3
        for u in achados_unidade[1:] if u.group(1).upper() not in _MEDIDAS
    )
    if (achados_unidade and not coluna_adiante
            and achados_unidade[0].group(1).upper() not in _MEDIDAS):
        u0 = achados_unidade[0]
        # Aqui a descrição vem DEPOIS da unidade, então um "NÃO" final é parte
        # dela ("BATERIA NÃO RECARREGÁVEL"), não a coluna de amostra: usa-se o
        # miolo bruto. Tirá-lo invertia o sentido do produto.
        antes, depois = m[: u0.start()], m_bruto[u0.end():].strip()
        # exige números antes (a quantidade): "KIT PARTO ... - KIT" começa
        # pela própria palavra e não pode perder o "KIT" inicial
        if (not unidade_no_fim
                and re.search(r"\d", antes) and not re.search(r"[A-Za-zÀ-ú]", antes)
                and len(re.sub(r"[^A-Za-zÀ-ú]", "", depois)) >= 3):
            return depois, u0.group(1)
        # Ordem "unidade | quantidade | descrição" (Iguaraçu):
        #   "UN 20 SONDA ENDOTRAQUEAL DE PVC N° 2,0 SEM BALÃO"
        # Nada antes da unidade e, depois dela, um número (a quantidade)
        # seguido de texto. Exigir o número logo após a unidade é o que separa
        # este caso de "KIT PARTO ... - KIT", em que a palavra abre a descrição.
        m_qd = re.match(r"^\s*\d[\d.,]*\s+(.+)$", m_bruto[u0.end():])
        if (not antes.strip(" .-") and m_qd
                and len(re.sub(r"[^A-Za-zÀ-ú]", "", m_qd.group(1))) >= 3):
            return m_qd.group(1).strip(), u0.group(1)
    # A unidade de fornecimento é a coluna seguinte à descrição: no texto
    # linearizado ela cai no FIM do miolo. Palavras iguais que aparecem no meio
    # da frase ("...para EMBALAGEM lacrada...", "...750 ML...") são parte da
    # descrição e não podem truncá-la — por isso a preferência é por um achado
    # que termine junto com o miolo; só quando não há nenhum assim é que vale
    # a última ocorrência, para não regredir layouts com sobras após a unidade.
    um = None
    for achado in reversed(achados_unidade):
        if len(m) - achado.end() <= 3:
            um = achado
            break
    if um is None and achados_unidade:
        um = achados_unidade[-1]
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


def _forma_canonica(linha: str) -> str:
    """Forma de comparação de linhas de cabeçalho e rodapé.

    O mesmo cabeçalho chega com variações entre páginas: número de página,
    um símbolo solto ("® MUNICÍPIO DE ..."), espaços que o extrator ora
    preserva ora cola. Só letras minúsculas, com números trocados por "#",
    faz todas essas versões serem reconhecidas como a mesma linha.
    """
    s = re.sub(r"\d+", "#", linha.lower())
    so_letras = re.sub(r"[^a-zà-ú#]", "", s)
    # Linhas quase sem letras (traço de assinatura "______", "- 12 -") ficariam
    # vazias e deixariam de ser reconhecidas; para elas vale a forma literal.
    if len(so_letras.replace("#", "")) < 4:
        return re.sub(r"\s+", "", s)
    return so_letras


def _mobiliario_de_pagina(paginas_linhas: list[list[str]]) -> set[str]:
    """Identifica cabeçalho/rodapé repetidos (mobiliário de página).

    Editais carimbam todas as páginas com o mesmo bloco de cabeçalho (órgão,
    endereço, telefone, site) e rodapé (numeração, modelo da minuta). Quando um
    item atravessa a quebra de página, esse bloco cai **no meio da descrição**.

    A detecção não usa lista de palavras — que apagaria texto legítimo, já que
    descrições de produto contêm "produto", "registro", "validade" etc. Usa-se
    a combinação de duas evidências que o conteúdo real não tem:

    1. **posição fixa** — a linha aparece sempre entre as primeiras ou as
       últimas linhas da página; e
    2. **repetição** — aparece assim em boa parte das páginas do documento.

    Uma frase de descrição pode até se repetir entre itens parecidos, mas cai
    em posições variáveis; e uma linha de topo pode ser conteúdo, mas não se
    repete página após página. Exigir as duas evidências junta o que é seguro
    remover.
    """
    if len(paginas_linhas) < 3:
        return set()

    LIMIAR = 0.6                  # fração das páginas que precisa concordar
    MAX_FAIXA = 12                # teto de linhas de cabeçalho/rodapé
    n_pag = len(paginas_linhas)
    minimo = max(3, int(n_pag * LIMIAR))

    def _norm(ln: str) -> str:
        return _forma_canonica(ln)

    def _linha(pagina: list[str], k: int, do_fim: bool) -> str | None:
        # limita a faixa a 1/3 da página: em páginas curtas, cabeçalho e rodapé
        # não podem engolir o miolo.
        if len(pagina) < 6 or k >= max(1, len(pagina) // 3):
            return None
        try:
            return _norm(pagina[-(k + 1)] if do_fim else pagina[k])
        except IndexError:
            return None

    mobiliario: set[str] = set()
    for do_fim in (False, True):
        # Avança a partir da borda enquanto a linha daquela posição for a mesma
        # na maioria das páginas. Parar no primeiro desacordo garante que só
        # o bloco CONTÍGUO de borda seja removido — uma frase de descrição que
        # por acaso se repita no miolo nunca é alcançada.
        for k in range(MAX_FAIXA):
            contagem: dict[str, int] = {}
            for pagina in paginas_linhas:
                ln = _linha(pagina, k, do_fim)
                if ln and len(ln) >= 4:
                    contagem[ln] = contagem.get(ln, 0) + 1
            if not contagem:
                # Posição sem linha candidata (ex.: número de página sozinho,
                # "41"): não há evidência nem a favor nem contra — passa por
                # cima em vez de encerrar a busca. Sem isso, um rodapé logo
                # acima do número da página nunca seria alcançado.
                continue
            candidata, vezes = max(contagem.items(), key=lambda kv: kv[1])
            if vezes < minimo:
                break
            mobiliario.add(candidata)

    return mobiliario


def _eh_mobiliario(linha: str, mobiliario: set[str]) -> bool:
    return _forma_canonica(linha) in mobiliario


def _bordas_de_linha(pagina) -> list[float]:
    """Alturas das bordas que separam as LINHAS da tabela de itens.

    Uma tabela desenha muitos traços: bordas de célula, de coluna, de moldura.
    Só as que **começam na margem esquerda da tabela** atravessam a linha
    inteira e, por isso, marcam onde um item termina e o próximo começa. As
    demais são internas e dividiriam a descrição no meio.

    Devolve lista vazia quando a página não tem grade — aí valem as outras
    regras de fronteira.
    """
    try:
        bordas = pagina.horizontal_edges
    except Exception:  # noqa: BLE001
        return []
    if len(bordas) < 4:
        return []
    x_min = min(b["x0"] for b in bordas)
    ys = sorted({round(float(b["top"]), 1)
                 for b in bordas if abs(b["x0"] - x_min) < 3})
    limpos: list[float] = []
    for y in ys:
        if not limpos or y - limpos[-1] > 2:   # junta traços duplicados
            limpos.append(y)
    return limpos


def _marcar_por_bordas(tops: list[float], cortes: list[float]) -> list[bool]:
    """Marca as linhas de texto que abrem uma nova linha da tabela."""
    if not cortes or not tops:
        return []
    import bisect

    faixa_anterior = None
    marcas: list[bool] = []
    for top in tops:
        faixa = bisect.bisect_right(cortes, top + 1)
        marcas.append(faixa_anterior is not None and faixa != faixa_anterior)
        faixa_anterior = faixa
    return marcas


def _tokens_colados(textos: list[str]) -> int:
    """Conta "palavras" longas demais para serem uma palavra só.

    Em alguns PDFs o espaçamento entre palavras é tão justo que o extrator
    junta palavras vizinhas: "SONDAGEMGÁSTRICA.ESTÉRIL,DESCARTÁVEL,". Palavras
    reais da área raramente passam de 17 letras; um token bem maior, quase
    todo de letras, é sinal de espaços perdidos. Endereços (com "/" ou "@")
    ficam de fora.
    """
    n = 0
    for t in textos:
        for tok in t.split():
            if (len(tok) >= 18 and sum(c.isalpha() for c in tok) >= 14
                    and "/" not in tok and "@" not in tok):
                n += 1
    return n


def _tokens_picados(textos: list[str]) -> int:
    """Conta letras soltas — o efeito colateral de separar demais."""
    return sum(1 for t in textos for tok in t.split()
               if len(tok) == 1 and tok.isalpha() and tok.upper() not in "AEOÀÉ")


def _linhas_da_pagina(pagina):
    """Linhas de texto da página, recuperando espaços perdidos quando preciso.

    A tolerância padrão do extrator (3 pt) junta letras próximas numa mesma
    palavra e é o certo na maioria dos PDFs. Em alguns, de espaçamento
    apertado, ela cola palavras inteiras. Só nesses a página é relida com
    tolerância menor, e a releitura só é aceita se reduzir as palavras
    coladas sem passar a picotar palavras em letras soltas. Assim os editais
    que já saíam certos continuam exatamente iguais.
    """
    linhas = pagina.extract_text_lines()
    textos = [l["text"] for l in linhas]
    colados = _tokens_colados(textos)
    if colados < 2:
        return linhas
    try:
        alt = pagina.extract_text_lines(x_tolerance=1.5)
    except Exception:  # noqa: BLE001
        return linhas
    textos_alt = [l["text"] for l in alt]
    if (_tokens_colados(textos_alt) < colados
            and _tokens_picados(textos_alt) <= _tokens_picados(textos) + 2):
        return alt
    return linhas


def _coletar_linhas(reader, pagina_inicio: int, pagina_fim: int | None) -> list[str]:
    from hbi.modules.pdf_reader import sem_marca_dagua

    paginas = reader.paginas_indexadas(pagina_inicio, pagina_fim)

    from hbi.utils import cancelamento

    por_pagina: list[list[str]] = []
    tops_pagina: list[list[bool]] = []
    for pagina in paginas:
        # Ponto seguro de cancelamento: nada pela metade entre uma página e
        # a próxima, e é aqui que o tempo é gasto.
        cancelamento.checar()
        limpa = sem_marca_dagua(pagina)
        # Além do texto, guarda a posição vertical de cada linha. Em tabelas
        # onde a linha de valores fica NO MEIO do bloco (descrição acima e
        # abaixo dela), a distância até a âncora não diz a que item a linha
        # pertence — mas o espaçamento diz: dentro de um item o entrelinha é
        # regular, e entre um item e o seguinte há um salto maior.
        try:
            linhas_pos = _linhas_da_pagina(limpa)
            por_pagina.append([ln["text"].strip() for ln in linhas_pos])
            cortes = _bordas_de_linha(pagina)
            tops_pagina.append(
                _marcar_por_bordas([float(l["top"]) for l in linhas_pos], cortes)
            )
        except Exception:  # noqa: BLE001 — versões sem extract_text_lines
            texto = limpa.extract_text() or ""
            por_pagina.append([ln.strip() for ln in texto.split("\n")])
            tops_pagina.append([])
        # Libera o cache de objetos da página (chars, linhas, retângulos).
        # Sem isso o pdfplumber retém tudo até o fim do documento e o consumo
        # cresce linearmente com o número de páginas — o que estourava o
        # limite de memória de instâncias pequenas em editais longos.
        pagina.flush_cache()
        if hasattr(pagina, "close"):
            pagina.close()

    # Cabeçalho do documento todo e, além dele, o de cada trecho: editais
    # longos mudam de cabeçalho entre seções (edital, termo de referência,
    # anexos), e aí nenhuma linha se repete em 60% de TODAS as páginas —
    # mas se repete nas páginas vizinhas.
    mobiliario = _mobiliario_de_pagina(por_pagina)
    JANELA = 5
    mob_local: list[set[str]] = []
    for i in range(len(por_pagina)):
        viz = por_pagina[max(0, i - JANELA): i + JANELA + 1]
        mob_local.append(_mobiliario_de_pagina(viz) if len(viz) >= 6 else set())
    if mobiliario:
        log.info("Cabeçalho/rodapé de página detectado: %d linhas ignoradas.",
                 len(mobiliario))

    linhas: list[str] = []
    for offset, linhas_pg in enumerate(por_pagina):
        pagina = pagina_inicio + offset + 1  # rastreabilidade (1-based)
        marcas = tops_pagina[offset] if offset < len(tops_pagina) else []
        novos = {i for i, m in enumerate(marcas) if m}
        for idx_pg, ln in enumerate(linhas_pg):
            # Linhas que dão estrutura à tabela (cabeçalho de colunas, lote,
            # total, regime) nunca saem, mesmo repetidas: elas servem de
            # fronteira entre itens, e removê-las mudaria a montagem das
            # descrições em editais que já saem certos.
            estrutural = (_eh_cabecalho_tabela(ln) or _LOTE.match(ln)
                          or _TOTAL_LINHA.match(ln) or _REGIME_PARTICIPACAO.match(ln))
            if not estrutural and (_eh_mobiliario(ln, mobiliario)
                                   or _eh_mobiliario(ln, mob_local[offset])):
                continue
            linhas.append((ln, pagina, idx_pg in novos))
    return linhas


def _decidir_topos_de_pagina(topos, aidx, linhas, cortes) -> set[int]:
    """Decide se a primeira linha de uma página começa um item ou continua um.

    No topo de cada página a tabela ganha uma borda, então a marca de "início
    de linha da tabela" ali é ambígua: o texto pode ser a continuação do item
    que a quebra de página cortou (CIGAMERIOS: "APRESENTAR AMOSTRA") ou o
    começo do item seguinte (Iguaraçu: "EMBALAGEM P/ ESTERILIZAÇÃO...").

    O desempate usa a geometria das tabelas desses editais: o número do item
    fica centralizado verticalmente no seu bloco. Se o item de cima já tem,
    abaixo do número, pelo menos tantas linhas quantas tem acima, o bloco está
    completo e a linha do topo começa outro item. Se tem menos, o bloco foi
    cortado pela quebra de página e a linha é continuação.
    """
    import bisect

    aceitos: set[int] = set()
    texto = lambda j: bool(linhas[j].strip()) and not _NOISE.search(linhas[j])
    for t in sorted(topos):
        pos = bisect.bisect_left(aidx, t)
        if pos == 0:
            continue
        a = aidx[pos - 1]
        anterior = aidx[pos - 2] if pos >= 2 else -1
        # Só dá para medir o equilíbrio se o início do bloco for conhecido por
        # evidência (marcador de fim do item anterior, marcador de início ou
        # borda). Sem isso, contar a partir do item anterior somaria as linhas
        # de continuação DELE como se fossem deste — e o topo de página seria
        # tomado por início de item quando é continuação.
        conhecidos = [c for c in cortes if anterior < c <= a]
        if not conhecidos:
            continue
        inicio = max(conhecidos)
        acima = sum(1 for j in range(inicio, a) if texto(j))
        abaixo = sum(1 for j in range(a + 1, t) if texto(j))
        # O critério só vale no layout centralizado (há texto ACIMA do número).
        # Quando a descrição começa na própria linha do número (CIGAMERIOS),
        # não há o que equilibrar: o topo da página é continuação, e o item
        # seguinte começa na linha do seu próprio número.
        if acima >= 1 and abaixo >= acima:
            aceitos.add(t)
    return aceitos


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
    # Linhas que abrem um novo item segundo o espaçamento vertical da página.
    # Ausente quando as linhas vêm sem posição (ex.: chamadas de teste).
    # A primeira linha de cada página nunca conta como início de item: a borda
    # ali é o topo da tabela, e o texto costuma ser a continuação do item que
    # transbordou da página anterior.
    inicios_espaco = {
        i for i, lp in enumerate(linhas_pag)
        if len(lp) > 2 and lp[2] and (i == 0 or lp[1] == linhas_pag[i - 1][1])
    }
    # Marcas na primeira linha de página ficam em espera: decididas depois,
    # quando as âncoras forem conhecidas (ver _decidir_topos_de_pagina).
    topos_marcados = {
        i for i, lp in enumerate(linhas_pag)
        if len(lp) > 2 and lp[2] and i > 0 and lp[1] != linhas_pag[i - 1][1]
    }
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
    linhas_qtd_preco = 0
    lote_atual: int | None = None
    consumidas_invertido: set[int] = set()  # linhas já usadas por âncora invertida
    for idx, ln in enumerate(linhas):
        m_lote = _LOTE.match(ln)
        if m_lote:
            lote_atual = int(m_lote.group(1) or m_lote.group(2))
            esperado = 1  # a numeração de item recomeça dentro do lote
            continue
        # Número no TOPO da descrição e valores numa linha própria abaixo.
        # Testado antes da âncora padrão, que leria "470,00 UND 1,75 822,50"
        # como item 470 e descartaria a linha. Só vale se uma linha acima
        # começar exatamente pelo próximo número esperado — a contagem
        # incremental impede confundir um número do texto ("Nº 18") com o item.
        m_vs = _VALORES_SEM_NUMERO.match(ln)
        if m_vs:
            achou = None
            for k in range(idx - 1, max(-1, idx - 1 - _JANELA_NUMERO_ACIMA), -1):
                if any(a[0] == k for a in anchors[-3:]) or _LOTE.match(linhas[k]):
                    break  # não atravessa outro item nem início de lote
                m_num = _NUMERO_INICIO.match(linhas[k])
                if m_num and int(m_num.group(1)) == esperado:
                    achou = (k, int(m_num.group(1)))
                    break
            if achou:
                k, num = achou
                # o número sai da linha de texto: ela é descrição
                linhas[k] = _NUMERO_INICIO.match(linhas[k]).group(2)
                anchors.append(
                    (idx, num, f"{m_vs.group(1)} {m_vs.group(2)}",
                     _to_float(m_vs.group(3)), _to_float(m_vs.group(4)),
                     paginas[idx], lote_atual)
                )
                esperado = num + 1
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
            if _SO_ULTIMO_COM_RS.search(ln):
                linhas_qtd_preco += 1
            esperado = num + 1

    if not anchors:
        log.info(
            "Nenhuma âncora de tabela encontrada; tentando itens em blocos de texto."
        )
        itens_blocos = extrair_itens_blocos(reader)
        if itens_blocos:
            return itens_blocos
        log.warning("Nenhuma âncora de item encontrada nas páginas varridas.")
        return []

    # 2) Fronteiras estruturais: cabeçalho de tabela, linha de TOTAL, início
    #    de lote e rótulo de regime de participação delimitam blocos. Elas
    #    impedem que uma linha de descrição "vaze" de um item para outro (ou do
    #    texto introdutório para o item 1).
    fronteiras = {
        i for i, ln in enumerate(linhas)
        if _LOTE.match(ln) or _TOTAL_LINHA.match(ln) or _eh_cabecalho_tabela(ln)
        or _REGIME_PARTICIPACAO.match(ln)
        or _ROTULO_GRUPO.match(ln)
    }

    # Inícios de descrição só valem como corte quando o padrão se repete o
    # bastante para ser a estrutura do documento, e não uma coincidência: um
    # código solto no meio de um texto não pode partir a descrição em duas.
    inicios_bloco = {
        i for i, ln in enumerate(linhas) if _INICIO_DESCRICAO.match(ln)
    }
    if len(inicios_bloco) < max(2, int(len(anchors) * 0.6)):
        inicios_bloco = set()
    fins = {i + 1 for i, ln in enumerate(linhas[:-1]) if _FIM_DESCRICAO.search(ln)}
    regime_fim = len(fins) >= max(2, int(len(anchors) * 0.6))
    if regime_fim:
        inicios_bloco = inicios_bloco | fins
        log.info("Fim de descrição pelo código de catálogo: %d cortes.", len(fins))
    else:
        log.info("Início de descrição detectado em %d linhas (corte de bloco).",
                 len(inicios_bloco))

    # As bordas da tabela são evidência independente do texto e valem mesmo
    # sem marcador textual — que é justamente o caso em que a âncora fica no
    # meio do bloco e a proximidade sozinha erra o dono da linha.
    # Salvaguarda: em alguns PDFs a grade tem uma borda por LINHA DE TEXTO,
    # não por item. Nesse caso os cortes picotariam cada descrição em pedaços.
    # Um conjunto de cortes coerente tem cardinalidade próxima à de itens —
    # bem mais que isso denuncia grade por linha, e aí a evidência é
    # descartada em favor das outras regras.
    # A salvaguarda mede só os cortes comuns: os de topo de página são poucos
    # e decididos à parte, e somá-los antes fazia a salvaguarda descartar
    # TODOS os cortes de um edital válido.
    if inicios_espaco and len(inicios_espaco) <= len(anchors) * 1.5:
        if topos_marcados:
            inicios_espaco = inicios_espaco | _decidir_topos_de_pagina(
                topos_marcados, [a[0] for a in anchors], linhas,
                inicios_bloco | inicios_espaco)
        inicios_bloco = inicios_bloco | inicios_espaco
        log.info("Cortes por borda de tabela: %d.", len(inicios_espaco))
    elif inicios_espaco:
        log.info("Bordas de tabela ignoradas (%d cortes para %d itens: grade "
                 "por linha de texto).", len(inicios_espaco), len(anchors))

    def _mesma_secao(a: int, b: int) -> bool:
        """True se ``a`` (âncora) e ``b`` (linha) pertencem ao mesmo item.

        Duas coisas separam: fronteiras estruturais (cabeçalho, TOTAL, lote,
        regime) e o início de uma nova descrição. A diferença é sutil: a
        fronteira fica ENTRE os dois blocos e não pertence a nenhum, enquanto
        o início de descrição É a primeira linha do bloco novo — por isso ele
        entra na comparação com ``<=`` do lado da linha.
        """
        ini, fim = (a, b) if a < b else (b, a)
        if any(f for f in fronteiras if ini < f < fim):
            return False
        # um corte em c joga tudo a partir de c para o bloco seguinte
        return not any(c for c in inicios_bloco if ini < c <= fim)

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
    orfas_reatadas = 0
    fim_ultimo = None
    if regime_fim:
        for j in range(ultima_ancora + 1, min(len(linhas), ultima_ancora + 61)):
            if _FIM_DESCRICAO.search(linhas[j]):
                fim_ultimo = j
                break
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
        # Depois da última âncora vale uma janela curta (o que vem a seguir
        # costuma ser o corpo do edital). Mas, se o edital fecha cada descrição
        # com um marcador ("UNIDADE DE FORNECIMENTO: ..."), o último item vai
        # até o marcador — senão uma descrição longa era cortada no meio.
        if (i > ultima_ancora and i - ultima_ancora > janela_borda
                and not (fim_ultimo is not None and i <= fim_ultimo)):
            continue

        # Dentro da tabela, o bloco de descrição é delimitado pelas âncoras
        # vizinhas e pelas fronteiras estruturais — sem limite de linhas,
        # porque o tamanho do bloco varia muito conforme a largura da coluna
        # (de ~5 linhas por item a ~30 em editais de coluna estreita).
        pos = bisect.bisect_left(aidx, i)
        candidatos = []
        if pos > 0:
            candidatos.append(pos - 1)          # âncora acima
        if pos < len(aidx):
            # A âncora abaixo entra sempre que o modo não for "avante"; e,
            # mesmo no modo avante, quando a âncora de cima está separada por
            # uma fronteira estrutural — nesse caso a linha abre o bloco do
            # próximo item (ex.: ICS, onde a descrição começa acima da âncora,
            # logo após o rótulo de regime de participação).
            acima_isolada = pos == 0 or not _mesma_secao(aidx[pos - 1], i)
            if not modo_avante or acima_isolada:
                candidatos.append(pos)          # âncora abaixo
        melhor, bk = 10**9, None
        for k in candidatos:
            if not _mesma_secao(aidx[k], i):
                continue
            d = abs(aidx[k] - i)
            if d < melhor:
                melhor, bk = d, k
        if bk is None and pos > 0 and primeira_ancora < i < ultima_ancora:
            # Linha órfã DENTRO da tabela: os cortes de bloco a isolaram tanto
            # do item de cima quanto do de baixo. Antes ela era descartada em
            # silêncio — e linhas do meio de descrições longas sumiam sem
            # nenhum alerta. Texto do edital nunca é jogado fora: fica com o
            # item de cima, como continuação, desde que nenhuma fronteira
            # estrutural (cabeçalho, total, lote) separe os dois.
            k_acima = pos - 1
            if not any(f for f in fronteiras if aidx[k_acima] < f < i):
                bk = k_acima
                orfas_reatadas += 1
        if bk is not None:
            desc[bk].append((i, ln))
    if orfas_reatadas:
        log.info("Linhas órfãs reatadas ao item anterior: %d.", orfas_reatadas)

    # 4) monta os itens
    #
    # Layout "quantidade + preço unitário": a tabela não traz coluna de total,
    # e os dois últimos números da linha são a QUANTIDADE e o PREÇO. Só é
    # adotado quando a assinatura aparece na ampla maioria das linhas — um
    # "R$" solto numa linha isolada não pode mudar a leitura do edital todo.
    modo_qtd_preco = linhas_qtd_preco >= max(3, len(anchors) * 0.7)
    if modo_qtd_preco:
        log.info("Layout com coluna de quantidade e preço unitário (sem total): "
                 "%d de %d linhas.", linhas_qtd_preco, len(anchors))

    usa_lotes = any(a[6] is not None for a in anchors)
    itens: list[ItemEdital] = []
    for k, (idx, num, miolo, vunit, vtot, pagina, lote) in enumerate(anchors):
        if modo_qtd_preco:
            # o penúltimo número era a quantidade; o último, o preço unitário
            quantidade, vunit, vtot = vunit, vtot, round(vunit * vtot, 2)
        else:
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


# =============================================================================
# Estratégia B — itens em BLOCOS DE TEXTO (edital sem tabela de itens)
# =============================================================================
# Alguns editais (padrão FEAS/Curitiba) não trazem tabela alguma: cada item é
# um bloco de texto corrido, com rótulo próprio e os dados em linhas rotuladas.
#
#   Item 2: 66376/ BR0619857/ Luva para Procedimento em Látex Tamanho P
#   Luva de procedimento P, não cirúrgica, em látex natural ...
#   Quantidade: 2.400.000 unidades
#   Valor máximo permitido: R$ 0,2200
#
# Aqui não existe valor total impresso: ele é derivado de qtd × unitário. Por
# isso a conferência automática não é evidência independente nesses editais —
# o gate de extração se apoia na sequência 1..N.

_BLOCO_ITEM = re.compile(r"^Item\s+(\d+)\s*:?\s*(.*)$", re.I)
_BLOCO_QTD = re.compile(
    r"^Quantidade(?:\s+estimada|\s+total)?\s*:\s*([\d.]+(?:,\d+)?)\s*([A-Za-zÀ-ú]+)?",
    re.I,
)
_BLOCO_VALOR = re.compile(
    r"^Valor\s+(?:m[áa]ximo(?:\s+permitido|\s+unit[áa]rio)?|unit[áa]rio(?:\s+m[áa]ximo)?"
    r"|estimado|de\s+refer[êe]ncia)\s*:?\s*R?\$?\s*(" + _MONEY + r")",
    re.I,
)


def _to_float_qtd(txt: str) -> float:
    """Converte quantidade em formato brasileiro ('2.400.000', '1.500,5')."""
    t = txt.strip()
    if "," in t:
        return float(t.replace(".", "").replace(",", "."))
    return float(t.replace(".", ""))


def extrair_itens_blocos(reader) -> list[ItemEdital]:
    """Extrai itens dispostos como blocos de texto rotulados (sem tabela).

    Cada bloco vai do seu rótulo ``Item N:`` até o rótulo seguinte. Dentro do
    bloco, procura-se a quantidade e o valor unitário em linhas rotuladas; a
    descrição é o texto entre o rótulo e essas linhas.

    Returns:
        Lista de :class:`ItemEdital`, ou lista vazia se o documento não segue
        este formato.
    """
    linhas_pag = _coletar_linhas(reader, 0, None)
    linhas = [lp[0] for lp in linhas_pag]
    paginas = [lp[1] for lp in linhas_pag]

    # 1) Âncoras de bloco, com contagem incremental (rejeita "Item 5" citado
    #    em cláusulas do edital, que não seguem a sequência).
    ancoras: list[tuple[int, int, str]] = []  # idx, numero, resto do rótulo
    esperado = 1
    for i, ln in enumerate(linhas):
        m = _BLOCO_ITEM.match(ln)
        if not m:
            continue
        num = int(m.group(1))
        if esperado <= num <= esperado + _SALTO_MAXIMO:
            ancoras.append((i, num, m.group(2).strip()))
            esperado = num + 1

    if len(ancoras) < 2:
        return []

    # 2) Cada bloco vai até a âncora seguinte (o último, até o fim do texto).
    itens: list[ItemEdital] = []
    for k, (idx, num, titulo) in enumerate(ancoras):
        fim = ancoras[k + 1][0] if k + 1 < len(ancoras) else len(linhas)
        quantidade = unidade = None
        valor = None
        corpo: list[str] = []
        for j in range(idx + 1, fim):
            ln = linhas[j]
            mq = _BLOCO_QTD.match(ln)
            if mq:
                quantidade = _to_float_qtd(mq.group(1))
                unidade = (mq.group(2) or "").strip()
                continue
            mv = _BLOCO_VALOR.match(ln)
            if mv:
                valor = _to_float(mv.group(1))
                continue
            # O filtro _NOISE existe para cabeçalhos de TABELA e não pode ser
            # aplicado aqui: ele casa palavras soltas ("produto", "descrição",
            # "registro") que aparecem legitimamente no meio de uma descrição
            # de produto — apagá-las mutilaria o texto do edital. Nos blocos, o
            # cabeçalho/rodapé de página já foi removido em ``_coletar_linhas``.
            if len(ln) < 3:
                continue
            corpo.append(ln)

        # O valor pode cair logo ANTES do rótulo seguinte, já na página nova,
        # depois do rodapé — nesse caso ele foi consumido acima. Se ainda
        # faltar, procura na janela imediatamente após o fim do bloco.
        if valor is None:
            for j in range(fim, min(fim + 6, len(linhas))):
                mv = _BLOCO_VALOR.match(linhas[j])
                if mv:
                    valor = _to_float(mv.group(1))
                    break

        if quantidade is None or valor is None:
            log.warning("Item %s sem quantidade ou valor identificável.", num)
            continue

        descricao = normalizar_espacos(" ".join([titulo] + corpo))
        itens.append(
            ItemEdital(
                item=num,
                descricao=descricao,
                unidade=unidade or "",
                quantidade=quantidade,
                valor_estimado=valor,
                # Sem total impresso: derivado de qtd × unitário.
                valor_total=round(quantidade * valor, 2),
                pagina=paginas[idx],
            )
        )

    log.info("Itens extraídos: %d (blocos de texto rotulados)", len(itens))
    return itens


def _completude(itens) -> float:
    """Fração da sequência 1..N que foi realmente extraída."""
    if not itens:
        return 0.0
    nums = {i.item for i in itens}
    return len(nums) / max(nums)


_RS_SOLTO = re.compile(r"(?<!\S)R\$(?=\s|$)(?!\s*\d)")


def _limpar_rs_solto(itens):
    """Remove "R$" isolado das descrições.

    Quando o preço é partido entre linhas, o "R$" fica numa linha de texto e
    o valor noutra. O valor é recuperado pela regra de valor quebrado, mas o
    "R$" sobrava no meio da descrição ("...UNIDADE DE R$ FORNECIMENTO").
    Só sai o símbolo sem número colado, então "R$ 10,00" escrito numa
    descrição continua intacto.
    """
    for it in itens:
        if "R$" in it.descricao:
            it.descricao = normalizar_espacos(_RS_SOLTO.sub(" ", it.descricao))
    return itens


def melhor_extracao(reader, caminho=None):
    """Extrai os itens escolhendo a estratégia que der o resultado mais íntegro.

    A leitura por âncoras resolve a maioria dos editais, mas alguns PDFs
    entrelaçam as colunas ao achatar o texto — e aí a sequência de itens sai
    com buracos. Nesses casos, quando o PDF desenha a tabela, ler as células
    da grade recupera o que faltou.

    A decisão não é por tipo de arquivo nem por nome de órgão: roda-se a
    estratégia padrão e, se a sequência ficou incompleta, compara-se com a
    leitura por grade — fica a que cobre mais itens e tem menos divergências.
    """
    itens = _limpar_rs_solto(extrair_itens(reader))
    cobertura = _completude(itens)
    if cobertura >= 0.995 or caminho is None:
        return itens, {}

    try:
        from hbi.modules.grid_extractor import extrair_por_grade
        por_grade, extras = extrair_por_grade(caminho)
    except Exception as exc:  # noqa: BLE001
        log.warning("Leitura por grade indisponível (%s).", exc)
        return itens, {}

    # As duas leituras precisam ser medidas contra a MESMA régua: a maior
    # numeração vista por qualquer uma delas. Medir cada uma contra a própria
    # sequência é armadilha — uma grade que só reconheceu uma tabela pequena
    # (itens 1 a 9) teria "100%" e venceria uma leitura de 55 de 58 itens,
    # descartando dezenas de itens sem nenhum aviso.
    nums_a = {i.item for i in itens}
    nums_g = {i.item for i in por_grade}
    referencia = max(nums_a | nums_g, default=0)
    if not referencia:
        return itens, {}
    cob_a = len(nums_a) / referencia
    cob_g = len(nums_g) / referencia
    if cob_g > cob_a:
        log.info(
            "Leitura por grade adotada: %d itens (%.0f%% de 1..%d) contra "
            "%d (%.0f%%) por âncoras.",
            len(nums_g), cob_g * 100, referencia, len(nums_a), cob_a * 100,
        )
        return por_grade, extras
    log.info(
        "Leitura por âncoras mantida: %d itens (%.0f%% de 1..%d); a grade "
        "reconheceu %d.", len(nums_a), cob_a * 100, referencia, len(nums_g),
    )
    return itens, {}

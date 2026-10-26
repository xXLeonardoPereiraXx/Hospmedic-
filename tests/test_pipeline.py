"""Testes de fumaça do pipeline HBI.

Não usam framework externo (mantendo o MVP enxuto): rodam com
``python tests/test_pipeline.py`` e falham com AssertionError se algo quebrar.
Requerem um PDF de edital em ``data/input/`` para o teste de integração.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbi.modules import edital_validator
from hbi.models.edital import ItemEdital
from hbi.utils.text import brl_para_float, float_para_brl


def test_conversao_brl():
    assert brl_para_float("1.256,00") == 1256.0
    assert brl_para_float("70.200,00") == 70200.0
    assert brl_para_float("6,28") == 6.28
    assert float_para_brl(801434.08) == "801.434,08"
    print("ok  test_conversao_brl")


def test_confere_total():
    it = ItemEdital(1, "x", "un", 200, 6.28, 1256.00, 1)
    assert it.confere_total()
    it_bad = ItemEdital(2, "y", "un", 200, 6.28, 9999.0, 1)
    assert not it_bad.confere_total()
    print("ok  test_confere_total")


def test_validacao_go_nogo():
    texto = (
        "LICITAÇÃO EXCLUSIVA PARA ME, EPP. Deverá ser apresentada AFE expedida "
        "pela ANVISA. O critério será o de MENOR PREÇO POR ITEM, modo de disputa "
        "ABERTO. Exige-se SICAF e amostra."
    )
    r = edital_validator.validar(texto)
    nomes_presentes = {c.nome for c in r.criterios if c.presente}
    assert "AFE – Autorização de Funcionamento (ANVISA)" in nomes_presentes
    assert "Julgamento por menor preço por item" in nomes_presentes
    assert "SICAF" in nomes_presentes
    assert r.veredito in {"go", "revisar", "no_go"}
    print(f"ok  test_validacao_go_nogo (veredito={r.veredito})")


def test_metadados():
    texto = "O MUNICÍPIO DE XAMBRÊ ... EDITAL DE PREGÃO (ELETRÔNICO) SRP N° 10/2026"
    m = edital_validator.detectar_metadados(texto)
    assert m["numero_pregao"] == "PE 10/2026", m
    assert m["orgao"] and "Xambr" in m["orgao"], m
    print("ok  test_metadados")



# --- Descritivos técnicos em seção separada (spec_extractor) ----------------
def test_descritivos_por_lote():
    """Edital indexado por LOTE, com rótulo cobrindo dois lotes de uma vez."""
    from hbi.modules import spec_extractor
    from hbi.models.edital import ItemEdital

    texto = "\n".join([
        "1.2 ESPECIFICACOES TECNICAS",
        "LOTES 1 E 2: SERINGA DESCARTAVEL 20 ml",
        "Seringa descartavel de 20ml luer slip, sem agulha, em polipropileno atoxico.",
        "LOTE 3 e 4: DOSADOR ORAL 5ml",
        "Dosador oral de uso unico, cilindro translucido graduado em mililitros.",
        "1.2.1 Requisitos da contratacao:",
        "Produtos sustentaveis sob os aspectos socioambientais.",
    ])
    tipo, d = spec_extractor.extrair_descritivos(texto)
    assert tipo == "lote", tipo
    assert sorted(d) == [1, 2, 3, 4], sorted(d)
    assert "polipropileno" in d[2]
    assert "Requisitos da contratacao" not in d[4]  # fim de secao respeitado

    itens = [ItemEdital(item=1, descricao="SERINGA", unidade="PECA", quantidade=10,
                        valor_estimado=1.0, valor_total=10.0, pagina=1, lote=n)
             for n in (1, 2, 3, 4)]
    diag = spec_extractor.aplicar_descritivos(itens, tipo, d)
    assert diag["itens_enriquecidos"] == 4, diag
    assert not diag["descritivos_orfaos"]
    assert "luer slip" in itens[0].descricao
    print("ok  test_descritivos_por_lote")


def test_descritivos_por_item():
    """Edital com itens soltos: o join usa o numero do item, nao o lote."""
    from hbi.modules import spec_extractor
    from hbi.models.edital import ItemEdital

    texto = "\n".join([
        "ESPECIFICACOES TECNICAS",
        "ITEM 1: AGULHA HIPODERMICA",
        "Agulha hipodermica em aco inoxidavel siliconizado, bisel trifacetado.",
        "ITENS 2 E 3: COMPRESSA DE GAZE",
        "Compressa de gaze hidrofila, 13 fios, esteril, embalagem individual.",
    ])
    tipo, d = spec_extractor.extrair_descritivos(texto)
    assert tipo == "item", tipo
    assert sorted(d) == [1, 2, 3], sorted(d)

    itens = [ItemEdital(item=n, descricao="", unidade="UN", quantidade=5,
                        valor_estimado=2.0, valor_total=10.0, pagina=1)
             for n in (1, 2, 3, 4)]
    diag = spec_extractor.aplicar_descritivos(itens, tipo, d)
    assert diag["itens_enriquecidos"] == 3, diag
    assert diag["itens_sem_descritivo"] == [4], diag
    assert "bisel trifacetado" in itens[0].descricao
    print("ok  test_descritivos_por_item")


def test_sem_descritivos_separados():
    """Edital cuja tabela ja traz a descricao completa nao e alterado."""
    from hbi.modules import spec_extractor
    from hbi.models.edital import ItemEdital

    tipo, d = spec_extractor.extrair_descritivos(
        "1 OBJETO\nAquisicao de materiais hospitalares conforme tabela."
    )
    assert tipo is None and d == {}
    itens = [ItemEdital(item=1, descricao="GAZE", unidade="CX", quantidade=1,
                        valor_estimado=5.0, valor_total=5.0, pagina=1)]
    diag = spec_extractor.aplicar_descritivos(itens, tipo, d)
    assert itens[0].descricao == "GAZE"
    assert diag["itens_enriquecidos"] == 0
    print("ok  test_sem_descritivos_separados")



def test_itens_em_blocos():
    """Edital sem tabela: itens como blocos rotulados (padrao FEAS/Curitiba)."""
    from hbi.modules import table_extractor as te

    linhas = [
        "Item 1: 222485 /BR0619856/ Luva para Procedimento em Latex PP",
        "Luva de procedimento PP, nao cirurgica, em latex natural.",
        "Quantidade: 30.000 unidades",
        "Valor maximo permitido: R$ 0,2170",
        "Item 2: 66376/ BR0619857/ Luva para Procedimento em Latex P",
        "Luva de procedimento P, nao cirurgica, em latex natural.",
        "Quantidade: 2.400.000 unidades",
        "Valor maximo permitido: R$ 0,2200",
    ]

    class _FakeReader:
        """Stub minimo: o extrator so precisa das linhas ja coletadas."""

    original = te._coletar_linhas
    te._coletar_linhas = lambda *a, **k: [(ln, 1) for ln in linhas]
    try:
        itens = te.extrair_itens_blocos(_FakeReader())
    finally:
        te._coletar_linhas = original

    assert len(itens) == 2, len(itens)
    assert itens[0].quantidade == 30000.0 and itens[0].unidade == "unidades"
    assert abs(itens[0].valor_estimado - 0.2170) < 1e-9
    assert abs(itens[0].valor_total - 6510.00) < 0.01, itens[0].valor_total
    assert itens[1].quantidade == 2400000.0
    assert "latex natural" in itens[1].descricao
    print("ok  test_itens_em_blocos")



def test_mobiliario_de_pagina():
    """Cabecalho/rodape repetido sai; texto de descricao permanece intacto."""
    from hbi.modules import table_extractor as te

    cabecalho = ["EDITAL - PREGAO 70/2026", "Feas", "R. Cap. Argemiro, 161"]
    rodape = ["Pagina 1 | 68", "Edital modelo - Lei 14.133"]
    # a mesma frase de descricao se repete entre itens, mas no MEIO da pagina:
    frase = "resistente de forma a assegurar a protecao do produto ate o uso"
    paginas = []
    for n in range(6):
        # pagina realista: cabecalho + miolo longo + rodape
        corpo = [f"Item {n+1}: Luva modelo {chr(65+n)}", frase]
        corpo += [f"caracteristica {chr(97+k)} do modelo {chr(65+n)}" for k in range(28)]
        corpo += ["Quantidade: 100 caixas"]
        paginas.append(cabecalho + corpo + [f"Pagina {n+1} | 68", rodape[1]])

    mob = te._mobiliario_de_pagina(paginas)
    assert te._eh_mobiliario("Feas", mob), "cabecalho deveria ser detectado"
    assert te._eh_mobiliario("Pagina 3 | 68", mob), "rodape numerado deveria ser detectado"
    assert not te._eh_mobiliario(frase, mob), "descricao repetida NAO pode ser removida"
    print("ok  test_mobiliario_de_pagina")


def test_noise_nao_apaga_descricao():
    """O filtro de cabecalho de TABELA nao pode ser aplicado a descricoes."""
    from hbi.modules import table_extractor as te

    linhas = [
        "Item 1: Luva para procedimento M - vinil",
        "Embalagem: caixa dispenser box com 100 unidades, possuindo abertura",
        "uma a uma; resistente de forma a assegurar a protecao do produto ate o momento",
        "com identificacao de procedencia, numero de lote e registro no ministerio",
        "Quantidade: 2.000 caixas",
        "Valor maximo permitido: R$ 13,7000",
        "Item 2: Luva para procedimento G - vinil",
        "Luva em vinil flexivel, sem talco, ambidestra.",
        "Quantidade: 1.000 caixas",
        "Valor maximo permitido: R$ 14,7474",
    ]

    class _FakeReader:
        pass

    original = te._coletar_linhas
    te._coletar_linhas = lambda *a, **k: [(ln, 1) for ln in linhas]
    try:
        itens = te.extrair_itens_blocos(_FakeReader())
    finally:
        te._coletar_linhas = original

    assert len(itens) == 2, len(itens)
    # a linha com a palavra "produto" era apagada pelo filtro de tabela
    assert "assegurar a protecao do produto" in itens[0].descricao, itens[0].descricao
    assert "registro no ministerio" in itens[0].descricao
    print("ok  test_noise_nao_apaga_descricao")



def test_fronteira_regime_participacao():
    """Rotulo de regime separa itens: a descricao nao invade o vizinho."""
    from hbi.modules import table_extractor as te

    # cada item abre com o rotulo de regime; a ancora fica no MEIO do bloco,
    # com descricao acima e abaixo dela (layout ICS/Curitiba).
    linhas = [
        "ORD DESCRICAO DOS PRODUTOS QUANTIDADE VALOR UNITARIO VALOR TOTAL",
        "EXCLUSIVO MEI/ME/EPP",
        "BANDAGEM INELASTICA TIPO BOTA DE UNNA, COMPOSTA POR",
        "1 HIDRATANTE NAO IONICO. UNIDADE 180 R$ 46,45 R$ 8.361,00",
        "INDICADA PARA ULCERAS VENOSAS E EDEMAS.",
        "EXCLUSIVO MEI/ME/EPP",
        "CURATIVO AUTOADERENTE, ATRAUMATICO, RECORTAVEL,",
        "2 COMPOSTO POR 3 CAMADAS. UNIDADE 240 R$ 80,00 R$ 19.200,00",
        "ESPUMA ABSORVENTE DE POLIURETANO.",
    ]

    class _FakeReader:
        pass

    original = te._coletar_linhas
    te._coletar_linhas = lambda *a, **k: [(ln, 1) for ln in linhas]
    try:
        itens = te.extrair_itens(_FakeReader())
    finally:
        te._coletar_linhas = original

    assert len(itens) == 2, len(itens)
    d1, d2 = itens[0].descricao, itens[1].descricao
    # o inicio do bloco (acima da ancora) tem de entrar no item certo...
    assert "BANDAGEM INELASTICA" in d1, d1
    assert "ULCERAS VENOSAS" in d1, d1
    # ...e nada do item 2 pode vazar para o item 1
    assert "AUTOADERENTE" not in d1, d1
    assert "AUTOADERENTE" in d2 and "ESPUMA ABSORVENTE" in d2, d2
    assert "BANDAGEM" not in d2, d2
    print("ok  test_fronteira_regime_participacao")



def test_cancelamento_nao_e_engolido():
    """Cancelamento sobe pelas camadas: nunca vira 'falha de leitura'."""
    import threading
    from hbi.utils import cancelamento

    tid = threading.get_ident()
    cancelamento.marcar_cancelamento(tid)
    try:
        assert cancelamento.cancelada(tid)
        levantou = False
        try:
            cancelamento.checar()
        except cancelamento.AnaliseCancelada:
            levantou = True
        assert levantou, "checar() deveria levantar AnaliseCancelada"
    finally:
        cancelamento.limpar(tid)

    assert not cancelamento.cancelada(tid), "limpar() deveria remover o registro"

    # a excecao NAO pode ser subclasse de nada que o pipeline capture como
    # falha generica de leitura — senao o pedido do usuario seria engolido
    # e o trabalho recomecaria no extrator lento.
    import inspect
    from hbi.modules import pdf_reader
    fonte = inspect.getsource(pdf_reader.PdfReader.texto_rapido)
    assert "except AnaliseCancelada" in fonte, (
        "texto_rapido precisa re-lancar o cancelamento antes do except geral"
    )
    print("ok  test_cancelamento_nao_e_engolido")



def test_regras_destaque():
    """Termos criticos destacados so quando o produto correspondente aparece."""
    from hbi.config.regras_destaque import trechos_destacados as T

    def marcados(txt):
        return [txt[a:b].upper() for a, b in T(txt)]

    # luva: presenca de po / material
    d = "LUVA DE PROCEDIMENTO EM LATEX, NAO ESTERIL, LUBRIFICADA COM PO"
    assert "LUBRIFICA" in marcados(d) and "COM PO" in marcados(d), marcados(d)
    assert "SEM PO" in marcados("LUVA NITRILICA SEM PO, TAMANHO G")
    assert "S/PO" in marcados("LUVA CIRURGICA S/PO ESTERIL")
    assert marcados("LUVA NITRILICA SINTETICA") == ["SINTETICA"]

    # cateter / scalpe / seringa / agulha: NR 32
    for produto in ("CATETER INTRAVENOSO PERIFERICO 20G", "ABOCATH 22G",
                    "SCALPE 23G", "ESCALPE 21G", "SERINGA 5ML", "AGULHA 25X7"):
        d = produto + " COM DISPOSITIVO DE SEGURANCA CONFORME NR 32"
        m = marcados(d)
        assert "COM DISPOSITIVO DE SEGURANCA" in m, (produto, m)
        assert "CONFORME NR 32" in m, (produto, m)

    # o gatilho evita ruido: termo presente, produto ausente -> nao destaca
    assert marcados("GAZE HIDROFILA, EMBALAGEM SEM PO") == []
    assert marcados("SONDA EM MATERIAL SINTETICO") == []
    assert marcados("EQUIPO MACROGOTAS") == []

    # trechos sobrepostos viram um so intervalo (sem marcacao duplicada)
    d = "SERINGA COM DISPOSITIVO DE SEGURANCA"
    assert len(T(d)) == 1, T(d)
    print("ok  test_regras_destaque")



def test_escolha_de_estrategia():
    """A leitura por grade so e adotada quando cobre mais da sequencia."""
    from hbi.modules import table_extractor as te
    from hbi.models.edital import ItemEdital

    def itens(nums):
        return [ItemEdital(item=n, descricao="x" * 30, unidade="UN", quantidade=1,
                           valor_estimado=2.0, valor_total=2.0, pagina=1)
                for n in nums]

    # sequencia completa -> nem tenta a grade (e por isso aceita caminho None)
    assert abs(te._completude(itens(range(1, 51))) - 1.0) < 1e-9
    # buracos reduzem a cobertura proporcionalmente
    assert abs(te._completude(itens([1, 2, 3, 7, 8, 9, 10])) - 0.7) < 1e-9
    assert te._completude([]) == 0.0
    print("ok  test_escolha_de_estrategia")



def test_leitura_do_miolo_v17():
    """Formatos de linha de item vistos nos editais da v17."""
    from hbi.modules.table_extractor import _parse_miolo as f
    casos = [
        # unidade antes da descricao (Guarapuava) - nome do produto preservado
        ("1 4755 PCT CATMAT 481797 - LENCOL", "CATMAT 481797 - LENCOL"),
        # "NAO" faz parte da descricao: nao pode inverter o sentido do produto
        ("1 30 CR CATMAT 411291 - BATERIA NAO", "CATMAT 411291 - BATERIA NAO"),
        # unidade fora do vocabulario ("M" de metro), descricao aberta por CATMAT
        ("1 127 M CATMAT 460728 - TUBO HOSPITALAR -", "CATMAT 460728 - TUBO HOSPITALAR -"),
        # unidade | quantidade | descricao (Iguacu)
        ("UN 20 SONDA ENDOTRAQUEAL DE PVC N 2,0 SEM BALAO", "SONDA ENDOTRAQUEAL DE PVC N 2,0 SEM BALAO"),
        ("UN 100 CATETER OXIGENOTERAPIA PEDIATRICO - UNIDADE", "CATETER OXIGENOTERAPIA PEDIATRICO - UNIDADE"),
    ]
    for miolo, esperado in casos:
        assert f(miolo)[0] == esperado, (miolo, f(miolo))
    # palavra de unidade que ABRE a descricao continua na descricao
    assert f("KIT PARTO (EMBALAGEM LACRADA) CONTENDO: 01 - KIT")[0].startswith("KIT PARTO")
    assert f("93712 274623 BOLSA COLETORA DE URINA (SISTEMA UNID 1.800 NAO")[0].startswith("BOLSA")
    assert "CAIXA PLASTICA" in f("30 CAIXA PLASTICA TIPO ORGANIZADOR UN")[0]
    # medida nao e coluna de unidade
    assert f("50 L, APRESENTACAO: PECA UNICA")[0].startswith("50 L")
    print("ok  test_leitura_do_miolo_v17")


def test_filtro_nao_apaga_descricao_v17():
    """Linhas de descricao que o filtro de ruido da v16 apagava."""
    from hbi.modules.table_extractor import _NOISE
    mantem = [
        "PRODUTO ESTERILIZADO. TAMANHO 14 FR. UND",
        "FORNECIDO EM CAIXA COM 100",
        "MEDIA - MODELO: C, SISTEMA",
        "MAXIMO O DESFIAMENTO E A",
        "CONDICOES GERAIS DA NBR 14990 E",
        "DESCRICAO DETALHADA DO KIT CONFORME ANEXO",
        "COR A CRITERIO DA CONTRATANTE.",
        "ENTREGA PARCELADA CONFORME EDITAL.",
        "UNID.",
    ]
    for s in mantem:
        assert not _NOISE.search(s), s
    for s in ("UNIT. (R$) (R$)", "PRECO MAXIMO PRECO TOTAL", "ANEXO I - TERMO DE REFERENCIA"):
        assert _NOISE.search(s), s
    print("ok  test_filtro_nao_apaga_descricao_v17")


def test_fronteiras_e_limpeza_v17():
    from hbi.modules import table_extractor as te
    assert te._TOTAL_LINHA.match("TOTAL: R$ 801.434,08")
    assert not te._TOTAL_LINHA.match("TOTAL DE 10 UNIDADES POR CAIXA")
    assert te._FIM_DESCRICAO.search("CALIBRE N 12 - BR 437443.")
    assert te._FIM_DESCRICAO.search("UNIDADE DE FORNECIMENTO: ROLO")
    assert te._ROTULO_GRUPO.match("LOTE 2")
    assert te._RS_SOLTO.sub(" ", "UNIDADE DE R$ FORNECIMENTO R$ 10,00").split() == \
        ["UNIDADE", "DE", "FORNECIMENTO", "R$", "10,00"]
    # cabecalho/rodape: variantes da mesma linha batem; traco de assinatura tambem
    assert te._forma_canonica("\u00ae MUNICIPIO DE CASCAVEL") == te._forma_canonica("MUNICIPIODECASCAVEL")
    assert te._forma_canonica("______________") == "______________"
    print("ok  test_fronteiras_e_limpeza_v17")


def test_escolha_usa_regua_comum():
    """Grade que so achou itens 1..9 nao pode vencer ancoras com 55 de 58."""
    from hbi.modules import table_extractor as te
    from hbi.modules import grid_extractor as ge
    from hbi.models.edital import ItemEdital
    mk = lambda ns: [ItemEdital(item=n, descricao="x" * 30, unidade="UN", quantidade=1,
                                valor_estimado=1.0, valor_total=1.0, pagina=1) for n in ns]
    ancoras = mk([n for n in range(1, 59) if n not in (17, 18, 19)])
    orig_a, orig_g = te.extrair_itens, ge.extrair_por_grade
    te.extrair_itens = lambda r: ancoras
    ge.extrair_por_grade = lambda c: (mk(range(1, 10)), {})
    try:
        itens, _ = te.melhor_extracao(object(), "qualquer.pdf")
    finally:
        te.extrair_itens, ge.extrair_por_grade = orig_a, orig_g
    assert len(itens) == 55, len(itens)
    print("ok  test_escolha_usa_regua_comum")



def test_info_edital_v18():
    """Sessão, validade, local/regional, contatos, portal e nome do arquivo."""
    from hbi.modules.info_edital import extrair_informacoes, _local_regional, _do_nome_arquivo
    texto = ("PREFEITURA MUNICIPAL DE X ESTADO DO PARANÁ\n"
             "DATA E HORA DA SESSÃO PÚBLICA Dia 28/10/2026 às 08h00min (horário de Brasília)\n"
             "LOCAL DA SESSÃO PÚBLICA BLL COMPRAS - www.bll.com.br\n"
             "A validade da proposta não será inferior a 60 (sessenta) dias.\n"
             "E-mail: licitacao@x.pr.gov.br Fone: (44) 3232-1234 contato@bll.org.br\n"
             "CNPJ 76.123.456/0001-00")
    i = extrair_informacoes(texto, "28-10-2026 - 07 30 hrs - PE 50-2026 - X PR (Portal BLL).pdf",
                            pregao_texto="PE 032/2026")
    assert i["sessao"]["data_sessao"] == "28/10/2026" and i["sessao"]["hora_sessao"] == "08:00"
    assert i["validade"]["validade_proposta_dias"] == 60
    assert i["portal"]["portal"] == "BLL Compras"
    assert i["contatos"]["emails"] == ["licitacao@x.pr.gov.br"]       # do portal fica à parte
    assert i["contatos"]["emails_portal"] == ["contato@bll.org.br"]
    assert i["contatos"]["telefones"] == ["(44) 3232-1234"]           # CNPJ não vira telefone
    assert i["origem"]["uf"] == "PR"
    div = " ".join(i["divergencias"])
    assert "Hora da sessão" in div and "Número do pregão" in div
    # local/regional: a fórmula da LC 123 conta; certidão e mercado fornecedor não
    assert _local_regional("ME e EPP sediadas local ou regionalmente terão prioridade")["local_regional"]
    assert not _local_regional("Certidão de tributos (para empresas sediadas no Município de X)")["local_regional"]
    assert not _local_regional("ampla disponibilidade em âmbito regional e nacional")["local_regional"]
    cota = _local_regional("LOTES DE COTA RESERVADA - PARA MICRO E PEQUENAS EMPRESAS LOCAIS")
    assert cota["local_regional"] and cota["tipo"].startswith("cota")
    # nome do arquivo também depois do upload trocar espaços e parênteses por "_"
    a = _do_nome_arquivo("28-10-2026_-_07_30_hrs_-_PE_50-2026_-_Iguacu_PR__Portal_BLL_.pdf")
    assert a["pregao"] == "PE 50/2026" and a["portal"] == "BLL" and a["hora_sessao"] == "07:30"
    print("ok  test_info_edital_v18")


def test_espelho_criterios_v18():
    """Quadro-resumo sem dois-pontos, variantes novas e número do pregão."""
    from hbi.modules import edital_validator as ev
    r, _ = ev.resposta_exclusiva_me_epp("MODO DE DISPUTA: Aberto EXCLUSIVO ME/EPP/EQUIPARADAS  NÃO    PREFERÊNCIA")
    assert r is False
    r, _ = ev.resposta_exclusiva_me_epp("o item exclusivo ME/EPP não poderá ser adjudicado")
    assert r is None                       # frase, não resposta do quadro
    def marcado(texto, nome):
        return next(c for c in ev.validar(texto).criterios if c.nome == nome).presente
    assert marcado("MENOR PREÇO POR ITEM, com PARTICIPAÇÃO EXCLUSIVA para Microempreendedor "
                   "Individual - MEI, Microempresas", "Exclusiva ME/EPP")
    assert marcado("LOTES DE COTA RESERVADA - PARA MICRO E PEQUENAS EMPRESAS", "Cota reservada ME/EPP")
    assert marcado("microempresas e empresas de pequeno porte, estabelecendo cota reservada",
                   "Cota reservada ME/EPP")
    assert marcado("o critério de julgamento será o MENOR PREÇO POR GRUPO", "Disputa por lote (não por item)")
    assert not marcado("taxa de R$ 600,00 por lote adjudicado", "Disputa por lote (não por item)")
    m = ev.detectar_metadados("EDITAL DE PREGÃO Nº 050/2026 REGISTRO DE PREÇOS N° 032/2026")
    assert m["numero_pregao"] == "PE 050/2026", m["numero_pregao"]
    print("ok  test_espelho_criterios_v18")


def test_espelho_pdf_e_zip_v18():
    """PDF do espelho é gerado; zip não grava fora da pasta e corrige acentos."""
    import io, tempfile, zipfile
    from pathlib import Path
    from hbi.models.edital import Edital, ResultadoValidacao, CriterioValidacao
    from hbi.services.espelho_pdf import gerar_pdf_espelho
    e = Edital(origem="x.pdf", orgao="X", numero_pregao="PE 1/2026", valor_total_estimado=None,
               itens=[], validacao=ResultadoValidacao(
                   criterios=[CriterioValidacao(nome="Exige amostras", presente=True, impacto="atencao",
                                                evidencia="apresentar amostra <&>", categoria="Decisão")],
                   veredito="revisar", justificativa="teste"),
               info={"sessao": {"data_sessao": "01/01/2026"}, "divergencias": ["teste"]})
    with tempfile.TemporaryDirectory() as d:
        pdf = gerar_pdf_espelho(e, Path(d) / "esp.pdf")
        assert pdf.read_bytes()[:4] == b"%PDF"
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from webapp.app import _extrair_pdfs_do_zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../../fora.pdf", b"%PDF-1.4 x")      # tentativa de sair da pasta
            z.writestr("pasta/Igua-xxu.pdf", b"%PDF-1.4 y")
            z.writestr("leia.txt", b"nada")
        dados = buf.getvalue().replace(b"Igua-xxu", "Iguaçu".encode("utf-8")[:8].ljust(8, b"_"))
        (Path(d) / "a.zip").write_bytes(dados)
        saida = _extrair_pdfs_do_zip(Path(d) / "a.zip", Path(d))
        assert len(saida) == 2 and all(p.parent == Path(d) for p, _ in saida)
        assert not (Path(d).parent / "fora.pdf").exists()
    print("ok  test_espelho_pdf_e_zip_v18")


if __name__ == "__main__":
    test_conversao_brl()
    test_confere_total()
    test_validacao_go_nogo()
    test_metadados()
    test_descritivos_por_lote()
    test_descritivos_por_item()
    test_sem_descritivos_separados()
    test_itens_em_blocos()
    test_mobiliario_de_pagina()
    test_noise_nao_apaga_descricao()
    test_fronteira_regime_participacao()
    test_cancelamento_nao_e_engolido()
    test_regras_destaque()
    test_escolha_de_estrategia()
    test_leitura_do_miolo_v17()
    test_filtro_nao_apaga_descricao_v17()
    test_fronteiras_e_limpeza_v17()
    test_escolha_usa_regua_comum()
    test_info_edital_v18()
    test_espelho_criterios_v18()
    test_espelho_pdf_e_zip_v18()
    print("\nTodos os testes de fumaça passaram.")

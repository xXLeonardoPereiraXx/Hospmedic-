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
    print("\nTodos os testes de fumaça passaram.")

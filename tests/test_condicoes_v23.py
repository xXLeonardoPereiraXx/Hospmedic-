from hbi.modules import condicoes_comerciais as cc


def test_campos_principais():
    t = ("Os produtos deverão ter prazo de validade mínimo de 12 meses na entrega. "
         "O pagamento será efetuado em até 30 (trinta) dias após a nota fiscal. "
         "1.4.2 Prazo de entrega: 15 (quinze) dias úteis. "
         "A vigência da Ata de Registro de Preços será de 12 (doze) meses.")
    r = cc.extrair(t)
    assert r["validade_produtos"]["valor"] == "12 mês(es)"
    assert r["prazo_pagamento"]["valor"] == "30 dias"
    assert r["prazo_entrega"]["valor"] == "15 dias úteis"
    assert r["vigencia_arp"]["valor"] == "12 mês(es)"


def test_validade_da_proposta_nao_conta_como_validade_do_produto():
    t = "Prazo de validade da proposta não inferior a 60 (sessenta) dias."
    assert cc.extrair(t)["validade_produtos"] == {}


def test_prazo_de_entrega_de_amostra_nao_conta():
    t = "O primeiro classificado deverá entregar, no prazo máximo de 05 (cinco) dias úteis, as amostras."
    assert cc.extrair(t)["prazo_entrega"] == {}


def test_ausente_fica_vazio():
    assert cc.extrair("texto sem nada relevante") == {
        "validade_produtos": {}, "prazo_pagamento": {}, "prazo_entrega": {}, "vigencia_arp": {}}

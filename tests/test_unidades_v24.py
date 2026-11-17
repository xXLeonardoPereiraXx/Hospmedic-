from hbi.models.edital import ItemEdital
from hbi.modules import unidades


def _it(u, d="X", q=10.0):
    return ItemEdital(item=1, descricao=d, unidade=u, quantidade=q,
                      valor_estimado=1.0, valor_total=q, pagina=1)


def test_letras_espacadas_viram_unidade():
    assert unidades.juntar_letras("UN D") == "UND"
    assert unidades.juntar_letras("PC T") == "PCT"
    assert unidades.juntar_letras("ME TR O") == "METRO"
    assert unidades.juntar_letras("PCT 100 UN.") == "PCT 100 UN."   # já é unidade


def test_nome_do_produto_nao_e_unidade():
    it = _it("Luva", "Luva de Segurança em Raspa 32,00 PA Técnica de Luva", q=32)
    assert unidades.corrigir([it]) == 1 and it.unidade == "PA"


def test_sem_evidencia_nao_inventa():
    it = _it("aço", "CUBA EM AÇO INOX 50X100 MM", q=90)
    unidades.corrigir([it])
    assert it.unidade == "aço"
    assert unidades.suspeitas([it]) == [1]


def test_unidades_validas():
    for u in ["UN", "Fra", "GALÃO 5L", "CAIXA 100 UN.", "pacote", "milheiro", "PCTE"]:
        assert unidades.eh_unidade(u), u


def test_medida_na_descricao_nao_vira_unidade():
    it = _it("", "CUBA REDONDA EM AÇO INOX 80 MM - CAP 160 ML", q=160)
    unidades.corrigir([it])
    assert it.unidade == ""

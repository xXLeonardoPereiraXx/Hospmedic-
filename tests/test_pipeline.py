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
    assert "Exige AFE (ANVISA)" in nomes_presentes
    assert "Menor preço por item" in nomes_presentes
    assert r.veredito in {"go", "revisar", "no_go"}
    print(f"ok  test_validacao_go_nogo (veredito={r.veredito})")


def test_metadados():
    texto = "O MUNICÍPIO DE XAMBRÊ ... EDITAL DE PREGÃO (ELETRÔNICO) SRP N° 10/2026"
    m = edital_validator.detectar_metadados(texto)
    assert m["numero_pregao"] == "PE 10/2026", m
    assert m["orgao"] and "Xambr" in m["orgao"], m
    print("ok  test_metadados")


if __name__ == "__main__":
    test_conversao_brl()
    test_confere_total()
    test_validacao_go_nogo()
    test_metadados()
    print("\nTodos os testes de fumaça passaram.")

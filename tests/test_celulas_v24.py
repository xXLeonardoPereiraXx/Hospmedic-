"""Leitura pelas células desenhadas: a borda é a fronteira entre itens."""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from hbi.modules.cell_extractor import extrair_por_celulas, sequencia_ok

COLS = [40, 80, 330, 380, 430, 490, 560]          # item | descrição | und | qtd | unit | total
CAB = ["Item", "Descrição", "Und", "Qtd", "Valor Unit.", "Valor Total"]


def _linha(c, y0, y1, textos, segmentado=False):
    """Desenha uma linha da tabela; segmentado=True desenha a borda por célula."""
    for x in COLS:
        c.line(x, y0, x, y1)
    if segmentado:
        for a, b in zip(COLS, COLS[1:]):
            c.line(a, y0, b, y0); c.line(a, y1, b, y1)
    else:
        c.line(COLS[0], y0, COLS[-1], y0); c.line(COLS[0], y1, COLS[-1], y1)
    for (a, _), t in zip(zip(COLS, COLS[1:]), textos):
        for k, parte in enumerate(t.split("\n")):
            c.drawString(a + 3, y1 - 11 - 10 * k, parte)


def _pdf(caminho):
    c = canvas.Canvas(str(caminho), pagesize=A4)
    c.setFont("Helvetica", 8)
    y = 800
    _linha(c, y - 20, y, CAB); y -= 20
    _linha(c, y - 40, y, ["1", "SERINGA 10 ML\nLUER LOCK", "UN", "100", "1,50", "150,00"], True); y -= 40
    # item 2 com descrição que a linha de baixo NÃO pode levar
    _linha(c, y - 40, y, ["2", "AGULHA 25 X 7\nCAIXA COM 100", "CX", "10", "8,00", "80,00"], True); y -= 40
    _linha(c, y - 30, y, ["3", "GAZE ESTERIL", "PCT", "1.000", "0,50", "500,00"]); y -= 30
    c.drawString(40, 60, "Página 1 | 2")
    c.showPage(); c.setFont("Helvetica", 8)
    # topo da página 2: resto da descrição do item 3 (linha sem número)
    y = 800
    _linha(c, y - 20, y, ["", "13 FIOS 7,5 X 7,5 CM", "", "", "", ""]); y -= 20
    _linha(c, y - 30, y, ["4", "ESPARADRAPO 10 CM", "RL", "20", "7,00", "140,00"]); y -= 30
    c.drawString(40, 60, "Página 2 | 2")
    c.showPage(); c.save()


def test_celulas_respeitam_bordas_e_quebra_de_pagina(tmp_path):
    f = tmp_path / "tabela.pdf"
    _pdf(f)
    itens, orfas = extrair_por_celulas(f)
    assert orfas == 0
    assert [i.item for i in itens] == [1, 2, 3, 4]
    assert sequencia_ok(itens)
    assert itens[0].descricao == "SERINGA 10 ML LUER LOCK"
    assert itens[1].descricao == "AGULHA 25 X 7 CAIXA COM 100"
    assert itens[2].descricao == "GAZE ESTERIL 13 FIOS 7,5 X 7,5 CM"
    assert itens[2].quantidade == 1000 and itens[2].valor_total == 500.0
    assert itens[3].unidade == "RL" and itens[3].valor_estimado == 7.0


def test_sem_bordas_nao_le(tmp_path):
    f = tmp_path / "texto.pdf"
    c = canvas.Canvas(str(f), pagesize=A4)
    c.drawString(40, 800, "1 SERINGA 10 ML UN 100 1,50 150,00")
    c.showPage(); c.save()
    assert extrair_por_celulas(f) == ([], 0)


def test_texto_sem_dono_entre_itens_e_denunciado(tmp_path):
    """Faixa de descrição sem número entre os itens 1 e 2: a leitura avisa."""
    f = tmp_path / "orfa.pdf"
    c = canvas.Canvas(str(f), pagesize=A4)
    c.setFont("Helvetica", 8)
    y = 800
    _linha(c, y - 20, y, CAB); y -= 20
    _linha(c, y - 20, y, ["1", "SERINGA 10 ML", "UN", "100", "1,50", "150,00"]); y -= 20
    _linha(c, y - 20, y, ["", "LUER LOCK ESTERIL", "", "", "", ""]); y -= 20
    _linha(c, y - 20, y, ["2", "AGULHA 25 X 7", "CX", "10", "8,00", "80,00"]); y -= 20
    c.showPage(); c.save()
    itens, orfas = extrair_por_celulas(f)
    assert len(itens) == 2 and orfas == 1

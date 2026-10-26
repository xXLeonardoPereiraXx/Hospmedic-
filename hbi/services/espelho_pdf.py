"""Espelho de critérios em PDF, pronto para imprimir ou arquivar.

Gera, a partir do :class:`Edital` já analisado, um documento com:

* identificação do certame e informações gerais (sessão, portal, validade da
  proposta, participação local/regional, contatos);
* pontos a conferir (divergências entre o texto e o nome do arquivo);
* o veredito e a justificativa;
* os critérios do Espelho de Documentos, por categoria, com a situação e a
  evidência textual de cada um.

Usa só as fontes embutidas do PDF (Helvetica), que cobrem a acentuação do
português e funcionam em qualquer servidor — sem depender de fontes
instaladas. Por isso não há símbolos como ✓ ou ⚠, que essas fontes não têm.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from hbi.models.edital import Edital
from hbi.utils.text import float_para_brl

# identidade HospMedic
AZUL = colors.HexColor("#203763")
VERDE = colors.HexColor("#649A06")
CINZA = colors.HexColor("#5b6576")
FUNDO = colors.HexColor("#eef1f6")
COR_IMPACTO = {
    "no_go": colors.HexColor("#b42318"),
    "atencao": colors.HexColor("#b54708"),
    "go": colors.HexColor("#3f6b04"),
    "checklist": CINZA,
}
ROTULO_IMPACTO = {
    "no_go": "Impeditivo", "atencao": "Exige conferência",
    "go": "Favorável", "checklist": "Documento",
}
COR_VEREDITO = {"go": COR_IMPACTO["go"], "no_go": COR_IMPACTO["no_go"],
                "revisar": COR_IMPACTO["atencao"]}

_base = getSampleStyleSheet()
TITULO = ParagraphStyle("t", parent=_base["Title"], fontName="Helvetica-Bold",
                        fontSize=17, textColor=AZUL, alignment=TA_LEFT, spaceAfter=2)
SUB = ParagraphStyle("s", parent=_base["Normal"], fontSize=9.5, textColor=CINZA)
H2 = ParagraphStyle("h2", parent=_base["Heading2"], fontName="Helvetica-Bold",
                    fontSize=11.5, textColor=AZUL, spaceBefore=10, spaceAfter=4)
TXT = ParagraphStyle("x", parent=_base["Normal"], fontSize=9, leading=11.5)
PEQ = ParagraphStyle("p", parent=TXT, fontSize=7.8, leading=9.6, textColor=CINZA)
ROT = ParagraphStyle("r", parent=TXT, fontName="Helvetica-Bold", textColor=AZUL)


def _p(texto, estilo=TXT) -> Paragraph:
    return Paragraph(escape(str(texto or "")), estilo)


def _tabela_info(edital: Edital) -> Table:
    i = edital.info or {}
    s, v, lr = i.get("sessao") or {}, i.get("validade") or {}, i.get("local_regional") or {}
    c, po, o = i.get("contatos") or {}, i.get("portal") or {}, i.get("origem") or {}

    sessao = s.get("data_sessao", "não identificada")
    if s.get("hora_sessao"):
        sessao += " às " + s["hora_sessao"]
    if lr.get("local_regional"):
        local = f"Sim: {lr.get('tipo', '')}"
    else:
        local = "Não identificado no edital"
    if edital.itens:
        valor = f"R$ {float_para_brl(edital.soma_itens)} (soma dos {len(edital.itens)} itens)"
    elif edital.valor_total_estimado is not None:
        valor = f"R$ {float_para_brl(edital.valor_total_estimado)} (referência informada no edital)"
    else:
        valor = "não identificado"

    linhas = [
        ("Órgão", f"{o.get('orgao') or edital.orgao or 'não identificado'}"
                  f"{' - ' + o['uf'] if o.get('uf') else ''}"),
        ("Pregão", edital.numero_pregao or "não identificado"),
        ("Sessão pública", sessao),
        ("Portal de disputa", po.get("portal", "não identificado")),
        ("Validade da proposta",
         f"{v['validade_proposta_dias']} dias" if v.get("validade_proposta_dias") else "não identificada"),
        ("Participação local/regional", local),
        ("Valor", valor),
        ("E-mails do órgão", ", ".join(c.get("emails") or []) or "não identificados"),
        ("Telefones", ", ".join(c.get("telefones") or []) or "não identificados"),
    ]
    if c.get("pregoeiro"):
        linhas.append(("Pregoeiro(a)", c["pregoeiro"]))
    dados = [[_p(a, ROT), _p(b)] for a, b in linhas]
    t = Table(dados, colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), FUNDO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d4dae4")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _tabela_criterios(criterios) -> Table:
    dados = [[_p("Critério", ROT), _p("Situação", ROT), _p("Evidência no edital", ROT)]]
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), FUNDO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d4dae4")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for k, c in enumerate(criterios, start=1):
        cor = COR_IMPACTO.get(c.impacto, CINZA) if c.presente else CINZA
        sit = ("Encontrado" if c.presente else "Não encontrado")
        if c.presente and c.impacto in ("no_go", "atencao"):
            sit += f" - {ROTULO_IMPACTO[c.impacto]}"
        estilo_sit = ParagraphStyle("sit", parent=TXT, textColor=cor,
                                    fontName="Helvetica-Bold" if c.presente else "Helvetica")
        dados.append([_p(c.nome), _p(sit, estilo_sit),
                      _p(c.evidencia[:260] if c.presente else "", PEQ)])
    t = Table(dados, colWidths=[58 * mm, 34 * mm, 78 * mm], repeatRows=1)
    t.setStyle(TableStyle(estilos))
    return t


def _rodape(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(CINZA)
    canvas.drawString(15 * mm, 10 * mm,
                      "HBI - HospMedic Bid Intelligence | Análise automática: "
                      "a decisão de participar exige revisão humana.")
    canvas.drawRightString(195 * mm, 10 * mm,
                           f"Gerado em {datetime.now():%d/%m/%Y %H:%M} | página {doc.page}")
    canvas.setStrokeColor(VERDE)
    canvas.setLineWidth(1.2)
    canvas.line(15 * mm, 14 * mm, 195 * mm, 14 * mm)
    canvas.restoreState()


def gerar_pdf_espelho(edital: Edital, destino: str | Path,
                      nome_exibido: str | None = None) -> Path:
    """Gera o espelho de critérios em PDF e devolve o caminho do arquivo."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(destino), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=18 * mm,
        title=f"Espelho de critérios - {edital.numero_pregao or ''}",
        author="HBI - HospMedic",
    )
    h: list = [
        _p("Espelho de Critérios", TITULO),
        _p(nome_exibido or Path(edital.origem).name, SUB),
        Spacer(1, 8),
        _p("Informações gerais", H2),
        _tabela_info(edital),
    ]

    divergencias = (edital.info or {}).get("divergencias") or []
    if divergencias:
        h.append(_p("Pontos a conferir", H2))
        for d in divergencias:
            h.append(_p(f"Atenção: {d}", ParagraphStyle(
                "d", parent=TXT, textColor=COR_IMPACTO["atencao"])))

    v = edital.validacao
    if v is not None:
        cor = COR_VEREDITO.get(v.veredito, CINZA)
        h.append(_p("Veredito", H2))
        h.append(KeepTogether([
            _p(v.veredito.upper().replace("_", "-"), ParagraphStyle(
                "v", parent=TXT, fontName="Helvetica-Bold", fontSize=13, textColor=cor,
                leading=16)),
            _p(v.justificativa),
        ]))
        ordem: list[str] = []
        por_cat: dict[str, list] = {}
        for c in v.criterios:
            cat = c.categoria or "Outros"
            if cat not in por_cat:
                ordem.append(cat)
                por_cat[cat] = []
            por_cat[cat].append(c)
        for cat in ordem:
            cs = por_cat[cat]
            achados = sum(1 for c in cs if c.presente)
            h.append(_p(f"{cat} ({achados} de {len(cs)} encontrados)", H2))
            h.append(_tabela_criterios(cs))

    doc.build(h, onFirstPage=_rodape, onLaterPages=_rodape)
    return destino

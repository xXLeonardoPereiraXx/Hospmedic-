"""Serviço de relatório: resumo textual da validação e da extração.

Gera um relatório legível (para console e/ou arquivo) que apoia a etapa de
revisão humana, destacando o veredito GO/NO-GO e os pontos de atenção.
"""
from __future__ import annotations

from pathlib import Path

from hbi.models.edital import Edital
from hbi.utils.text import float_para_brl

_SIMBOLO = {"go": "[GO]", "no_go": "[NO-GO]", "revisar": "[REVISAR]", "atencao": "!", }


def montar_relatorio(edital: Edital) -> str:
    """Monta o relatório textual completo do edital processado."""
    linhas: list[str] = []
    add = linhas.append

    add("=" * 68)
    add("HBI — Relatório de Análise de Edital")
    add("=" * 68)
    add(f"Origem        : {Path(edital.origem).name}")
    add(f"Órgão         : {edital.orgao or '(não identificado)'}")
    add(f"Pregão        : {edital.numero_pregao or '(não identificado)'}")
    if edital.valor_total_estimado is not None:
        add(f"Valor edital  : R$ {float_para_brl(edital.valor_total_estimado)}")
    add(f"Itens         : {len(edital.itens)}")
    add(f"Soma extraída : R$ {float_para_brl(edital.soma_itens)}")

    # --- Gate de extração (confiabilidade dos dados) ---
    diag = edital.diagnostico_extracao()
    add("")
    add(f"EXTRAÇÃO      : [{diag['gate']}] — {diag['motivo_gate']}")
    add(f"  Sequência 1..N completa : {'sim' if diag['sequencia_completa'] else 'NÃO'}")
    add(f"  Linhas consistentes     : {diag['linhas_consistentes']}/{diag['itens']}"
        f" ({diag['consistencia_pct']:.1f}%)")
    if diag.get("total_declarado") is not None:
        estado = "OK" if diag.get("bate_com_declarado") else "DIVERGE"
        add(f"  Soma x total declarado  : {estado}"
            f" (declarado R$ {float_para_brl(diag['total_declarado'])})")

    # Veredito.
    if edital.validacao is not None:
        v = edital.validacao
        add("")
        add(f"VEREDITO      : {_SIMBOLO.get(v.veredito, v.veredito.upper())} "
            f"{v.veredito.upper()}")
        add(f"Justificativa : {v.justificativa}")
        add("")
        add("Critérios avaliados:")
        for c in v.criterios:
            marca = "x" if c.presente else " "
            add(f"  [{marca}] ({c.impacto:7}) {c.nome}")
            if c.presente and c.evidencia:
                add(f"        └ evidência: …{c.evidencia}…")

    # Itens que falharam na conferência automática.
    suspeitos = [i for i in edital.itens if not i.confere_total()]
    add("")
    if suspeitos:
        add(f"Itens a revisar (qtd × valor ≠ total): {len(suspeitos)}")
        for i in suspeitos[:15]:
            add(f"  - item {i.item}: q={i.quantidade} × {float_para_brl(i.valor_estimado)}"
                f" ≠ {float_para_brl(i.valor_total)}")
    else:
        add("Todos os itens passaram na conferência automática (qtd × valor = total).")

    add("=" * 68)
    return "\n".join(linhas)


def salvar_relatorio(edital: Edital, destino: str | Path) -> Path:
    """Salva o relatório textual em ``destino`` e retorna o caminho."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar_relatorio(edital), encoding="utf-8")
    return destino


def montar_relatorio_validacao(edital: Edital) -> str:
    """Relatório enxuto: apenas metadados e a validação GO/NO-GO.

    Usado no modo "somente validação", quando não há extração de itens.
    """
    linhas: list[str] = []
    add = linhas.append

    add("=" * 68)
    add("HBI — Validação de Critérios (GO/NO-GO)")
    add("=" * 68)
    add(f"Origem        : {Path(edital.origem).name}")
    add(f"Órgão         : {edital.orgao or '(não identificado)'}")
    add(f"Pregão        : {edital.numero_pregao or '(não identificado)'}")
    if edital.valor_total_estimado is not None:
        add(f"Valor edital  : R$ {float_para_brl(edital.valor_total_estimado)}")

    if edital.validacao is not None:
        v = edital.validacao
        add("")
        add(f"VEREDITO      : {_SIMBOLO.get(v.veredito, v.veredito.upper())} "
            f"{v.veredito.upper()}")
        add(f"Justificativa : {v.justificativa}")
        add("")
        add("Critérios avaliados:")
        for c in v.criterios:
            marca = "x" if c.presente else " "
            add(f"  [{marca}] ({c.impacto:7}) {c.nome}")
            if c.presente and c.evidencia:
                add(f"        └ evidência: …{c.evidencia}…")

    add("=" * 68)
    return "\n".join(linhas)


def salvar_relatorio_validacao(edital: Edital, destino: str | Path) -> Path:
    """Salva o relatório enxuto de validação em ``destino``."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar_relatorio_validacao(edital), encoding="utf-8")
    return destino

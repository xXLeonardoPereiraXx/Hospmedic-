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
    add(f"Itens         : {len(edital.itens)}")
    # No modo completo o valor oficial é a SOMA DOS ITENS extraídos — número
    # exato e derivado dos dados reais da tabela. Editais costumam declarar
    # valores globais que divergem entre si (soma dos itens vs. verba
    # disponível); esses não são usados aqui para evitar ruído.
    add(f"Valor total   : R$ {float_para_brl(edital.soma_itens)}  "
        f"(soma dos {len(edital.itens)} itens)")

    # --- Gate de extração (confiabilidade dos dados) ---
    diag = edital.diagnostico_extracao()
    add("")
    add(f"EXTRAÇÃO      : [{diag['gate']}] — {diag['motivo_gate']}")
    add(f"  Sequência 1..N completa : {'sim' if diag['sequencia_completa'] else 'NÃO'}")
    add(f"  Linhas consistentes     : {diag['linhas_consistentes']}/{diag['itens']}"
        f" ({diag['consistencia_pct']:.1f}%)")

    # --- Join de descritivos técnicos (editais com descrição em seção à parte) ---
    dd = getattr(edital, "diagnostico_descritivos", None) or {}
    if dd.get("tipo_chave"):
        add("")
        add(f"DESCRITIVOS   : {dd['descritivos']} blocos indexados por "
            f"{dd['tipo_chave']}; {dd['itens_enriquecidos']} itens enriquecidos")
        if dd.get("itens_sem_descritivo"):
            add(f"  Itens sem descritivo : {dd['itens_sem_descritivo'][:15]}")
        if dd.get("descritivos_orfaos"):
            add(f"  Descritivos órfãos   : {dd['descritivos_orfaos'][:15]}")

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
        # Na triagem não há extração de itens, então mostramos o valor
        # informado no edital apenas como referência de PORTE (ordem de
        # grandeza para decidir se vale participar). Não é tratado como
        # verdade absoluta — o valor exato sai da soma dos itens no modo
        # completo. Editais podem declarar mais de um valor global; usamos
        # o primeiro/mais específico só para dimensionar.
        add(f"Valor de referência : R$ {float_para_brl(edital.valor_total_estimado)} "
            f"(estimativa de porte, informada no edital)")

    if edital.validacao is not None:
        v = edital.validacao
        add("")
        add(f"VEREDITO      : {_SIMBOLO.get(v.veredito, v.veredito.upper())} "
            f"{v.veredito.upper()}")
        add(f"Justificativa : {v.justificativa}")

        _adicionar_criterios_por_categoria(add, v.criterios)

    add("=" * 68)
    return "\n".join(linhas)


def _adicionar_criterios_por_categoria(add, criterios) -> None:
    """Escreve os critérios agrupados por categoria, em formato de checklist.

    Os critérios de decisão (impacto go/atenção/no_go) aparecem primeiro, com
    a evidência textual; os documentos de habilitação ('checklist') vêm em
    seguida, agrupados pelas seções do Espelho de Documentos, mostrando
    presença/ausência e um total por seção.
    """
    from hbi.config.criterios_espelho import CATEGORIAS

    # agrupa preservando a ordem de CATEGORIAS
    por_cat: dict[str, list] = {cat: [] for cat in CATEGORIAS}
    for c in criterios:
        por_cat.setdefault(c.categoria or "Outros", []).append(c)

    for categoria in por_cat:
        itens = por_cat[categoria]
        if not itens:
            continue
        presentes = sum(1 for c in itens if c.presente)
        add("")
        add(f"── {categoria}  ({presentes}/{len(itens)}) "
            + "─" * max(0, 48 - len(categoria)))
        for c in itens:
            marca = "X" if c.presente else " "
            add(f"  [{marca}] {c.nome}")
            # evidência só para os critérios de decisão presentes (mantém o
            # checklist de habilitação enxuto e legível)
            if c.presente and c.evidencia and c.impacto in ("go", "atencao", "no_go"):
                add(f"        └ evidência: …{c.evidencia}…")


def salvar_relatorio_validacao(edital: Edital, destino: str | Path) -> Path:
    """Salva o relatório enxuto de validação em ``destino``."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar_relatorio_validacao(edital), encoding="utf-8")
    return destino

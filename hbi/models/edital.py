"""Modelos de dados do domínio HBI.

Representam as entidades centrais do processo de análise de editais:
cada :class:`ItemEdital` é uma linha da tabela do Termo de Referência,
e :class:`Edital` agrega os itens, os metadados e o resultado da
validação de critérios de participação.

Todos os dados são rastreáveis à origem (página do PDF) — princípio
arquitetural nº 3 do documento mestre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Abaixo deste número de itens, a consistência interna não é evidência
# suficiente para declarar a extração confiável (ver ``diagnostico_extracao``).
MIN_ITENS_PARA_CONFIANCA = 3


@dataclass
class ItemEdital:
    """Uma linha da tabela de itens do Termo de Referência.

    Attributes:
        item: Número sequencial do item no edital.
        descricao: Descrição do produto conforme o edital.
        unidade: Unidade de fornecimento (ex.: ``"Cx"``, ``"uni"``).
        quantidade: Quantidade estimada.
        valor_estimado: Valor unitário estimado pelo órgão (R$).
        valor_total: Valor total estimado da linha (R$).
        pagina: Página do PDF de onde a linha foi extraída (rastreabilidade).
        lote: Número do lote, em editais organizados por lote (ex.: portal
            BLL, onde a numeração de item reinicia a cada lote). ``None``
            em editais com tabela de itens única.
    """

    item: int
    descricao: str
    unidade: str
    quantidade: float
    valor_estimado: float
    valor_total: float
    pagina: int
    lote: Optional[int] = None

    def confere_total(self, tolerancia: float = 0.5) -> bool:
        """Indica se ``quantidade * valor_estimado`` bate com ``valor_total``.

        Usado como coluna de conferência para revisão humana.
        """
        esperado = self.quantidade * self.valor_estimado
        return abs(esperado - self.valor_total) <= tolerancia


@dataclass
class CriterioValidacao:
    """Resultado da checagem de um único critério de participação.

    Attributes:
        nome: Nome legível do critério (ex.: ``"Exige AFE/ANVISA"``).
        presente: Se o critério foi detectado no texto do edital.
        impacto: ``"go"`` (favorável/atende), ``"no_go"`` (impeditivo),
            ``"atencao"`` (requer análise humana) ou ``"checklist"``
            (documento de habilitação padrão; não altera o veredito).
        evidencia: Trecho do edital que embasou a decisão (rastreabilidade).
        categoria: Agrupamento no relatório (ex.: "Regularidade Fiscal e
            Trabalhista"). Vazio para os critérios legados.
    """

    nome: str
    presente: bool
    impacto: str
    evidencia: str = ""
    categoria: str = ""


@dataclass
class ResultadoValidacao:
    """Consolidação da validação de critérios com o veredito GO/NO-GO."""

    criterios: list[CriterioValidacao] = field(default_factory=list)
    veredito: str = "revisar"  # "go", "no_go" ou "revisar"
    justificativa: str = ""

    @property
    def impeditivos(self) -> list[CriterioValidacao]:
        """Critérios que, sozinhos, bloqueiam a participação."""
        return [c for c in self.criterios if c.impacto == "no_go" and c.presente]


@dataclass
class Edital:
    """Agrega os dados extraídos e validados de um edital.

    Attributes:
        origem: Caminho do PDF de origem.
        orgao: Nome do órgão/município, quando identificado.
        numero_pregao: Identificação do pregão (ex.: ``"PE 10/2026"``).
        valor_total_estimado: Valor global declarado no edital, se encontrado.
        itens: Lista de :class:`ItemEdital`.
        validacao: Resultado da validação de critérios.
    """

    origem: str
    orgao: Optional[str] = None
    numero_pregao: Optional[str] = None
    # Valor global informado no edital, usado APENAS como referência de porte
    # na triagem (modo validação, onde ainda não há itens extraídos). No modo
    # completo o número oficial é a soma dos itens (``soma_itens``), exata.
    valor_total_estimado: Optional[float] = None
    itens: list[ItemEdital] = field(default_factory=list)
    validacao: Optional[ResultadoValidacao] = None
    # Todos os valores globais declarados no texto (um edital pode trazer mais
    # de um: soma dos itens vs. verba disponível). Registrados para referência;
    # não geram mais aviso de divergência, por decisão de produto.
    valores_declarados: list[float] = field(default_factory=list)

    @property
    def soma_itens(self) -> float:
        """Soma dos ``valor_total`` de todos os itens extraídos."""
        return sum(i.valor_total for i in self.itens)

    @property
    def sequencia_completa(self) -> bool:
        """Indica se os itens formam a sequência 1..N sem lacunas."""
        nums = sorted(i.item for i in self.itens)
        return nums == list(range(1, len(nums) + 1)) if nums else False

    def diagnostico_extracao(self) -> dict:
        """Diagnóstico do gate de extração: confiabilidade dos dados.

        Baseia-se na evidência interna dos próprios itens — a consistência
        (qtd × valor unitário == valor total) e a completude da sequência
        (1..N sem lacunas). O valor global declarado no edital NÃO é usado
        como referência: editais frequentemente declaram valores que divergem
        entre si (soma dos itens vs. verba disponível), então ele não é uma
        âncora confiável. A soma dos itens extraídos é o número oficial.
        """
        total = len(self.itens)
        consistentes = sum(1 for i in self.itens if i.confere_total())
        pct = (consistentes / total * 100) if total else 0.0

        diag = {
            "itens": total,
            "sequencia_completa": self.sequencia_completa,
            "soma_itens": self.soma_itens,
            "linhas_consistentes": consistentes,
            "consistencia_pct": pct,
        }

        # Com pouquíssimos itens a evidência interna é fraca demais: uma tabela
        # com 1 item satisfaz "sequência completa" e "100% consistente"
        # trivialmente, mesmo que a extração tenha perdido todo o resto.
        if total < MIN_ITENS_PARA_CONFIANCA:
            diag["gate"] = "REVISAR"
            diag["motivo_gate"] = (
                f"poucos itens extraídos ({total}) — extração possivelmente "
                "incompleta"
            )
        elif pct >= 98 and self.sequencia_completa:
            diag["gate"] = "CONFIAVEL"
            diag["motivo_gate"] = "consistência interna alta e sequência completa"
        else:
            diag["gate"] = "REVISAR"
            diag["motivo_gate"] = "consistência interna baixa ou sequência incompleta"
        return diag

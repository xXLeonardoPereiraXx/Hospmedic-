"""Catálogo de critérios de habilitação, derivado do Espelho de Documentos.

Cada critério tem uma lista de **variantes/sinônimos**: o edital pode escrever
o mesmo documento de várias formas ("Certificado de Regularidade do FGTS",
"CRF", "Prova de regularidade com o FGTS"). O critério é considerado presente
se QUALQUER variante casar — assim reduzimos os falsos "ausente".

Estrutura de cada critério:
    id        — identificador curto e estável
    nome      — rótulo exibido no relatório
    categoria — agrupa no checklist (ver CATEGORIAS)
    variantes — lista de padrões regex; basta um casar
    impacto   — 'no_go' | 'atencao' | 'go' | 'checklist'
                'checklist' = documento de habilitação padrão; entra na lista
                de conferência mas não altera o veredito GO/NO-GO.

As categorias seguem as seções do Espelho de Documentos.
"""
from __future__ import annotations

# Ordem de exibição das categorias no relatório.
CATEGORIAS = [
    "Decisão (GO/NO-GO)",
    "Habilitação Jurídica",
    "Regularidade Fiscal e Trabalhista",
    "Qualificação Econômico-Financeira",
    "Qualificação Técnica",
    "Documentação Complementar (Declarações)",
]

# Cada entrada: (id, nome, categoria, [variantes...], impacto)
CRITERIOS: list[tuple[str, str, str, list[str], str]] = [
    # ------------------------------------------------------------------ #
    # 1) CRITÉRIOS DE DECISÃO — definem o veredito GO / NO-GO / REVISAR
    # ------------------------------------------------------------------ #
    (
        "exclusiva_me_epp",
        "Exclusiva ME/EPP",
        "Decisão (GO/NO-GO)",
        [
            # Só afirmações diretas de exclusividade. Frases condicionais ou
            # negativas ("nos itens em que NÃO for exclusiva") e o quadro-resumo
            # respondido com "NÃO" são tratados à parte (ver _negado_como_resposta
            # e a exclusão de "não ... exclusiva" abaixo).
            r"licita[çc][ãa]o exclusiva[^.\n]{0,40}(me|epp|microempresa)",
            r"(item|itens)[^.\n]{0,30}exclusiv[ao][^.\n]{0,30}(me|epp|microempresa)",
            r"destinad[oa][^.\n]{0,30}exclusivamente[^.\n]{0,30}(me|epp|microempresa)",
            r"participa[çc][ãa]o\s+exclusiva[^.\n]{0,30}(me|epp|microempresa)",
            # "PARTICIPAÇÃO EXCLUSIVA para Microempreendedor Individual – MEI,
            # Microempresas..." (Santa Fé): mais distância e MEI/microempreendedor
            r"participa[çc][ãa]o\s+exclusiva[^.\n]{0,80}(?:microempreendedor|\bmei\b|microempresa)",
            r"LICITA[ÇC][ÃA]O EXCLUSIVA ME/EPP[^\n]{0,20}(sim|:.{0,6}sim)",
        ],
        "atencao",
    ),
    (
        "cota_reservada",
        "Cota reservada ME/EPP",
        "Decisão (GO/NO-GO)",
        [
            r"cota[s]? reservada[s]?[^.\n]{0,40}(me|epp|microempresa)",
            # "LOTES DE COTA RESERVADA - PARA MICRO E PEQUENAS EMPRESAS" (Guarapuava)
            r"cotas?\s+reservadas?[^.\n]{0,40}(?:micro\s+e\s+pequenas|pequeno\s+porte|\bmpe\b)",
            # ME/EPP ANTES da cota: "...microempresas e empresas de pequeno porte,
            # estabelecendo cota reservada" (CIGAMERIOS)
            r"(?:microempresas?|pequeno\s+porte)[^.\n]{0,80}cotas?\s+reservadas?",
            r"cota reservada[^\n]{0,30}(sim|:.{0,6}sim)",
            r"reserva[^.\n]{0,20}(25%|vinte e cinco por cento)[^.\n]{0,30}(me|epp)",
        ],
        "atencao",
    ),
    (
        "disputa_por_lote",
        "Disputa por lote (não por item)",
        "Decisão (GO/NO-GO)",
        [
            r"menor\s+pre[çc]o\s+(?:global\s+)?por\s+(?:lote|grupo)",
            r"lote:\s*\d+\s*-\s*lote",
            r"julgamento[^.\n]{0,40}por\s+(?:lote|grupo)",
            r"disputa[^.\n]{0,20}por (grupo|lote)",
        ],
        "atencao",
    ),
    (
        "amostras",
        "Exige amostras",
        "Decisão (GO/NO-GO)",
        [
            r"\bamostra",
            r"apresenta[çc][ãa]o de amostra",
            r"prova de conceito",
        ],
        "atencao",
    ),
    (
        "menor_preco_item",
        "Julgamento por menor preço por item",
        "Decisão (GO/NO-GO)",
        [
            r"menor pre[çc]o por item",
            r"menor pre[çc]o unit[áa]rio",
            r"crit[ée]rio de julgamento[^.\n]{0,20}menor pre[çc]o[^.\n]{0,20}item",
        ],
        "go",
    ),
    (
        "disputa_aberto",
        "Modo de disputa aberto",
        "Decisão (GO/NO-GO)",
        [
            r"modo de disputa[^.\n]{0,20}aberto",
            r"disputa[^.\n]{0,10}\baberto\b",
        ],
        "go",
    ),

    # ------------------------------------------------------------------ #
    # 2) HABILITAÇÃO JURÍDICA
    # ------------------------------------------------------------------ #
    (
        "contrato_social",
        "Contrato Social / última alteração",
        "Habilitação Jurídica",
        [
            r"contrato social",
            r"ato constitutivo",
            r"estatuto social",
            r"[úu]ltima altera[çc][ãa]o contratual",
            r"consolida[çc][ãa]o (do )?contrato social",
        ],
        "checklist",
    ),
    (
        "cnpj",
        "CNPJ atualizado",
        "Habilitação Jurídica",
        [
            r"\bCNPJ\b",
            r"cadastro nacional da pessoa jur[íi]dica",
            r"comprovante de inscri[çc][ãa]o[^.\n]{0,30}CNPJ",
        ],
        "checklist",
    ),
    (
        "inscricao_estadual_municipal",
        "Inscrição Estadual/Municipal (Cicad/Alvará)",
        "Habilitação Jurídica",
        [
            r"inscri[çc][ãa]o estadual",
            r"inscri[çc][ãa]o municipal",
            r"\bcicad\b",
            r"alvar[áa]",
        ],
        "checklist",
    ),
    (
        "identificacao_representante",
        "Identificação do representante legal (RG/CPF)",
        "Habilitação Jurídica",
        [
            r"documento[s]? de identifica[çc][ãa]o[^.\n]{0,30}representante",
            r"representante legal[^.\n]{0,30}(rg|cpf)",
            r"\bRG\b[^.\n]{0,6}\bCPF\b",
        ],
        "checklist",
    ),
    (
        "certidao_correcional",
        "Certidão Negativa Correcional (CGU/CEIS/CNEP/TCU)",
        "Habilitação Jurídica",
        [
            r"certid[ãa]o negativa correcional",
            r"\bCEIS\b",
            r"\bCNEP\b",
            r"\bCEPIM\b",
            r"consulta consolidada[^.\n]{0,30}(TCU|tribunal de contas)",
            r"\bCGU-PJ\b",
        ],
        "checklist",
    ),
    (
        "sicaf",
        "SICAF",
        "Habilitação Jurídica",
        [
            r"\bSICAF\b",
            r"sistema de cadastramento unificado de fornecedores",
        ],
        "checklist",
    ),

    # ------------------------------------------------------------------ #
    # 3) REGULARIDADE FISCAL E TRABALHISTA
    # ------------------------------------------------------------------ #
    (
        "cnd_federal",
        "Certidão de Débitos Federais / Dívida Ativa da União (RFB)",
        "Regularidade Fiscal e Trabalhista",
        [
            r"certid[ãa]o[^.\n]{0,40}d[ée]bitos[^.\n]{0,30}federa",
            r"d[íi]vida ativa da uni[ãa]o",
            r"certid[ãa]o conjunta[^.\n]{0,30}(federa|uni[ãa]o|RFB)",
            r"regularidade[^.\n]{0,20}fazenda (nacional|federal)",
            r"tributos federais",
        ],
        "checklist",
    ),
    (
        "cnd_estadual",
        "Certidão Negativa de Débitos Estaduais (SEFAZ)",
        "Regularidade Fiscal e Trabalhista",
        [
            r"certid[ãa]o[^.\n]{0,30}d[ée]bitos[^.\n]{0,20}estadua",
            r"regularidade[^.\n]{0,20}fazenda estadual",
            r"\bSEFAZ\b",
            r"tributos estaduais",
        ],
        "checklist",
    ),
    (
        "cnd_municipal",
        "Certidão Negativa de Débitos Municipais",
        "Regularidade Fiscal e Trabalhista",
        [
            r"certid[ãa]o[^.\n]{0,30}d[ée]bitos[^.\n]{0,20}municipa",
            r"regularidade[^.\n]{0,20}fazenda municipal",
            r"tributos municipais",
        ],
        "checklist",
    ),
    (
        "fgts",
        "Regularidade do FGTS (CRF)",
        "Regularidade Fiscal e Trabalhista",
        [
            r"\bFGTS\b",
            r"\bCRF\b",
            r"certificado de regularidade[^.\n]{0,20}fgts",
            r"fundo de garantia",
        ],
        "checklist",
    ),
    (
        "cndt_trabalhista",
        "Certidão Negativa de Débitos Trabalhistas (CNDT)",
        "Regularidade Fiscal e Trabalhista",
        [
            r"\bCNDT\b",
            r"d[ée]bitos trabalhistas",
            r"certid[ãa]o[^.\n]{0,20}trabalhista",
            r"justi[çc]a do trabalho",
            r"\bTST\b",
        ],
        "checklist",
    ),

    # ------------------------------------------------------------------ #
    # 4) QUALIFICAÇÃO ECONÔMICO-FINANCEIRA
    # ------------------------------------------------------------------ #
    (
        "balanco_patrimonial",
        "Balanço Patrimonial e Demonstrações Contábeis",
        "Qualificação Econômico-Financeira",
        [
            r"balan[çc]o patrimonial",
            r"demonstra[çc][õo]es cont[áa]beis",
            r"escritura[çc][ãa]o cont[áa]bil",
        ],
        "checklist",
    ),
    (
        "indices_contabeis",
        "Índices contábeis (liquidez, solvência)",
        "Qualificação Econômico-Financeira",
        [
            r"[íi]ndice[s]? cont[áa]bil",
            r"[íi]ndice[s]? de liquidez",
            r"liquidez (geral|corrente)",
            r"solv[êe]ncia",
            r"grau de endividamento",
        ],
        "checklist",
    ),
    (
        "certidao_falencia",
        "Certidão de Falência e Concordata",
        "Qualificação Econômico-Financeira",
        [
            r"fal[êe]ncia",
            r"concordata",
            r"recupera[çc][ãa]o (judicial|extrajudicial)",
            r"certid[ãa]o[^.\n]{0,20}distribui[çc][ãa]o",
        ],
        "checklist",
    ),

    # ------------------------------------------------------------------ #
    # 5) QUALIFICAÇÃO TÉCNICA
    # ------------------------------------------------------------------ #
    (
        "atestado_capacidade",
        "Atestado de Capacidade Técnica",
        "Qualificação Técnica",
        [
            r"atestado de capacidade t[ée]cnica",
            r"atestado[^.\n]{0,20}aptid[ãa]o",
            r"comprova[çc][ãa]o[^.\n]{0,20}aptid[ãa]o t[ée]cnica",
        ],
        "checklist",
    ),
    (
        "licenca_sanitaria",
        "Licença Sanitária (Vigilância)",
        "Qualificação Técnica",
        [
            r"licen[çc]a sanit[áa]ria",
            r"vigil[âa]ncia sanit[áa]ria",
            r"licen[çc]a de funcionamento[^.\n]{0,30}(sanit|vigil)",
            r"alvar[áa] sanit[áa]rio",
        ],
        "checklist",
    ),
    (
        "afe_anvisa",
        "AFE – Autorização de Funcionamento (ANVISA)",
        "Qualificação Técnica",
        [
            r"\bAFE\b",
            r"autoriza[çc][ãa]o de funcionamento",
            r"autoriza[çc][ãa]o[^.\n]{0,20}empresa[^.\n]{0,20}anvisa",
        ],
        "checklist",
    ),
    (
        "responsavel_tecnico",
        "Responsável Técnico / Conselho de Classe (CRF/COREN)",
        "Qualificação Técnica",
        [
            r"respons[áa]vel t[ée]cnico",
            r"conselho de classe",
            r"\bCRF\b(?![-\s]*FGTS)",
            r"\bCOREN\b",
            r"\bCRM\b",
            r"certid[ãa]o[^.\n]{0,20}conselho regional",
        ],
        "checklist",
    ),
    (
        "registro_produtos_anvisa",
        "Registro dos produtos na ANVISA",
        "Qualificação Técnica",
        [
            r"registro[^.\n]{0,30}anvisa",
            r"registro[^.\n]{0,20}(no )?(MS|minist[ée]rio da sa[úu]de)",
            r"n[úu]mero de registro[^.\n]{0,20}(anvisa|produto)",
            r"RDC\s*185",
        ],
        "checklist",
    ),
    (
        "catalogos_fichas",
        "Catálogos / Fichas técnicas",
        "Qualificação Técnica",
        [
            r"cat[áa]logo",
            r"ficha[s]? t[ée]cnica",
            r"prospecto",
            r"folder[^.\n]{0,20}t[ée]cnico",
        ],
        "checklist",
    ),
    (
        "amostras_produtos",
        "Amostras dos produtos",
        "Qualificação Técnica",
        [
            r"amostra[s]? do[s]? produto",
            r"apresenta[çc][ãa]o de amostra",
        ],
        "checklist",
    ),

    # ------------------------------------------------------------------ #
    # 6) DOCUMENTAÇÃO COMPLEMENTAR — Declarações
    # ------------------------------------------------------------------ #
    (
        "decl_trabalho_infantil",
        "Declaração – não uso de mão de obra infantil (art. 7º, XXXIII)",
        "Documentação Complementar (Declarações)",
        [
            r"art(igo)?\.?\s*7[ºo][^.\n]{0,20}XXXIII",
            r"m[ãa]o[- ]de[- ]obra infantil",
            r"trabalho[^.\n]{0,10}menor[^.\n]{0,20}(16|dezesseis)",
            r"n[ãa]o emprega[^.\n]{0,20}menor",
        ],
        "checklist",
    ),
    (
        "decl_fatos_impeditivos",
        "Declaração – inexistência de fatos impeditivos / idoneidade",
        "Documentação Complementar (Declarações)",
        [
            r"fatos? impeditivos?",
            r"inexist[êe]ncia[^.\n]{0,20}impeditiv",
            r"declara[çc][ãa]o[^.\n]{0,20}idoneidade",
        ],
        "checklist",
    ),
    (
        "decl_me_epp",
        "Declaração de enquadramento ME/EPP + Certidão Simplificada",
        "Documentação Complementar (Declarações)",
        [
            r"enquadramento[^.\n]{0,20}(me|epp|microempresa)",
            r"certid[ãa]o simplificada",
            r"declara[çc][ãa]o[^.\n]{0,30}(me/epp|pequeno porte)",
        ],
        "checklist",
    ),
    (
        "decl_ciencia_edital",
        "Termo de ciência e cumprimento do edital",
        "Documentação Complementar (Declarações)",
        [
            r"termo de ci[êe]ncia",
            r"declara[çc][ãa]o[^.\n]{0,20}cumprimento[^.\n]{0,20}edital",
            r"pleno conhecimento[^.\n]{0,20}edital",
        ],
        "checklist",
    ),
    (
        "decl_lgpd",
        "Declaração LGPD",
        "Documentação Complementar (Declarações)",
        [
            r"\bLGPD\b",
            r"prote[çc][ãa]o[^.\n]{0,10}dados pessoais",
            r"lei geral de prote[çc][ãa]o",
            r"lei\s*13\.?709",
        ],
        "checklist",
    ),
    (
        "decl_pcd",
        "Declaração de reserva de cargos PCD",
        "Documentação Complementar (Declarações)",
        [
            r"reserva de cargos[^.\n]{0,20}(pcd|defici[êe]nte)",
            r"pessoa[s]? com defici[êe]ncia",
            r"\bPCD\b",
        ],
        "checklist",
    ),
    (
        "decl_parentesco",
        "Declaração de não parentesco com o município",
        "Documentação Complementar (Declarações)",
        [
            r"n[ãa]o parentesco",
            r"grau de parentesco",
            r"nepotismo",
        ],
        "checklist",
    ),
    (
        "decl_trabalho_degradante",
        "Declaração de não trabalho degradante ou forçado",
        "Documentação Complementar (Declarações)",
        [
            r"trabalho[^.\n]{0,10}degradante",
            r"trabalho[^.\n]{0,10}for[çc]ado",
            r"trabalho escravo",
            r"condi[çc][ãa]o an[áa]loga",
        ],
        "checklist",
    ),
    (
        "decl_anticorrupcao",
        "Declaração de prevenção à corrupção",
        "Documentação Complementar (Declarações)",
        [
            r"preven[çc][ãa]o[^.\n]{0,10}corrup[çc][ãa]o",
            r"anticorrup[çc][ãa]o",
            r"lei\s*12\.?846",
            r"integridade[^.\n]{0,20}corrup[çc][ãa]o",
        ],
        "checklist",
    ),
    (
        "decl_comprometimento",
        "Declaração de comprometimento com a entrega e custos inclusos",
        "Documentação Complementar (Declarações)",
        [
            r"comprometimento[^.\n]{0,20}entrega",
            r"custos operacionais[^.\n]{0,30}inclusos",
            r"encargos[^.\n]{0,20}(previdenci|trabalhist|tribut)[^.\n]{0,30}inclu",
        ],
        "checklist",
    ),
    (
        "decl_assinatura_contrato",
        "Declaração do responsável pela assinatura do contrato",
        "Documentação Complementar (Declarações)",
        [
            r"respons[áa]vel[^.\n]{0,20}assinatura[^.\n]{0,20}contrato",
            r"declara[çc][ãa]o[^.\n]{0,20}assinatura[^.\n]{0,20}contrato",
        ],
        "checklist",
    ),
    (
        "decl_ambiental",
        "Declaração de contratação sustentável (política ambiental)",
        "Documentação Complementar (Declarações)",
        [
            r"contrata[çc][ãa]o sustent[áa]vel",
            r"pol[íi]tica ambiental",
            r"sustentabilidade ambiental",
        ],
        "checklist",
    ),
]

# HospMedic Bid Intelligence (HBI) — MVP

Automação da análise inicial de editais públicos de produtos hospitalares.
O MVP lê um edital em PDF, valida critérios de participação (**GO / NO-GO /
REVISAR**), extrai a tabela de itens do Termo de Referência e preenche a
planilha padrão da HospMedic — mantendo a **revisão humana como etapa final**.

> Alinhado ao *Documento Mestre de Contexto* (v1.0): foco exclusivo no MVP,
> arquitetura modular, simplicidade, rastreabilidade e evolução incremental.

---

## O que o MVP faz

1. **Lê** o edital em PDF (`pdf_reader`).
2. **Valida** critérios de participação e dá um veredito GO/NO-GO
   (`edital_validator`), com a **evidência textual** de cada critério.
3. **Extrai** Item, Descrição, Unidade, Quantidade e Valor Estimado
   (`table_extractor`), organizando em objetos de domínio.
4. **Preenche** a planilha-modelo da HospMedic, preservando as fórmulas, e
   adiciona uma coluna **Confere** (`excel_exporter`).
5. **Relata** o resultado em texto para apoiar a revisão (`services/report`).

Fluxo TO-BE:
`seleção do PDF → leitura → validação → extração → organização → preenchimento → revisão humana`

---

## Como rodar

```bash
pip install -r requirements.txt

# pipeline completo: validação + extração + planilha
python main.py data/input/PE_10-2026_Xambre.pdf \
    --out data/output/PE_10-2026_Xambre.xlsx \
    --relatorio data/output/PE_10-2026_Xambre_relatorio.txt

# somente validação de critérios (GO/NO-GO), sem extrair itens nem planilha
python main.py data/input/PE_10-2026_Xambre.pdf --somente-validacao \
    --relatorio data/output/validacao.txt
```

O modo `--somente-validacao` é uma triagem rápida: lê só as páginas iniciais,
aplica as regras GO/NO-GO e mostra o veredito com as evidências — sem rodar a
extração da tabela nem gerar a planilha.

Saídas:
- `data/output/<edital>.xlsx` — planilha padrão preenchida (com a coluna *Confere*).
- `data/output/<edital>_relatorio.txt` — relatório GO/NO-GO + conferência.
- `logs/hbi.log` — log de execução (rastreabilidade).

Testes de fumaça (sem dependências externas):

```bash
python tests/test_pipeline.py
```

---

## Arquitetura (modular, responsabilidade única)

```
hbi/
├── main.py                     # CLI (ponto de entrada)
├── requirements.txt
├── data/
│   ├── input/                  # editais em PDF
│   ├── output/                 # planilhas + relatórios gerados
│   └── Modelo_de_Planilha_de_Licitacao.xlsx   # modelo da HospMedic
├── hbi/
│   ├── config/settings.py      # caminhos, layout de colunas, regras GO/NO-GO
│   ├── models/edital.py        # Edital, ItemEdital, CriterioValidacao...
│   ├── modules/
│   │   ├── pdf_reader.py        # leitura de baixo nível do PDF
│   │   ├── edital_validator.py  # validação GO/NO-GO + metadados
│   │   ├── table_extractor.py   # extração da tabela de itens
│   │   └── excel_exporter.py    # preenchimento da planilha padrão
│   ├── services/
│   │   ├── pipeline.py          # orquestra o fluxo TO-BE
│   │   └── report.py            # relatório textual
│   └── utils/
│       ├── logger.py            # logging (console + arquivo)
│       └── text.py              # conversões BRL, normalização
└── tests/test_pipeline.py
```

Cada informação extraída carrega a **página de origem** (rastreabilidade).

---

## Validação GO / NO-GO

As regras vivem em `hbi/config/settings.py` (`REGRAS_VALIDACAO`) e derivam do
*Espelho de Documentos de Licitação Hospitalar*. Cada regra tem um **impacto**:

- `no_go` — se presente, tende a **bloquear** a participação.
- `atencao` — exige documento/conferência; entra como **ponto de revisão**.
- `go` — sinal esperado de um edital compatível.

O veredito é conservador: exigências detectadas geram **REVISAR**, nunca uma
recusa automática — a decisão é do time da HospMedic.

Exemplo de saída (edital PE 10/2026 — Xambrê-PR):

```
VEREDITO      : REVISAR
Itens         : 207
Soma extraída : R$ 801.434,08
Conferência   : soma dos itens x valor do edital -> OK
  [x] (atencao) Exige AFE (ANVISA)
  [x] (atencao) Exige Atestado de Capacidade Técnica
  [x] (go     ) Menor preço por item
  ...
```

---

## Conferência automática

Para cada item, o sistema verifica se `quantidade × valor_estimado = valor_total`.
Divergências são marcadas como **REVISAR** (célula destacada) na coluna *Confere*
da planilha — apoiando a revisão humana sem substituí-la.

No edital de referência, a soma dos 207 itens reconciliou **exatamente** com o
valor global declarado (R$ 801.434,08) e todos os itens passaram na conferência.

---

## Limitações conhecidas (MVP) e próximos passos

- **Layout de tabela**: a extração usa as coordenadas de coluna em
  `settings.COLUNAS_X`, calibradas para o padrão de tabela deste edital.
  Editais com outro layout de Termo de Referência exigem recalibração dessas
  fronteiras (ou uma etapa de autodetecção de colunas — evolução futura).
- **Regras de validação**: baseadas em busca textual; casos com redação
  atípica podem exigir ajuste dos padrões.
- **Marca / Reg. Anvisa**: colunas preenchidas manualmente pela HospMedic
  (dependem do catálogo interno — fora do escopo do MVP).

Fora do MVP (visão de longo prazo do documento mestre): integração com o
catálogo da HospMedic, banco de dados, APIs, dashboards e apoio à decisão.

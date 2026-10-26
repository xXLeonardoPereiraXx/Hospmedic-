# HospMedic Bid Intelligence (HBI) — MVP

Automação da análise inicial de editais públicos de produtos hospitalares.
O HBI lê um edital em PDF, valida os critérios de participação (**GO /
NO-GO / REVISAR**), extrai a tabela de itens do Termo de Referência e
preenche a planilha padrão da HospMedic — mantendo a **revisão humana como
etapa final** do fluxo.

> Alinhado ao *Documento Mestre de Contexto* (v1.0): foco exclusivo no MVP,
> arquitetura modular, simplicidade, rastreabilidade e evolução incremental.

---

## O que o sistema faz

1. **Lê** o edital em PDF (`pdf_reader`), com dois extratores: pypdf para a
   varredura textual da validação (~4x mais rápido) e pdfplumber para a
   extração da tabela de itens.
2. **Valida** o edital contra um catálogo de **39 critérios** derivado do
   *Espelho de Documentos de Licitação Hospitalar* (`edital_validator` +
   `config/criterios_espelho.py`), registrando a **evidência textual** de
   cada critério encontrado.
3. **Extrai** Item, Descrição, Unidade, Quantidade, Valor Unitário e Valor
   Total da tabela de itens (`table_extractor`), por **âncoras numéricas** —
   estratégia independente do layout do edital (ver seção abaixo).
4. **Reúne descritivos separados** (`spec_extractor`): quando o edital põe
   quantidade/valores na tabela e a especificação técnica completa em outra
   seção, os dois lados são unidos pelo lote ou pelo número do item.
5. **Preenche** a planilha-modelo da HospMedic (`excel_exporter`),
   regravando as fórmulas de custo/lance/total e acrescentando a coluna
   **Confere** (e **Lote**, quando o edital disputa por lote).
6. **Relata** o resultado (`services/report`): veredito, gate de
   confiabilidade da extração, diagnóstico do join de descritivos e
   checklist de habilitação por categoria.

Fluxo TO-BE:
`seleção do PDF → leitura → validação → extração → organização → preenchimento → revisão humana`

Duas formas de uso: **CLI** (`main.py`) e **interface web** com login
(`webapp/`, Flask) — a web reaproveita integralmente o pipeline.

---

## Como rodar (CLI)

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

O modo `--somente-validacao` é a triagem rápida: varre o texto do edital
inteiro, aplica os critérios e mostra o veredito com evidências e o
checklist de habilitação — sem rodar a extração da tabela nem gerar
planilha. Nesse modo o relatório exibe o valor global **declarado** no
edital apenas como referência de porte; no modo completo, o valor oficial é
a **soma dos itens extraídos**.

Saídas:
- `data/output/<edital>.xlsx` — planilha padrão preenchida.
- `data/output/<edital>_relatorio.txt` — relatório GO/NO-GO + conferência.
- `logs/hbi.log` — log de execução (rastreabilidade).

Testes de fumaça (sem depender de PDFs ou bibliotecas externas):

```bash
python tests/test_pipeline.py
```

Para a interface web e o deploy no Render, ver `webapp/LEIA-ME_WEB.md`.

---

## Arquitetura (modular, responsabilidade única)

```
hbi/
├── main.py                     # CLI (ponto de entrada)
├── requirements.txt
├── render.yaml                 # blueprint de deploy (Render)
├── data/
│   ├── input/                  # editais em PDF (inclui teste_cego/)
│   ├── output/                 # planilhas + relatórios gerados
│   └── Modelo_de_Planilha_de_Licitacao.xlsx   # modelo da HospMedic
├── hbi/
│   ├── config/
│   │   ├── settings.py          # caminhos, tolerância, layout da planilha
│   │   └── criterios_espelho.py # catálogo de 39 critérios (com variantes)
│   ├── models/edital.py         # Edital, ItemEdital, CriterioValidacao...
│   ├── modules/
│   │   ├── pdf_reader.py        # leitura de baixo nível (pdfplumber + pypdf)
│   │   ├── edital_validator.py  # validação GO/NO-GO + metadados
│   │   ├── table_extractor.py   # extração da tabela por âncoras numéricas
│   │   ├── spec_extractor.py    # descritivos técnicos em seção separada
│   │   └── excel_exporter.py    # preenchimento da planilha padrão
│   ├── services/
│   │   ├── pipeline.py          # orquestra o fluxo TO-BE
│   │   └── report.py            # relatórios (completo e de triagem)
│   └── utils/
│       ├── logger.py            # logging (console + arquivo)
│       └── text.py              # conversões BRL, normalização
├── webapp/                      # camada web (Flask): login, upload, histórico
└── tests/test_pipeline.py
```

Cada item extraído carrega a **página de origem** (rastreabilidade) e cada
critério presente carrega a **evidência textual** que o embasou.

---

## Extração por âncoras numéricas (independente de layout)

A extração **não usa coordenadas de coluna**: ela reconhece cada item por
uma **âncora** — uma linha que contém o número do item e valores
monetários — e é validada pela própria matemática da linha. Regras:

1. **Âncora numérica**: linha iniciada por um inteiro e terminando em dois
   valores monetários (unitário e total), tolerando prefixo `R$` (com ou
   sem espaço), 2 a 4 casas decimais e colunas finais que não são valores
   (traços `- - - -` ou margens textuais como `MedNac 5%`).
2. **Contagem incremental**: a âncora só é aceita se o número for o próximo
   esperado (1, 2, 3, …), com folga limitada para saltos. Isso rejeita
   falsos-positivos de dígitos soltos. Em editais **por lote**, a contagem
   reinicia a cada `Lote: N`.
3. **Fronteira por regime de participação**: em editais que marcam a reserva
   item a item (`EXCLUSIVO MEI/ME/EPP`, `AMPLA PARTICIPAÇÃO`, `COTA ME/EPP`),
   esse rótulo abre o bloco de um item e funciona como fronteira estrutural.
   Sem ele, a descrição de um item invade a do vizinho — e o começo do texto,
   que nesses layouts fica **acima** da linha-âncora, seria atribuído ao item
   anterior.
4. **Layout invertido**: quando a linha de valores não começa pelo número
   (descrição + valores) e o número abre a linha seguinte, o par é
   reconhecido em conjunto.
5. **Valor quebrado**: quando o PDF parte um valor para outra linha (um
   `R$` órfão e o número deslocado — inclusive misturado a texto ou
   empurrado para depois de rodapé em quebra de página), o valor é buscado
   numa janela ao redor da âncora. Perto da âncora, basta a razão
   total/unitário ser inteira; longe dela, só é aceito se `qtd × unitário
   == total` fechar exatamente. A quantidade também pode ser a **soma** de
   múltiplas colunas de quantidade (editais com mais de um destinatário).
6. **Quantidade derivada**: calculada de `valor_total / valor_unitário`
   (os dois dados mais confiáveis da linha); o parse do miolo da âncora
   serve de verificação cruzada.
7. **Descrição**: montada dos fragmentos ao redor da âncora (antes, depois
   ou na própria linha, conforme o layout), ordenados pela posição de
   origem. Fronteiras estruturais (cabeçalho de tabela, linhas de `TOTAL`,
   início de lote) impedem que texto "vaze" de um item para outro.

Layouts validados com os editais de `data/input/`:

| Edital | Layout | Itens | Conferência |
|---|---|---|---|
| Xambrê (PE 10/2026) | grade de células | 207/207 | soma exata, 0 divergências |
| Curiúva (PE 12/2026) | por lote (portal BLL) | 278/278 | soma exata, 0 divergências |
| Florianópolis | invertido (valores antes do número) | 412+ | 0 divergências |
| Paranacity | prefixo R$ + valores quebrados | 406/406 | soma exata = valor declarado |
| Campo Largo (PE 56/2026, itens) | compacto, item na própria linha | 112/112 | 0 divergências |
| São José dos Pinhais | grade | 22/22 | soma exata, 0 divergências |
| 5ª Brigada (TR 28/2026) | colunas de margem + valores quebrados | 187/187 | 0 divergências |
| SESA/PR (PE 713/2026) | ficha por lote (`ITEM 1 PEÇA …`) | 22/22 | soma exata = valor declarado |
| FEAS/Curitiba (PE 70/2026) | **sem tabela** — itens em blocos de texto | 13/13 | sequência completa |
| ICS/Curitiba (PE 11/2026) | descrição acima e abaixo da âncora, com rótulo de regime | 21/21 | 0 divergências |
| Campo do Tenente (PE 18/2026) | por lote, descrição multilinha | 39/39 | 0 divergências |
| Unicentro (PE 828/2026) | tabela simples, item zero-padded | 5/5 | 0 divergências |

### Estratégia C — células da tabela (PDF que embaralha o texto)

Alguns PDFs entrelaçam as colunas ao achatar o texto: a coluna de marca cai no
meio da descrição, palavras saem partidas (`"Agulha de scartável"`) e um valor
é dividido entre três linhas. Quando o arquivo **desenha** a tabela, a grade é
informação melhor que o texto — cada célula é lida no lugar certo, inclusive
colunas que a leitura linear nem enxerga.

A escolha é automática e por evidência, não por tipo de arquivo: roda-se a
leitura por âncoras e, se a sequência 1..N ficou incompleta, compara-se com a
leitura por grade; fica a que cobre mais itens. O extrator ainda testa dois
recortes de coluna (fixo para o documento ou por página) e adota o que
reconhece mais linhas de item, resolve o ponto ambíguo de milhar/decimal pela
própria aritmética da linha (`1.332` vira `1,332` quando é isso que fecha com
o total) e descarta itens repetidos em tabelas anexas, mantendo a ocorrência
cuja conta fecha.

### Estratégia B — itens em blocos de texto (edital sem tabela)

Alguns editais não têm tabela de itens: cada item é um **bloco de texto
rotulado**, com os dados em linhas próprias.

```
Item 2: 66376/ BR0619857/ Luva para Procedimento em Látex Tamanho P
Luva de procedimento P, não cirúrgica, em látex natural ...
Quantidade: 2.400.000 unidades
Valor máximo permitido: R$ 0,2200
```

Quando a varredura por âncoras não encontra tabela alguma, o extrator cai
automaticamente para esta estratégia: segmenta por `Item N:`, lê quantidade e
valor unitário das linhas rotuladas (aceitando variantes como "Valor unitário
máximo" e "Quantidade estimada") e monta a descrição com o texto do bloco. A
contagem incremental descarta menções a "Item N" em cláusulas do edital.

Nesses editais **não há valor total impresso** — ele é derivado de
`qtd × unitário`. Por isso a conferência automática não é evidência
independente aqui, e o gate de extração se apoia na completude da sequência.

### Cabeçalho e rodapé de página

Quando um item atravessa a quebra de página, o bloco de cabeçalho/rodapé do
edital (órgão, endereço, "Página X de Y", modelo da minuta) cai **no meio da
descrição**. A limpeza não usa lista de palavras — apagar linhas por conterem
"produto", "registro" ou "validade" mutilaria descrições legítimas. Em vez
disso, o cabeçalho e o rodapé são identificados como o **prefixo e o sufixo
contíguos** que se repetem na maioria das páginas: a varredura avança a partir
da borda e para no primeiro desacordo, de modo que uma frase de descrição que
por acaso se repita no miolo nunca é alcançada. Em páginas curtas as faixas
encolhem para no máximo um terço da página.

### Marca d'água (carimbo de protocolo)

Editais publicados por portais de protocolo trazem um carimbo diagonal em
todas as páginas. O extrator de texto intercala esses caracteres com o
conteúdo, partindo palavras no meio (`"para que ha" + "j a3 melhor ajuste"`).
O `pdf_reader.sem_marca_dagua` descarta os caracteres **rotacionados** (matriz
de transformação com termo de inclinação não nulo), removendo o carimbo sem
tocar em nenhum caractere do corpo do documento.

---

## Descritivos técnicos em seção separada

Editais do padrão SESA/Curitiba (e derivados) dividem o item em duas partes
do documento: a **tabela**, com quantidade, unidade e valores — onde a
descrição vem resumida — e uma **seção de especificações técnicas**, onde o
descritivo íntegro aparece indexado por um rótulo. O `spec_extractor` lê a
segunda parte e faz o *join* com os itens já extraídos.

Duas formas de indexação são suportadas, e a escolha é feita **por
documento**, pela predominância dos rótulos encontrados:

- **por lote** — `LOTES 1 E 2: CURATIVO FIX CATÉTER CURTA PERMANÊNCIA.`
  (edital organizado em lotes, cada um com item único; a numeração de item
  reinicia a cada lote, então o lote é a única chave estável);
- **por item** — `ITEM 5: SERINGA DESCARTÁVEL 20 ml` (itens soltos, com
  numeração corrida ao longo do edital).

Como funciona:

1. **Localiza a seção** pelo cabeçalho (`1.2 ESPECIFICAÇÕES TÉCNICAS` e
   variantes). Sem cabeçalho identificável, varre o documento inteiro — os
   rótulos se autoidentificam.
2. **Segmenta por âncoras de rótulo**: cada bloco vai do seu rótulo até o
   próximo, ou até o fim da seção (`1.2.1 Requisitos…`, `2. DA JUSTIFICATIVA`).
   O texto não é removido do documento; fatiar preserva as fronteiras.
3. **Expande o rótulo em chaves**: um bloco pode cobrir vários lotes de uma
   vez, e o edital alterna as formas (`LOTES 1 E 2`, `LOTE 17 e 18`).
4. **Limpa o corpo** de rodapés institucionais e cabeçalhos de página.
5. **Une ao item**, preservando a descrição resumida da tabela (que traz os
   códigos GMS/CATMAT, ausentes na seção de especificações).

O relatório informa quantos itens foram enriquecidos, quais ficaram **sem
descritivo** e quais descritivos ficaram **órfãos** — os dois últimos são
pontos de revisão humana, não erros silenciosos. Editais cuja tabela já traz
a descrição completa passam intactos pelo módulo.

---

## Validação GO / NO-GO

Os critérios vivem em `hbi/config/criterios_espelho.py`, organizados nas
seções do Espelho de Documentos (Decisão, Habilitação Jurídica,
Regularidade Fiscal e Trabalhista, Qualificação Econômico-Financeira,
Qualificação Técnica e Documentação Complementar). Cada critério tem uma
lista de **variantes/sinônimos** (basta uma casar) e um **impacto**:

- `no_go` — se presente, tende a **bloquear** a participação;
- `atencao` — exige documento/análise; entra como **ponto de revisão**;
- `go` — sinal esperado de um edital compatível;
- `checklist` — documento de habilitação padrão: compõe a lista de
  conferência, mas **não altera o veredito**.

Salvaguardas contra falsos-positivos:

- Rótulos de quadro-resumo respondidos com **"NÃO"** (ex.: `EXCLUSIVO
  ME/EPP: NÃO`) não contam como presença do critério.
- Para a exclusividade ME/EPP, o **quadro-resumo é a fonte autoritativa**
  quando existe (formatos "rótulo: Sim/Não" e quadro de colunas achatado),
  com prioridade sobre a varredura textual.

O veredito é conservador: exigências detectadas geram **REVISAR**, nunca
recusa automática — a decisão final é do time da HospMedic. A validação
varre o **documento inteiro** (a habilitação costuma ficar no meio/fim do
edital), usando o extrator rápido.

Também são detectados metadados: **órgão**, **número do pregão** e os
**valores globais declarados** no texto.

---

## Conferência automática e gate de extração

Para cada item, o sistema verifica se `quantidade × valor_unitário =
valor_total` (tolerância de R$ 0,50, em `settings.TOLERANCIA_TOTAL`).
Divergências são marcadas como **REVISAR** (célula destacada) na coluna
*Confere* da planilha.

O relatório traz ainda um **gate de confiabilidade da extração**, baseado
apenas em evidência interna dos dados:

- **CONFIAVEL** — sequência de itens 1..N completa **e** ≥98% das linhas
  consistentes;
- **REVISAR** — sequência incompleta, consistência baixa ou poucos itens
  (< 3) para haver evidência suficiente.

O valor global declarado no edital **não** é usado como âncora do gate:
editais frequentemente declaram valores que divergem entre si (soma dos
itens vs. verba disponível). O número oficial é a soma dos itens extraídos.

---

## Planilha gerada

O `excel_exporter` parte da planilha-modelo da HospMedic e:

- preenche as colunas de entrada (Item, Descrição Edital, Unidade,
  Quantidade, Estimado Edital) — a descrição vem **como escrita no
  edital**;
- regrava, linha a linha, as fórmulas de **Lance Mínimo**, **Total** e
  **Total Edital** do modelo, zerando os defaults (ICMS, Frete, Margem);
- acrescenta as colunas **Confere** (conferência automática) e **Lote**
  (somente em editais por lote, onde a numeração global é sequencial e o
  lote fica registrado à parte);
- fecha com a linha de **TOTAL** somando as colunas de valores.

### Termos críticos em destaque

Detalhes da especificação que decidem a cotação saem na planilha em **negrito
e vermelho**, dentro da própria célula de descrição. Cada regra tem um
gatilho (o produto) e os termos a marcar — o gatilho evita ruído, já que
"sintética" só interessa em luva, não numa sonda de material sintético:

| Gatilho no item | Termos destacados |
|---|---|
| luva | com pó, c/pó, sem pó, s/pó, isento de pó, lubrifica, talcada, sintética |
| cateter intravenoso periférico, abocath | com/c/ dispositivo de segurança, conforme NR 32 |
| scalpe, escalpe, scalp | com/c/ dispositivo de segurança, conforme NR 32 |
| seringa, agulha | com/c/ dispositivo de segurança, conforme NR 32 |

A comparação ignora acento e caixa (`sem pó` = `SEM PO`), e trechos
sobrepostos viram uma marcação só. Para acrescentar uma regra basta editar
`hbi/config/regras_destaque.py` — nenhum outro arquivo muda.

As colunas *Marca* e *Reg. Anvisa* seguem manuais (dependem do catálogo
interno da HospMedic — fora do escopo do MVP).

---

## Interface web

A pasta `webapp/` expõe o mesmo pipeline no navegador (Flask), com a
**identidade visual da HospMedic**: logo na barra superior e na tela de
entrada, azul-marinho `#203763` e verde `#649A06` do manual de marca, e
tipografia Montserrat. O semáforo de decisão (GO / REVISAR / NO-GO) usa o
verde da marca no GO e tons calibrados de âmbar e vermelho — as cores ali são
funcionais, para leitura imediata do veredito, não decorativas.

Recursos:

- login por sessão com senhas **em hash** (usuários semeados da variável
  `HBI_USERS` a cada boot — os acessos sobrevivem ao disco efêmero do
  Render);
- upload do PDF (até 30 MB) e escolha do modo (triagem ou completo);
- exibição do relatório, download da planilha e **histórico de análises**
  por usuário (SQLite);
- endpoint `/health` para checagem de disponibilidade;
- deploy no Render via blueprint (`render.yaml`), com HTTPS automático.

Guia completo (rodar local, variáveis, free tier): `webapp/LEIA-ME_WEB.md`.

---

## Limitações conhecidas (MVP) e próximos passos

- **Novos layouts de tabela**: a âncora genérica foi validada nos sete
  layouts acima; padrões inéditos de Termo de Referência podem exigir uma
  nova variante de âncora (o gate de extração acusa quando a sequência vem
  incompleta).
- **Descrições em layouts multi-coluna**: quando o PDF entrelaça a
  descrição de itens vizinhos, algum texto pode ser atribuído ao item
  errado — a coluna *Confere* e a revisão humana cobrem esses casos.
- **Regras de validação**: baseadas em busca textual; redações muito
  atípicas podem exigir novas variantes no catálogo.
- **Editais em dois arquivos** (ex.: Campo Largo separa edital e itens):
  cada PDF é processado individualmente — rodar a validação no arquivo do
  edital e a extração no arquivo de itens.

Fora do MVP (visão de longo prazo do documento mestre): integração com o
catálogo da HospMedic, banco de dados estruturado, APIs, dashboards e
apoio à decisão.

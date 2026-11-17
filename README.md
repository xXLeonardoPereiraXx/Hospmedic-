# HospMedic Bid Intelligence (HBI)

Automação da análise inicial de editais públicos de produtos hospitalares.
O HBI lê um edital em PDF, valida os critérios de participação (**GO /
NO-GO / REVISAR / ILEGÍVEL**), extrai a tabela de itens, preenche a planilha
padrão da HospMedic e gera o **espelho de critérios em PDF** — mantendo a
**revisão humana como etapa final** do fluxo.

> Alinhado ao *Documento Mestre de Contexto*: automatizar tarefas
> operacionais sem substituir a decisão humana; simplicidade,
> confiabilidade, rastreabilidade e evolução incremental.

**Versão atual: v24.** O histórico de mudanças está nos arquivos
`CHANGELOG_vNN.md` (v17 em diante).

---

## O que o sistema faz

1. **Lê** o edital em PDF (`pdf_reader`): pypdf para a varredura textual da
   validação (rápida) e pdfplumber para a tabela de itens (posição de cada
   palavra e das bordas da tabela).
2. **Confere a legibilidade**: PDF cuja fonte não tem texto legível (letras
   viram símbolos) recebe o veredito **ILEGÍVEL**, sem avaliar critérios —
   nunca um GO falso.
3. **Valida** o edital contra o catálogo de **39 critérios** do *Espelho de
   Documentos* (`edital_validator` + `config/criterios_espelho.py`), com a
   **evidência textual** de cada critério encontrado, incluindo quadros-resumo
   com "Sim/Não" e caixas de marcar (☒/☐).
4. **Lê as informações gerais** (`info_edital`): órgão, sessão (data e hora),
   portal, validade da proposta, participação local/regional, e-mails,
   telefones e pregoeiro; confere com o nome do arquivo no padrão da equipe e
   aponta divergências.
5. **Lê as condições comerciais** (`condicoes_comerciais`): validade mínima
   dos produtos, prazo de pagamento, prazo de entrega e vigência da ata (ARP),
   cada uma com o trecho do edital.
6. **Extrai** Item, Descrição, Unidade, Quantidade, Valor Unitário e Valor
   Total, escolhendo entre várias estratégias pela que se prova mais íntegra
   (ver "Extração da tabela de itens").
7. **Reúne descritivos separados** (`spec_extractor`): tabela com valores e
   especificação técnica em outra seção, unidos pelo lote ou pelo item.
8. **Preenche** a planilha-modelo da HospMedic (`excel_exporter`), com a
   coluna **Confere** e, em editais por lote, a coluna **Lote**.
9. **Relata** o resultado: relatório `.txt` (`services/report`) e espelho de
   critérios em PDF com a logo da HospMedic (`services/espelho_pdf`).

Fluxo TO-BE:
`seleção do PDF → leitura → validação → extração → organização → preenchimento → revisão humana`

Três formas de uso, todas com o mesmo pipeline: **HBI.exe** (aplicativo de
computador), **interface web** (Flask, `webapp/`) e **CLI** (`main.py`).

---

## Como usar

### HBI.exe (recomendado para a equipe)
Passo a passo para gerar e distribuir em `COMO_GERAR_O_EXE.md`. Resumo:
envie a versão ao GitHub; o workflow **Gerar HBI.exe**
(`.github/workflows/gerar-exe.yml`) roda os testes, compila com PyInstaller
(`hbi.spec`) e entrega o `HBI-windows.zip`. Também dá para gerar no próprio
Windows com `gerar_exe.bat`.

O HBI.exe abre o navegador no próprio computador (127.0.0.1, sem login,
invisível para a rede). Dados, histórico e logs ficam em `%LOCALAPPDATA%\HBI`.

### Vários editais de uma vez
A tela de envio aceita vários PDFs ou um `.zip` (até 30 editais). Cada um é
processado na sequência ("Edital 3 de 7"); um erro num edital não interrompe
os demais. O resultado é um `.zip` com planilha, espelho e relatório de cada
edital e um `resumo.txt`.

### CLI

```bash
pip install -r requirements.txt

# pipeline completo: validação + extração + planilha
python main.py data/input/PE_10-2026_Xambre.pdf \
    --out data/output/PE_10-2026_Xambre.xlsx \
    --relatorio data/output/PE_10-2026_Xambre_relatorio.txt

# somente validação de critérios (triagem), sem extrair itens nem planilha
python main.py data/input/PE_10-2026_Xambre.pdf --somente-validacao \
    --relatorio data/output/validacao.txt
```

No modo `--somente-validacao` o relatório mostra o valor global
**declarado** apenas como referência de porte; no modo completo, o valor
oficial é a **soma dos itens extraídos**.

### Testes

```bash
pip install pytest
python -m pytest -q tests        # na raiz do projeto (40 testes na v24)
```

Os testes geram PDFs sintéticos com reportlab; não dependem dos editais.

Para a interface web e o deploy no Render, ver `webapp/LEIA-ME_WEB.md`.

---

## Arquitetura (modular, responsabilidade única)

```
hbi/
├── main.py                     # CLI
├── hbi_desktop.py              # HBI.exe: sobe o servidor local e abre o navegador
├── hbi.spec / gerar_exe.bat    # receita do PyInstaller / geração no Windows
├── .github/workflows/gerar-exe.yml
├── requirements.txt, render.yaml
├── data/
│   └── Modelo_de_Planilha_de_Licitacao.xlsx   # modelo da HospMedic
├── hbi/
│   ├── config/
│   │   ├── settings.py           # caminhos, tolerância, layout da planilha
│   │   ├── criterios_espelho.py  # catálogo de 39 critérios (com variantes)
│   │   └── regras_destaque.py    # termos críticos em vermelho na planilha
│   ├── models/edital.py          # Edital, ItemEdital, gate de extração
│   ├── modules/
│   │   ├── pdf_reader.py         # leitura de baixo nível (pdfplumber + pypdf)
│   │   ├── edital_validator.py   # GO/NO-GO, legibilidade, metadados
│   │   ├── info_edital.py        # informações gerais + conferência c/ nome do arquivo
│   │   ├── condicoes_comerciais.py  # validade, pagamento, entrega, vigência ARP
│   │   ├── table_extractor.py    # âncoras numéricas + escolha da estratégia
│   │   ├── cell_extractor.py     # leitura pelas células desenhadas (v24)
│   │   ├── col_extractor.py      # leitura pela posição das colunas (v22)
│   │   ├── grid_extractor.py     # grade do pdfplumber; fichas por lote
│   │   ├── unidades.py           # whitelist e limpeza da unidade (v24)
│   │   ├── spec_extractor.py     # descritivos técnicos em seção separada
│   │   └── excel_exporter.py     # preenchimento da planilha padrão
│   ├── services/
│   │   ├── pipeline.py           # orquestra o fluxo TO-BE
│   │   ├── report.py             # relatório .txt
│   │   └── espelho_pdf.py        # espelho de critérios em PDF
│   └── utils/                    # logger, texto/BRL, cancelamento
├── webapp/                       # Flask: login, upload, lote, histórico
└── tests/                        # test_pipeline, test_condicoes_v23,
                                  # test_celulas_v24, test_unidades_v24
```

Cada item extraído carrega a **página de origem** e cada critério presente
carrega a **evidência textual** que o embasou.

---

## Extração da tabela de itens

Não existe um layout único de edital. Por isso o HBI tem várias leituras e
**escolhe por evidência**, nunca por tipo de arquivo ou nome de órgão. A
régua é sempre a mesma: sequência de itens completa e conta
`quantidade × unitário = total` fechando. Uma leitura nova só substitui a
anterior quando se prova melhor.

### A — células desenhadas (v24, a mais precisa)
Quando o PDF desenha as bordas da tabela, essas coordenadas são a fronteira
entre itens: cada linha da tabela é a faixa entre duas bordas horizontais, e
cada palavra vai para a célula onde está o seu centro. A descrição de um item
não tem como cair na célula de outro, e a unidade vem da própria coluna de
unidade.

Detalhes tratados: bordas desenhadas célula a célula; retângulos internos e
fios decorativos de página; tabela deslocada entre páginas (colunas pela
posição relativa); cabeçalho com letras espaçadas ou células mescladas;
coluna de descrição chamada "ITEM"; item cortado pela quebra de página
(inclusive descrição que atravessa duas páginas e valores na página
seguinte); número de página e cabeçalhos repetidos dentro da grade.

É adotada só se: a conta fecha em 98%+ das linhas, a numeração não tem
saltos, nenhum texto ficou sem dono entre dois itens seguidos e a tabela não
aparece repetida (o valor dobraria). Com os mesmos números da leitura
anterior, troca só o texto, e campos vazios na célula ficam com o valor que
a leitura anterior tinha.

### B — âncoras numéricas (tabelas sem bordas)
Reconhece cada item por uma **âncora** — linha com o número do item e os
valores monetários — e monta a descrição com o texto ao redor. Regras
principais: contagem incremental (rejeita dígitos soltos; reinicia por
lote), fronteiras estruturais (cabeçalho, TOTAL, lote, regime de
participação), layout invertido, valores quebrados entre linhas, quantidade
derivada de total ÷ unitário e topo de página decidido pelo equilíbrio do
bloco. É a leitura que adivinha fronteiras pelo texto; por isso, quando há
bordas, a leitura A tem prioridade.

### C — escolha de tabela, fichas por lote e grade
- **Mais de uma tabela de itens** (TR, mapa de cotações, modelo de proposta):
  cada tabela com coluna de valor é lida e vence a que tem mais contas
  fechando (Porto Amazonas).
- **Uma tabela por lote**: quando há mais títulos de lote que itens lidos,
  as fichas de lote são relidas (Fundo Estadual de Saúde).
- **Grade do pdfplumber**: quando a sequência sai com buracos, compara-se com
  a leitura por grade e fica a que cobre mais itens.

### D — posição das colunas (v22)
Para relatórios de sistema sem grade que despejam o texto fora da ordem
visual (Londrina): cada palavra vai para a coluna pela coordenada x do
cabeçalho. Só entra com descrições contaminadas e só é adotada com os mesmos
números.

### E — itens em blocos de texto (edital sem tabela)

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

### Unidades (v24)
Na leitura por texto a unidade é adivinhada; na leitura A ela vem da coluna.
Em ambos os casos o campo passa pela whitelist de `unidades.py`:
- letras espaçadas pelo PDF viram a unidade ("UN D" → UND, "ME TR O" →
  METRO);
- unidade fora da lista (ex.: "Luva", nome do produto) é trocada só com
  evidência: a quantidade do item seguida de uma unidade da lista na
  descrição ("340,0 PA");
- medidas (ML, L, G, KG, M, CM) nunca vêm da descrição ("CAP 160 ML" é
  capacidade);
- sem evidência, nada é inventado: o relatório lista os itens em
  "Unidades a conferir".

### Editais de referência

Alguns dos layouts que guiaram a extração (a regressão de cada versão roda
hoje em 29 editais):

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
| Ubiratã (PE 77/2026) | células desenhadas, descrição atravessando páginas | 232/232 | 0 divergências |
| Missal (PE 59/2026) | células, "QUANT. UND" mesclado no cabeçalho | 105/105 | 0 divergências |
| Balneário Gaivota (PE 3/2026) | células, tabela repetida 3 vezes | 292/292 | soma = valor declarado |
| Porto Amazonas (PE 34/2026) | quatro tabelas de itens no mesmo edital | 365/365 | soma = valor declarado |
| Londrina (PE 131/2026) | relatório de sistema, texto fora de ordem | 23/23 lotes | 0 divergências |

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
Divergências são marcadas como **REVISAR** na coluna *Confere* da planilha.

O relatório traz o **gate de confiabilidade da extração**:

- **CONFIAVEL** — sequência 1..N completa **e** ≥98% das linhas
  consistentes **e** soma dos itens não abaixo de 97% do valor estimado
  declarado (quando o edital declara um);
- **REVISAR** — sequência incompleta, consistência baixa, poucos itens
  (< 3) ou soma abaixo do valor declarado (itens podem ter ficado para trás).

O valor declarado só entra como teste de **confiança**; o número oficial é
sempre a soma dos itens extraídos.

O relatório também lista os itens com unidade vazia ou fora da lista
("Unidades a conferir").

---

## Espelho de critérios (PDF)

Gerado em toda análise, pronto para imprimir ou arquivar: logo da HospMedic,
informações gerais, condições comerciais (validade mínima dos produtos,
prazo de pagamento, prazo de entrega, vigência da ARP — cada uma com o
trecho do edital), pontos a conferir (divergências com o nome do arquivo),
veredito e critérios por categoria com a evidência.

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

## Regressão antes de cada versão

Toda mudança na extração é rodada no corpus de editais reais (29 na v24) e
comparada com a versão anterior: quantidade, unitário, total, número de
itens, descrições e unidades. Diferenças são conferidas item a item no PDF
antes de empacotar; o resultado vai no changelog da versão.

---

## Limitações conhecidas e próximos passos

- **PDF escaneado (imagem)**: sem OCR integrado, a tabela não é lida
  (ex.: Pinhalão PE 62/2026). PDF com fonte ilegível recebe ILEGÍVEL.
- **Tabelas sem bordas**: seguem a leitura por âncoras, que ainda pode
  atribuir texto ao item vizinho em layouts atípicos; a whitelist cobre a
  unidade, a coluna *Confere* e a revisão humana cobrem o resto.
- **Cabeçalhos não reconhecidos pela leitura por células** (ex.: CIGAMERIOS,
  Campo do Tenente): seguem a leitura por âncoras.
- **Condições comerciais e critérios**: busca por padrões de texto; redações
  atípicas podem não ser reconhecidas (o campo sai "não identificado", nunca
  um chute).
- **Editais em dois arquivos**: cada PDF é processado individualmente.

Fora do MVP (visão de longo prazo do documento mestre): integração com o
catálogo da HospMedic, banco de dados estruturado, APIs, dashboards e apoio
à decisão.

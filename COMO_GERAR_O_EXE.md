# HBI.exe — como gerar, distribuir e usar

O HBI.exe é o mesmo HBI do navegador, rodando no próprio computador:
velocidade total da máquina (segundos, não minutos), funciona sem internet,
os editais não saem da empresa e o histórico fica guardado de verdade.

## Gerar o .exe (escolha um jeito)

**A) Pelo GitHub, sem instalar nada (recomendado)**
1. Envie esta versão para o repositório do HBI no GitHub.
2. Aba **Actions** > **Gerar HBI.exe** > **Run workflow**.
3. Em ~5 minutos, baixe **HBI-windows** no fim da execução.
   O GitHub roda os testes, compila e ainda abre o .exe para conferir que ele
   responde antes de entregar.

**B) No seu Windows**
1. Instale o Python 3.12 (python.org), marcando *"Add python.exe to PATH"*.
2. Dê dois cliques em `gerar_exe.bat`.
3. Resultado: `dist\HBI\HBI.exe` e `dist\HBI-windows.zip`.

## Distribuir
Envie o `HBI-windows.zip`. Quem recebe descompacta numa pasta (por exemplo,
`Documentos\HBI`) e cria um atalho do `HBI.exe` na área de trabalho.
O .exe precisa ficar junto da pasta `_internal`: não mova o .exe sozinho.

## Usar
- Dois cliques no **HBI.exe**: abre uma janela preta e, em seguida, o
  navegador já na tela do HBI, sem login.
- **A janela preta é o HBI rodando: fechá-la encerra o programa.**
- Abrir o HBI.exe de novo com ele aberto só traz o navegador de volta.

## Avisos esperados na primeira vez
- **"O Windows protegeu o computador" (SmartScreen):** acontece com todo
  programa sem assinatura digital. Clique em *Mais informações* >
  *Executar assim mesmo*. Para eliminar o aviso, é preciso comprar um
  certificado de assinatura de código.
- **Antivírus:** alguns antivírus desconfiam de programas feitos com
  PyInstaller. Se bloquear, libere a pasta do HBI.

## Onde ficam os dados
`%LOCALAPPDATA%\HBI` (cole na barra do Explorer para abrir): histórico
(`hbi.db`), arquivos de cada análise (`resultados`) e logs.
Atualizar o HBI = substituir a pasta do programa; os dados continuam.
Desinstalar = apagar a pasta do programa e, se quiser, a de dados.

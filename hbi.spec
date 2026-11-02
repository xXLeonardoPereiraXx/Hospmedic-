# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller para o HBI.exe (gerar com:  pyinstaller --noconfirm hbi.spec)
#
# Gera uma PASTA dist/HBI com o HBI.exe dentro (modo "onedir"): abre bem mais
# rápido que um .exe único, que se descompacta inteiro a cada execução.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("webapp/templates", "webapp/templates"),
    ("webapp/static", "webapp/static"),
    ("data/Modelo_de_Planilha_de_Licitacao.xlsx", "data"),
]
datas += collect_data_files("pdfminer")    # tabelas de codificação de fontes dos PDFs
datas += collect_data_files("reportlab")   # métricas de fonte usadas no espelho em PDF

hidden = collect_submodules("hbi") + collect_submodules("webapp")

a = Analysis(
    ["hbi_desktop.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hidden,
    # nada disso é usado pelo HBI: fica de fora para o pacote ficar menor
    excludes=["pandas", "numpy", "matplotlib", "scipy", "tkinter", "IPython",
              "pytest", "gunicorn", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="HBI",
    console=True,          # a janela mostra que o HBI está aberto; fechá-la encerra
    icon="webapp/static/hbi.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="HBI")

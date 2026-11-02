"""HBI como aplicativo de computador (ponto de entrada do HBI.exe).

Ao abrir:

1. prepara a pasta de dados do usuário (``%LOCALAPPDATA%\\HBI`` no Windows),
   onde ficam o histórico, os arquivos de cada análise e os logs — fora da
   pasta do programa, para sobreviverem a uma atualização do HBI;
2. sobe o servidor do HBI **só neste computador** (127.0.0.1), invisível para
   a rede;
3. abre o navegador padrão já na tela do HBI, sem pedir login (o computador é
   de uma pessoa; a senha só faz sentido no servidor compartilhado).

A janela preta que fica aberta é o próprio HBI rodando: fechá-la encerra o
programa. Abrir o HBI.exe de novo com ele já aberto só reabre o navegador.
"""
from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

PORTA = 8765  # fixa: permite reconhecer um HBI já aberto e reaproveitá-lo


def _pasta_dados() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") \
        or str(Path.home() / ".local" / "share")
    pasta = Path(base) / "HBI"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _hbi_ja_aberto(porta: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/health", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def _porta_livre(preferida: int) -> int:
    for porta in (preferida, 0):  # 0 = o sistema escolhe uma livre
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", porta))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Nenhuma porta livre para o HBI.")


def _preparar_ambiente(dados: Path) -> None:
    os.environ.setdefault("HBI_MODO_DESKTOP", "1")
    os.environ.setdefault("HBI_DATA_DIR", str(dados / "resultados"))
    os.environ.setdefault("HBI_DB_PATH", str(dados / "hbi.db"))
    os.environ.setdefault("HBI_LOG_DIR", str(dados / "logs"))
    os.environ.setdefault("HBI_OUTPUT_DIR", str(dados / "saida"))
    # chave da sessão guardada em arquivo: a sessão continua válida entre
    # aberturas do programa, e cada instalação tem a sua
    arq_chave = dados / "chave_sessao.txt"
    if not arq_chave.exists():
        arq_chave.write_text(secrets.token_hex(32), encoding="utf-8")
    os.environ.setdefault("HBI_SECRET_KEY", arq_chave.read_text(encoding="utf-8").strip())


def main() -> None:
    dados = _pasta_dados()
    _preparar_ambiente(dados)

    if _hbi_ja_aberto(PORTA):
        webbrowser.open(f"http://127.0.0.1:{PORTA}")
        return

    porta = _porta_livre(PORTA)
    url = f"http://127.0.0.1:{porta}"

    # importado só agora: as variáveis de ambiente acima precisam valer
    # quando o app e o banco forem carregados
    from werkzeug.serving import make_server

    from webapp.app import app

    servidor = make_server("127.0.0.1", porta, app, threaded=True)
    print("=" * 62)
    print("  HBI - HospMedic Bid Intelligence")
    print(f"  Aberto no navegador em {url}")
    print(f"  Dados e histórico em {dados}")
    print("  Para encerrar o HBI, feche esta janela.")
    print("=" * 62, flush=True)
    if os.environ.get("HBI_SEM_NAVEGADOR") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    # no .exe a saída padrão pode não suportar acentos (console cp850)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    main()

"""Aplicação web (Flask) do HBI — HospMedic Bid Intelligence.

Expõe o pipeline de análise de editais por uma interface web com login:
    - autenticação simples por sessão (usuários no SQLite, senha com hash);
    - upload de um edital em PDF;
    - escolha do modo (só validação  ou  completo com planilha);
    - exibição do relatório e download da planilha (no modo completo).

Reaproveita integralmente o pacote ``hbi`` (pipeline, validação, extração).
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from flask import (  # noqa: I001
    jsonify,
    Flask, flash, redirect, render_template, request,
    send_file, session, url_for,
)
from werkzeug.utils import secure_filename

# Garante que o pacote hbi (um nível acima) seja importável.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hbi.services import pipeline, report  # noqa: E402
from webapp import database  # noqa: E402

app = Flask(__name__)
# Chave de sessão: em produção, defina HBI_SECRET_KEY no ambiente do Render.
app.secret_key = os.environ.get("HBI_SECRET_KEY", "troque-esta-chave-em-producao")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB por upload

# Pasta temporária para uploads e resultados (efêmera — ok para o free tier).
WORK_DIR = Path(tempfile.gettempdir()) / "hbi_web"
WORK_DIR.mkdir(parents=True, exist_ok=True)

database.init_db()


def login_obrigatorio(f):
    """Decorator que exige sessão autenticada."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        if database.verificar_credenciais(usuario, senha):
            session["usuario"] = usuario
            return redirect(url_for("index"))
        flash("Usuário ou senha inválidos.", "erro")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_obrigatorio
def index():
    historico = database.listar_analises(session["usuario"])
    return render_template("index.html", usuario=session["usuario"], historico=historico)


# ---------------------------------------------------------------------------
# Processamento em segundo plano
# ---------------------------------------------------------------------------
# A análise de um edital longo leva de dezenas de segundos a alguns minutos em
# instâncias pequenas. Fazer esse trabalho dentro da requisição HTTP esbarra no
# tempo limite do navegador e do proxy da hospedagem, que derruba a conexão e
# devolve erro mesmo com o processamento correndo bem.
#
# A requisição, então, apenas ENFILEIRA a tarefa e responde na hora; uma thread
# faz o trabalho e a página de progresso consulta o estado periodicamente. Um
# efeito colateral bem-vindo: o usuário vê que algo está acontecendo, em vez de
# uma aba parada.
#
# As tarefas vivem em memória do processo — por isso o serviço roda com UM
# worker e várias threads (ver render.yaml): com mais de um worker, a consulta
# de estado poderia cair num processo que não conhece a tarefa.
TAREFAS: dict[str, dict] = {}
TAREFAS_LOCK = threading.Lock()
RETENCAO_TAREFA = 60 * 30  # segundos


def _limpar_tarefas_antigas() -> None:
    agora = time.time()
    with TAREFAS_LOCK:
        velhas = [
            k for k, v in TAREFAS.items()
            if agora - v.get("criado_em", agora) > RETENCAO_TAREFA
        ]
        for k in velhas:
            TAREFAS.pop(k, None)


def _executar_analise(tarefa_id: str, pdf_path: Path, nome: str,
                      modo: str, usuario: str) -> None:
    """Roda o pipeline fora da requisição e guarda o resultado na tarefa."""
    def _passo(msg: str) -> None:
        with TAREFAS_LOCK:
            if tarefa_id in TAREFAS:
                TAREFAS[tarefa_id]["etapa"] = msg

    try:
        if modo == "completo":
            _passo("Lendo o PDF e validando critérios…")
            xlsx_path = WORK_DIR / f"{tarefa_id}_resultado.xlsx"
            edital = pipeline.processar_edital(pdf_path, xlsx_path)
            _passo("Montando o relatório…")
            resultado = {
                "relatorio": report.montar_relatorio(edital),
                "diag": edital.diagnostico_extracao(),
                "veredito": edital.validacao.veredito if edital.validacao else "—",
                "download_token": f"{tarefa_id}_resultado.xlsx",
            }
            database.registrar_analise(
                usuario, nome, "completo",
                edital.validacao.veredito if edital.validacao else None,
                len(edital.itens), edital.soma_itens,
            )
        else:
            _passo("Lendo o PDF e validando critérios…")
            edital = pipeline.validar_edital(pdf_path)
            resultado = {
                "relatorio": report.montar_relatorio_validacao(edital),
                "diag": None,
                "veredito": edital.validacao.veredito if edital.validacao else "—",
                "download_token": None,
            }
            database.registrar_analise(
                usuario, nome, "validacao",
                edital.validacao.veredito if edital.validacao else None, None, None,
            )
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="pronto", resultado=resultado)
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Falha ao processar edital")
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="erro", erro=str(exc))
    finally:
        try:
            pdf_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.route("/analisar", methods=["POST"])
@login_obrigatorio
def analisar():
    arquivo = request.files.get("edital")
    modo = request.form.get("modo", "validacao")

    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo PDF.", "erro")
        return redirect(url_for("index"))
    if not arquivo.filename.lower().endswith(".pdf"):
        flash("O arquivo precisa ser um PDF.", "erro")
        return redirect(url_for("index"))

    nome_seguro = secure_filename(arquivo.filename)
    tarefa_id = uuid.uuid4().hex[:12]
    pdf_path = WORK_DIR / f"{tarefa_id}_{nome_seguro}"
    arquivo.save(pdf_path)

    _limpar_tarefas_antigas()
    with TAREFAS_LOCK:
        TAREFAS[tarefa_id] = {
            "estado": "processando",
            "etapa": "Na fila…",
            "arquivo": nome_seguro,
            "modo": modo,
            "usuario": session["usuario"],
            "criado_em": time.time(),
        }

    threading.Thread(
        target=_executar_analise,
        args=(tarefa_id, pdf_path, nome_seguro, modo, session["usuario"]),
        daemon=True,
    ).start()

    return redirect(url_for("progresso", tarefa_id=tarefa_id))


@app.route("/progresso/<tarefa_id>")
@login_obrigatorio
def progresso(tarefa_id: str):
    """Página de espera: consulta o estado da tarefa periodicamente."""
    with TAREFAS_LOCK:
        t = TAREFAS.get(tarefa_id)
        dono = t and t.get("usuario") == session["usuario"]
    if not dono:
        flash("Análise não encontrada. Envie o edital novamente.", "erro")
        return redirect(url_for("index"))
    return render_template(
        "progresso.html", usuario=session["usuario"],
        tarefa_id=tarefa_id, arquivo=t["arquivo"],
    )


@app.route("/estado/<tarefa_id>")
@login_obrigatorio
def estado(tarefa_id: str):
    """Estado da tarefa em JSON, consultado pela página de progresso."""
    with TAREFAS_LOCK:
        t = TAREFAS.get(tarefa_id)
        if not t or t.get("usuario") != session["usuario"]:
            return jsonify({"estado": "desconhecido"}), 404
        return jsonify({
            "estado": t["estado"],
            "etapa": t.get("etapa", ""),
            "erro": t.get("erro"),
        })


@app.route("/resultado/<tarefa_id>")
@login_obrigatorio
def resultado(tarefa_id: str):
    with TAREFAS_LOCK:
        t = TAREFAS.get(tarefa_id)
        if not t or t.get("usuario") != session["usuario"]:
            flash("Análise não encontrada. Envie o edital novamente.", "erro")
            return redirect(url_for("index"))
        if t["estado"] == "erro":
            flash(f"Erro ao processar o edital: {t.get('erro')}", "erro")
            return redirect(url_for("index"))
        if t["estado"] != "pronto":
            return redirect(url_for("progresso", tarefa_id=tarefa_id))
        r = t["resultado"]
        arquivo, modo = t["arquivo"], t["modo"]

    return render_template(
        "resultado.html",
        usuario=session["usuario"], arquivo=arquivo, modo=modo,
        relatorio=r["relatorio"], diag=r["diag"],
        veredito=r["veredito"], download_token=r["download_token"],
    )


@app.route("/download/<token>")
@login_obrigatorio
def download(token: str):
    caminho = WORK_DIR / secure_filename(token)
    if not caminho.exists():
        flash("Arquivo expirado ou não encontrado. Rode a análise novamente.", "erro")
        return redirect(url_for("index"))
    return send_file(caminho, as_attachment=True, download_name="planilha_preenchida.xlsx")


@app.route("/health")
def health():
    """Endpoint simples para checagem de disponibilidade."""
    return {"status": "ok"}


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta, debug=True)

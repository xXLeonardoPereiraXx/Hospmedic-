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
import uuid
from functools import wraps
from pathlib import Path

from flask import (
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
    token = uuid.uuid4().hex[:8]
    pdf_path = WORK_DIR / f"{token}_{nome_seguro}"
    arquivo.save(pdf_path)

    try:
        if modo == "completo":
            xlsx_path = WORK_DIR / f"{token}_resultado.xlsx"
            edital = pipeline.processar_edital(pdf_path, xlsx_path)
            texto = report.montar_relatorio(edital)
            diag = edital.diagnostico_extracao()
            database.registrar_analise(
                session["usuario"], nome_seguro, "completo",
                edital.validacao.veredito if edital.validacao else None,
                len(edital.itens), edital.soma_itens,
            )
            return render_template(
                "resultado.html",
                usuario=session["usuario"],
                arquivo=nome_seguro,
                modo=modo,
                relatorio=texto,
                diag=diag,
                veredito=edital.validacao.veredito if edital.validacao else "—",
                download_token=f"{token}_resultado.xlsx",
            )
        else:
            edital = pipeline.validar_edital(pdf_path)
            texto = report.montar_relatorio_validacao(edital)
            database.registrar_analise(
                session["usuario"], nome_seguro, "validacao",
                edital.validacao.veredito if edital.validacao else None,
                None, None,
            )
            return render_template(
                "resultado.html",
                usuario=session["usuario"],
                arquivo=nome_seguro,
                modo=modo,
                relatorio=texto,
                diag=None,
                veredito=edital.validacao.veredito if edital.validacao else "—",
                download_token=None,
            )
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Falha ao processar edital")
        flash(f"Erro ao processar o edital: {exc}", "erro")
        return redirect(url_for("index"))
    finally:
        # Remove o PDF de entrada; a planilha fica para download.
        try:
            pdf_path.unlink(missing_ok=True)
        except OSError:
            pass


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

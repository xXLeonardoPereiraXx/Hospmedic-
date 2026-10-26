"""Aplicação web (Flask) do HBI — HospMedic Bid Intelligence.

Expõe o pipeline de análise de editais por uma interface web com login:
    - autenticação simples por sessão (usuários no SQLite, senha com hash);
    - upload de um edital em PDF;
    - escolha do modo (só validação  ou  completo com planilha);
    - exibição do relatório e download da planilha (no modo completo).

Reaproveita integralmente o pacote ``hbi`` (pipeline, validação, extração).
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
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
from hbi.services.espelho_pdf import gerar_pdf_espelho  # noqa: E402
from hbi.utils.text import float_para_brl  # noqa: E402
from hbi.utils import cancelamento  # noqa: E402
from webapp import database  # noqa: E402

app = Flask(__name__)
# Chave de sessão: em produção, defina HBI_SECRET_KEY no ambiente do Render.
app.secret_key = os.environ.get("HBI_SECRET_KEY", "troque-esta-chave-em-producao")
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024  # 150 MB: comporta um .zip de editais

# Pasta temporária para uploads e resultados (efêmera — ok para o free tier).
WORK_DIR = Path(tempfile.gettempdir()) / "hbi_web"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Arquivos de cada análise (planilha, espelho em PDF, relatório), guardados
# para o histórico poder reabri-los. HBI_DATA_DIR permite apontar para um
# disco persistente; no plano gratuito do Render o disco é apagado a cada
# reinício, então o histórico só dura até lá.
RESULTADOS_DIR = Path(os.environ.get(
    "HBI_DATA_DIR", Path(__file__).resolve().parent.parent / "data" / "resultados"))
RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
MAX_ARQUIVOS_LOTE = 30

# tipo -> (nome no disco, mimetype)
ARQUIVOS = {
    "planilha": ("planilha.xlsx",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "espelho": ("espelho.pdf", "application/pdf"),
    "relatorio": ("relatorio.txt", "text/plain; charset=utf-8"),
    "lote": ("lote.zip", "application/zip"),
}

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



def _como_dict(obj) -> dict | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


def _processar_um(pdf_path: Path, nome: str, modo: str, pasta: Path, passo=None) -> dict:
    """Analisa um edital e grava planilha, espelho em PDF e relatório na pasta."""
    pasta.mkdir(parents=True, exist_ok=True)
    if modo == "completo":
        edital = pipeline.processar_edital(pdf_path, pasta / "planilha.xlsx", nome_original=nome)
        relatorio = report.montar_relatorio(edital)
        diag = _como_dict(edital.diagnostico_extracao())
    else:
        edital = pipeline.validar_edital(pdf_path, nome_original=nome)
        relatorio = report.montar_relatorio_validacao(edital)
        diag = None
    if passo:
        passo("Gerando o espelho em PDF…")
    gerar_pdf_espelho(edital, pasta / "espelho.pdf", nome)
    (pasta / "relatorio.txt").write_text(relatorio, encoding="utf-8")
    resumo = {
        "arquivo": nome, "modo": modo,
        "veredito": edital.validacao.veredito if edital.validacao else "revisar",
        "itens": len(edital.itens) if modo == "completo" else None,
        "soma": edital.soma_itens if modo == "completo" else None,
        "diag": diag,
    }
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, default=str),
                                       encoding="utf-8")
    return {**resumo, "relatorio": relatorio}


def _arquivos_disponiveis(pasta: Path | None) -> dict:
    if not pasta:
        return {}
    return {tipo: (pasta / nome).exists() for tipo, (nome, _) in ARQUIVOS.items()}


def _nome_no_zip(info: zipfile.ZipInfo) -> str:
    """Nome do arquivo dentro do zip, com acentos corrigidos.

    Zips gerados no Windows costumam gravar o nome em cp437 sem marcar UTF-8;
    sem a correção, "Iguaraçu" chegaria como "Iguara├ºu" e o espelho perderia
    a conferência pelo nome do arquivo.
    """
    nome = Path(info.filename).name
    if not info.flag_bits & 0x800:
        try:
            nome = nome.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return nome


def _extrair_pdfs_do_zip(zpath: Path, destino: Path, inicio: int = 0) -> list[tuple[Path, str]]:
    """PDFs de um .zip, cada um com o nome original.

    Só o nome-base de cada entrada é usado (pastas internas descartadas), o
    que impede que um zip malicioso grave fora da pasta de trabalho.
    """
    saida: list[tuple[Path, str]] = []
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            nome = _nome_no_zip(info)
            if (info.is_dir() or not nome.lower().endswith(".pdf")
                    or info.filename.startswith("__MACOSX") or nome.startswith(".")):
                continue
            alvo = destino / f"{inicio + len(saida):02d}_{secure_filename(nome) or 'edital.pdf'}"
            with z.open(info) as src, open(alvo, "wb") as dst:
                shutil.copyfileobj(src, dst)
            saida.append((alvo, nome))
    return saida


def _montar_zip_lote(pasta_lote: Path, resultados: list[dict]) -> None:
    """Zip do lote: planilha, espelho e relatório de cada edital, pelo nome dele."""
    usados: set[str] = set()
    linhas = ["HBI - resumo do lote", ""]
    with zipfile.ZipFile(pasta_lote / "lote.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for r in resultados:
            base = Path(r["arquivo"]).stem
            nome, n = base, 2
            while nome in usados:  # dois editais com o mesmo nome
                nome, n = f"{base} ({n})", n + 1
            usados.add(nome)
            if not r.get("ok"):
                linhas.append(f"{r['arquivo']}: ERRO - {r.get('erro')}")
                continue
            pasta = Path(r["pasta"])
            for disco, rotulo in (("planilha.xlsx", f"{nome}.xlsx"),
                                  ("espelho.pdf", f"{nome} - espelho.pdf"),
                                  ("relatorio.txt", f"{nome} - relatorio.txt")):
                if (pasta / disco).exists():
                    z.write(pasta / disco, rotulo)
            extra = ""
            if r.get("itens") is not None:
                extra = f" | {r['itens']} itens | R$ {float_para_brl(r['soma'] or 0)}"
            linhas.append(f"{r['arquivo']}: {r['veredito'].upper()}{extra}")
        z.writestr("resumo.txt", "\n".join(linhas))


def _executar_lote(tarefa_id: str, arquivos: list[tuple[Path, str]],
                   modo: str, usuario: str) -> None:
    """Processa vários editais em sequência; um erro não interrompe os demais."""
    def _passo(msg: str) -> None:
        with TAREFAS_LOCK:
            if tarefa_id in TAREFAS:
                TAREFAS[tarefa_id]["etapa"] = msg

    tid = threading.get_ident()
    with TAREFAS_LOCK:
        if tarefa_id in TAREFAS:
            TAREFAS[tarefa_id]["thread_id"] = tid
    pasta_lote = RESULTADOS_DIR / tarefa_id
    resultados: list[dict] = []
    try:
        total = len(arquivos)
        for k, (pdf_path, nome) in enumerate(arquivos, start=1):
            cancelamento.checar()
            prefixo = f"Edital {k} de {total} ({nome})"
            _passo(f"{prefixo}: lendo o PDF…")
            pasta = pasta_lote / f"{k:02d}"
            try:
                r = _processar_um(pdf_path, nome, modo, pasta,
                                  lambda m, p=prefixo: _passo(f"{p}: {m}"))
                aid = database.registrar_analise(
                    usuario, nome, modo, r["veredito"], r["itens"], r["soma"], pasta=str(pasta))
                resultados.append({**{k2: v for k2, v in r.items() if k2 != "relatorio"},
                                   "ok": True, "pasta": str(pasta), "analise_id": aid})
            except cancelamento.AnaliseCancelada:
                raise
            except Exception as exc:  # noqa: BLE001 — um edital ruim não derruba o lote
                app.logger.exception("Falha no edital %s do lote", nome)
                resultados.append({"arquivo": nome, "ok": False, "erro": str(exc)})
        _passo("Montando o arquivo .zip com os resultados…")
        _montar_zip_lote(pasta_lote, resultados)
        (pasta_lote / "resumo.json").write_text(
            json.dumps({"modo": modo, "lote": resultados}, ensure_ascii=False, default=str),
            encoding="utf-8")
        lote_id = database.registrar_analise(
            usuario, f"Lote com {total} editais", "lote", None, None, None, pasta=str(pasta_lote))
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="pronto",
                                      resultado={"lote": resultados, "analise_id": lote_id})
    except cancelamento.AnaliseCancelada:
        # os editais já concluídos ficam no histórico, cada um com seus arquivos
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="cancelado")
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Falha no lote")
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="erro", erro=str(exc))
    finally:
        cancelamento.limpar(tid)


def _executar_analise(tarefa_id: str, pdf_path: Path, nome: str,
                      modo: str, usuario: str) -> None:
    """Roda o pipeline fora da requisição e guarda o resultado na tarefa."""
    def _passo(msg: str) -> None:
        with TAREFAS_LOCK:
            if tarefa_id in TAREFAS:
                TAREFAS[tarefa_id]["etapa"] = msg

    # Guarda a thread desta análise para que o pedido de cancelamento saiba
    # qual trabalho interromper.
    tid = threading.get_ident()
    with TAREFAS_LOCK:
        if tarefa_id in TAREFAS:
            TAREFAS[tarefa_id]["thread_id"] = tid

    try:
        _passo("Lendo o PDF e validando critérios…")
        pasta = RESULTADOS_DIR / tarefa_id
        r = _processar_um(pdf_path, nome, modo, pasta, _passo)
        aid = database.registrar_analise(
            usuario, nome, modo, r["veredito"], r["itens"], r["soma"], pasta=str(pasta))
        resultado = {"relatorio": r["relatorio"], "diag": r["diag"],
                     "veredito": r["veredito"], "analise_id": aid}
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="pronto", resultado=resultado)
    except cancelamento.AnaliseCancelada:
        app.logger.info("Análise %s cancelada pelo usuário.", tarefa_id)
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="cancelado")
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Falha ao processar edital")
        with TAREFAS_LOCK:
            TAREFAS[tarefa_id].update(estado="erro", erro=str(exc))
    finally:
        cancelamento.limpar(tid)
        try:
            pdf_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.route("/analisar", methods=["POST"])
@login_obrigatorio
def analisar():
    enviados = [a for a in request.files.getlist("edital") if a and a.filename]
    modo = request.form.get("modo", "validacao")
    if not enviados:
        flash("Selecione um PDF, vários PDFs ou um arquivo .zip.", "erro")
        return redirect(url_for("index"))

    tarefa_id = uuid.uuid4().hex[:12]
    pasta_up = WORK_DIR / tarefa_id
    pasta_up.mkdir(parents=True, exist_ok=True)
    pdfs: list[tuple[Path, str]] = []
    for a in enviados:
        nome = Path(a.filename).name  # nome original: usado no espelho e no zip
        if nome.lower().endswith(".pdf"):
            alvo = pasta_up / f"{len(pdfs):02d}_{secure_filename(nome) or 'edital.pdf'}"
            a.save(alvo)
            pdfs.append((alvo, nome))
        elif nome.lower().endswith(".zip"):
            zpath = pasta_up / f"envio_{uuid.uuid4().hex[:6]}.zip"
            a.save(zpath)
            try:
                pdfs += _extrair_pdfs_do_zip(zpath, pasta_up, inicio=len(pdfs))
            except zipfile.BadZipFile:
                flash(f"O arquivo {nome} não é um .zip válido.", "erro")
                return redirect(url_for("index"))
        else:
            flash(f"Ignorado (não é PDF nem .zip): {nome}", "aviso")

    if not pdfs:
        flash("Nenhum PDF encontrado nos arquivos enviados.", "erro")
        return redirect(url_for("index"))
    if len(pdfs) > MAX_ARQUIVOS_LOTE:
        flash(f"Envie no máximo {MAX_ARQUIVOS_LOTE} editais por vez "
              f"(recebidos: {len(pdfs)}).", "erro")
        return redirect(url_for("index"))

    lote = len(pdfs) > 1
    _limpar_tarefas_antigas()
    with TAREFAS_LOCK:
        TAREFAS[tarefa_id] = {
            "estado": "processando",
            "etapa": "Na fila…",
            "arquivo": f"{len(pdfs)} editais" if lote else pdfs[0][1],
            "modo": modo,
            "lote": lote,
            "usuario": session["usuario"],
            "criado_em": time.time(),
        }
    if lote:
        alvo, args = _executar_lote, (tarefa_id, pdfs, modo, session["usuario"])
    else:
        alvo, args = _executar_analise, (tarefa_id, pdfs[0][0], pdfs[0][1], modo,
                                         session["usuario"])
    threading.Thread(target=alvo, args=args, daemon=True).start()
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


@app.route("/cancelar/<tarefa_id>", methods=["POST"])
@login_obrigatorio
def cancelar(tarefa_id: str):
    """Interrompe uma análise em andamento.

    O trabalho não é morto à força: a thread verifica o pedido na troca de
    página do PDF e encerra sozinha, o que evita deixar arquivo ou estrutura
    pela metade. Na prática a interrupção acontece em menos de uma página.
    """
    with TAREFAS_LOCK:
        t = TAREFAS.get(tarefa_id)
        if not t or t.get("usuario") != session["usuario"]:
            return jsonify({"ok": False}), 404
        tid = t.get("thread_id")
        if t["estado"] == "processando":
            t["etapa"] = "Cancelando…"
    if tid:
        cancelamento.marcar_cancelamento(tid)
    return jsonify({"ok": True})


@app.route("/resultado/<tarefa_id>")
@login_obrigatorio
def resultado(tarefa_id: str):
    with TAREFAS_LOCK:
        t = TAREFAS.get(tarefa_id)
        if not t or t.get("usuario") != session["usuario"]:
            flash("Análise não encontrada. Envie o edital novamente.", "erro")
            return redirect(url_for("index"))
        if t["estado"] == "cancelado":
            flash("Análise cancelada.", "aviso")
            return redirect(url_for("index"))
        if t["estado"] == "erro":
            flash(f"Erro ao processar o edital: {t.get('erro')}", "erro")
            return redirect(url_for("index"))
        if t["estado"] != "pronto":
            return redirect(url_for("progresso", tarefa_id=tarefa_id))
        r = t["resultado"]
        arquivo, modo, lote = t["arquivo"], t["modo"], t.get("lote")

    if lote:
        return render_template("lote.html", usuario=session["usuario"], modo=modo,
                               itens=r["lote"], analise_id=r["analise_id"])
    return render_template(
        "resultado.html",
        usuario=session["usuario"], arquivo=arquivo, modo=modo,
        relatorio=r["relatorio"], diag=r["diag"], veredito=r["veredito"],
        analise_id=r["analise_id"],
        arquivos=_arquivos_disponiveis(RESULTADOS_DIR / tarefa_id),
    )


@app.route("/historico/<int:analise_id>")
@login_obrigatorio
def historico(analise_id: int):
    """Reabre uma análise anterior a partir dos arquivos guardados."""
    a = database.obter_analise(analise_id, session["usuario"])
    pasta = Path(a["pasta"]) if a and a["pasta"] else None
    if not pasta or not pasta.exists():
        flash("Os arquivos dessa análise não estão mais disponíveis no servidor "
              "(análises antigas ou apagadas em um reinício). Rode-a novamente.", "erro")
        return redirect(url_for("index"))
    resumo = {}
    if (pasta / "resumo.json").exists():
        resumo = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
    if a["modo"] == "lote":
        return render_template("lote.html", usuario=session["usuario"],
                               modo=resumo.get("modo"), itens=resumo.get("lote", []),
                               analise_id=analise_id, criado_em=a["criado_em"])
    relatorio = ""
    if (pasta / "relatorio.txt").exists():
        relatorio = (pasta / "relatorio.txt").read_text(encoding="utf-8")
    return render_template(
        "resultado.html",
        usuario=session["usuario"], arquivo=a["arquivo"], modo=a["modo"],
        relatorio=relatorio, diag=resumo.get("diag"), veredito=a["veredito"] or "revisar",
        analise_id=analise_id, arquivos=_arquivos_disponiveis(pasta),
        criado_em=a["criado_em"],
    )


@app.route("/arquivo/<int:analise_id>/<tipo>")
@login_obrigatorio
def arquivo(analise_id: int, tipo: str):
    """Baixa (ou abre, para imprimir) um arquivo de uma análise do usuário."""
    a = database.obter_analise(analise_id, session["usuario"])
    if tipo not in ARQUIVOS or not a or not a["pasta"]:
        flash("Arquivo não encontrado.", "erro")
        return redirect(url_for("index"))
    disco, mime = ARQUIVOS[tipo]
    caminho = Path(a["pasta"]) / disco
    if not caminho.exists():
        flash("Esse arquivo não está mais disponível. Rode a análise novamente.", "erro")
        return redirect(url_for("index"))
    base = Path(a["arquivo"]).stem
    nomes = {"planilha": f"{base}.xlsx", "espelho": f"{base} - espelho.pdf",
             "relatorio": f"{base} - relatorio.txt", "lote": f"HBI - {base}.zip"}
    # o espelho pode abrir no navegador (para imprimir) em vez de baixar
    abrir = tipo == "espelho" and request.args.get("abrir") == "1"
    return send_file(caminho, mimetype=mime, as_attachment=not abrir,
                     download_name=nomes[tipo])


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

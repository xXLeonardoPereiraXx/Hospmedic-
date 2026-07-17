"""Camada de banco de dados (SQLite) do webapp HBI.

Guarda usuários (login + senha com hash) e um histórico simples de análises.

Estratégia de persistência resiliente ao Render (free tier):
    O disco do plano gratuito do Render NÃO é persistente entre reinícios,
    então os usuários não podem depender apenas de escrita em disco. Para
    resolver isso, os usuários "oficiais" são definidos por uma variável de
    ambiente (``HBI_USERS``) e re-semeados (seed) a cada inicialização. Assim,
    mesmo que o arquivo SQLite seja recriado do zero, os logins da equipe
    voltam automaticamente — eles nunca se perdem.

Formato da variável de ambiente ``HBI_USERS`` (usuarios separados por ';',
login e senha separados por ':'):
    usuario1:senha1;usuario2:senha2

Se a variável não existir (ambiente local de teste), um usuário padrão é
criado: admin / hbi123  (troque em produção!).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

# O arquivo do banco fica ao lado deste módulo por padrão; em produção pode
# ser sobrescrito por variável de ambiente.
DB_PATH = Path(os.environ.get("HBI_DB_PATH", Path(__file__).parent / "hbi.db"))


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão SQLite com row factory por nome de coluna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Cria as tabelas se não existirem e semeia os usuários da configuração."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                login        TEXT UNIQUE NOT NULL,
                senha_hash   TEXT NOT NULL,
                criado_em    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analises (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario      TEXT NOT NULL,
                arquivo      TEXT NOT NULL,
                modo         TEXT NOT NULL,
                veredito     TEXT,
                itens        INTEGER,
                soma         REAL,
                criado_em    TEXT NOT NULL
            );
            """
        )
        conn.commit()
        _seed_usuarios(conn)
    finally:
        conn.close()


def _seed_usuarios(conn: sqlite3.Connection) -> None:
    """Garante que os usuários definidos na configuração existam no banco.

    Isso torna os logins resilientes: mesmo que o banco seja recriado, os
    usuários da equipe são restaurados a partir da variável de ambiente.
    """
    especificacao = os.environ.get("HBI_USERS", "admin:hbi123")
    for par in especificacao.split(";"):
        par = par.strip()
        if not par or ":" not in par:
            continue
        login, senha = par.split(":", 1)
        login, senha = login.strip(), senha.strip()
        if not login or not senha:
            continue
        existe = conn.execute(
            "SELECT 1 FROM usuarios WHERE login = ?", (login,)
        ).fetchone()
        if existe is None:
            conn.execute(
                "INSERT INTO usuarios (login, senha_hash, criado_em) VALUES (?, ?, ?)",
                (login, generate_password_hash(senha), datetime.utcnow().isoformat()),
            )
    conn.commit()


def verificar_credenciais(login: str, senha: str) -> bool:
    """Retorna True se o par login/senha for válido."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT senha_hash FROM usuarios WHERE login = ?", (login,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    return check_password_hash(row["senha_hash"], senha)


def registrar_analise(
    usuario: str,
    arquivo: str,
    modo: str,
    veredito: str | None,
    itens: int | None,
    soma: float | None,
) -> None:
    """Grava uma linha no histórico de análises."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO analises (usuario, arquivo, modo, veredito, itens, soma, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (usuario, arquivo, modo, veredito, itens, soma, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def listar_analises(usuario: str, limite: int = 20) -> list[sqlite3.Row]:
    """Retorna as últimas análises de um usuário (mais recentes primeiro)."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT arquivo, modo, veredito, itens, soma, criado_em
            FROM analises WHERE usuario = ?
            ORDER BY id DESC LIMIT ?
            """,
            (usuario, limite),
        ).fetchall()
    finally:
        conn.close()

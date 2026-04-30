"""
Camada de acesso a dados.

Em produção (TURSO_URL + TURSO_TOKEN definidos): usa Turso via libsql-client (HTTP).
Em desenvolvimento: usa SQLite local via sqlite3 padrão.

A API pública é idêntica nos dois casos — o resto do código não sabe a diferença.
"""

import os
import logging
import sqlite3

logger = logging.getLogger(__name__)

TURSO_URL   = os.environ.get("TURSO_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "").strip()
DB_PATH     = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imoveis.db")
_USE_TURSO  = bool(TURSO_URL and TURSO_TOKEN)


# ── Abstração de conexão ──────────────────────────────────────────────────────

class _TursoConn:
    """
    Wrapper sobre libsql_client que expõe a mesma interface do sqlite3.Connection.
    Executa queries síncronas via asyncio.run() — simples e sem dependências extras.
    """

    def __init__(self):
        import libsql_client
        import asyncio
        self._client = libsql_client.create_client_sync(
            url=TURSO_URL, auth_token=TURSO_TOKEN
        )

    def execute(self, sql: str, params=()):
        rs = self._client.execute(sql, list(params) if params else [])
        return _TursoCursor(rs)

    def executemany(self, sql: str, seq):
        for params in seq:
            self._client.execute(sql, list(params))
        return _TursoCursor(None)

    def commit(self):
        pass  # libsql-client auto-commita cada statement

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _TursoCursor:
    """Cursor compatível com sqlite3 para resultados do Turso."""

    def __init__(self, rs):
        self._rs = rs
        self._rows = list(rs.rows) if rs and rs.rows else []
        self._idx  = 0
        self.description = (
            [(col.name, None, None, None, None, None, None) for col in rs.columns]
            if rs and rs.columns else []
        )
        self.lastrowid = rs.last_insert_rowid if rs else None

    def fetchone(self):
        if not self._rows:
            return None
        row = self._rows[0]
        if self.description:
            return dict(zip([d[0] for d in self.description], row))
        return row

    def fetchall(self):
        if not self._rows or not self.description:
            return []
        cols = [d[0] for d in self.description]
        return [dict(zip(cols, r)) for r in self._rows]


def get_connection():
    if _USE_TURSO:
        return _TursoConn()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _as_dict(row) -> dict:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return dict(row)
    return dict(row)


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS imoveis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        origem TEXT,
        titulo TEXT,
        preco REAL,
        area_m2 REAL,
        quartos INTEGER,
        banheiros INTEGER,
        vagas INTEGER,
        endereco TEXT,
        bairro TEXT,
        cidade TEXT,
        lat REAL,
        lng REAL,
        dist_supermercado_km REAL,
        dist_centro_carro_km REAL,
        dist_centro_onibus_km REAL,
        tempo_centro_carro_min REAL,
        tempo_centro_onibus_min REAL,
        imagem_url TEXT,
        imagens_json TEXT,
        linhas_onibus TEXT,
        score REAL,
        status TEXT DEFAULT 'pendente',
        disponivel INTEGER DEFAULT 1,
        checado_em TIMESTAMP,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS pesos (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        peso_preco REAL DEFAULT 30,
        peso_area REAL DEFAULT 20,
        peso_quartos REAL DEFAULT 15,
        peso_banheiros REAL DEFAULT 10,
        peso_dist_supermercado REAL DEFAULT 10,
        peso_dist_centro_carro REAL DEFAULT 7,
        peso_dist_centro_onibus REAL DEFAULT 8
    )""",
    "INSERT OR IGNORE INTO pesos (id) VALUES (1)",
]

_MIGRATIONS = [
    "ALTER TABLE imoveis ADD COLUMN imagens_json TEXT",
    "ALTER TABLE imoveis ADD COLUMN linhas_onibus TEXT",
    "ALTER TABLE imoveis ADD COLUMN disponivel INTEGER DEFAULT 1",
    "ALTER TABLE imoveis ADD COLUMN checado_em TIMESTAMP",
    "ALTER TABLE imoveis ADD COLUMN origem TEXT",
]


def init_db():
    # Schema principal
    for stmt in _SCHEMA:
        with get_connection() as conn:
            conn.execute(stmt)

    # Migrações opcionais
    for stmt in _MIGRATIONS:
        try:
            with get_connection() as conn:
                conn.execute(stmt)
        except Exception:
            pass  # coluna já existe

    # Preenche origem para registros antigos
    with get_connection() as conn:
        conn.execute("""
            UPDATE imoveis SET origem = CASE
                WHEN url LIKE '%zapimoveis%'   THEN 'ZAP Imóveis'
                WHEN url LIKE '%vivareal%'     THEN 'VivaReal'
                WHEN url LIKE '%quintoandar%'  THEN 'QuintoAndar'
                WHEN url LIKE '%olx%'          THEN 'OLX'
                ELSE 'Outro'
            END
            WHERE origem IS NULL
        """)

    # Recupera imóveis presos em 'processando'
    with get_connection() as conn:
        conn.execute("""
            UPDATE imoveis SET status = 'pendente'
            WHERE status = 'processando'
              AND (atualizado_em IS NULL
                   OR atualizado_em < datetime('now', '-5 minutes'))
        """)

    logger.info("DB inicializado (%s)", "Turso" if _USE_TURSO else f"SQLite: {DB_PATH}")


# ── Queries ───────────────────────────────────────────────────────────────────

def get_all_imoveis() -> list:
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM imoveis ORDER BY score DESC NULLS LAST, criado_em DESC"
        )
        return cur.fetchall()


def get_imovel(imovel_id: int) -> dict:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM imoveis WHERE id = ?", (imovel_id,))
        return cur.fetchone()


def get_imovel_by_url(url: str) -> dict:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM imoveis WHERE url = ?", (url,))
        return cur.fetchone()


def upsert_imovel(data: dict) -> int:
    """INSERT se URL nova, UPDATE se já existe. Retorna o id."""
    # INSERT OR IGNORE garante que a linha existe
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO imoveis (url, status) VALUES (?, ?)",
            (data["url"], data.get("status", "processando")),
        )

    # Busca o id
    with get_connection() as conn:
        cur = conn.execute("SELECT id FROM imoveis WHERE url = ?", (data["url"],))
        row = cur.fetchone()
        imovel_id = row["id"] if row else None

    # UPDATE com todos os campos
    with get_connection() as conn:
        conn.execute("""
            UPDATE imoveis SET
                origem = ?, titulo = ?, preco = ?, area_m2 = ?,
                quartos = ?, banheiros = ?, vagas = ?,
                endereco = ?, bairro = ?, cidade = ?,
                lat = ?, lng = ?,
                dist_supermercado_km = ?, dist_centro_carro_km = ?,
                dist_centro_onibus_km = ?, tempo_centro_carro_min = ?,
                tempo_centro_onibus_min = ?, imagem_url = ?,
                imagens_json = ?, linhas_onibus = ?,
                score = ?, status = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE url = ?
        """, (
            data.get("origem"),        data.get("titulo"),
            data.get("preco"),         data.get("area_m2"),
            data.get("quartos"),       data.get("banheiros"),
            data.get("vagas"),         data.get("endereco"),
            data.get("bairro"),        data.get("cidade"),
            data.get("lat"),           data.get("lng"),
            data.get("dist_supermercado_km"),   data.get("dist_centro_carro_km"),
            data.get("dist_centro_onibus_km"),  data.get("tempo_centro_carro_min"),
            data.get("tempo_centro_onibus_min"),data.get("imagem_url"),
            data.get("imagens_json"),  data.get("linhas_onibus"),
            data.get("score"),         data.get("status"),
            data["url"],
        ))

    return imovel_id


def delete_imovel(imovel_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM imoveis WHERE id = ?", (imovel_id,))


def get_pesos() -> dict:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM pesos WHERE id = 1")
        return cur.fetchone() or {}


def update_pesos(pesos: dict):
    with get_connection() as conn:
        conn.execute("""
            UPDATE pesos SET
                peso_preco = ?, peso_area = ?, peso_quartos = ?,
                peso_banheiros = ?, peso_dist_supermercado = ?,
                peso_dist_centro_carro = ?, peso_dist_centro_onibus = ?
            WHERE id = 1
        """, (
            pesos["peso_preco"],            pesos["peso_area"],
            pesos["peso_quartos"],          pesos["peso_banheiros"],
            pesos["peso_dist_supermercado"],pesos["peso_dist_centro_carro"],
            pesos["peso_dist_centro_onibus"],
        ))


def recalculate_all_scores():
    from app.ranking import calcular_score_todos
    calcular_score_todos()

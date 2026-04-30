"""
Camada de acesso a dados.

Produção  (TURSO_URL + TURSO_TOKEN definidos): Turso via API HTTP REST — sem libs extras.
Desenvolvimento (variáveis ausentes): SQLite local via sqlite3 padrão.
"""

import os
import sqlite3
import logging
import requests as _requests

logger = logging.getLogger(__name__)

TURSO_URL   = os.environ.get("TURSO_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "").strip()
DB_PATH     = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imoveis.db")
_USE_TURSO  = bool(TURSO_URL and TURSO_TOKEN)

# Converte URL libsql:// → https:// para a API HTTP
_TURSO_HTTP = TURSO_URL.replace("libsql://", "https://") if TURSO_URL else ""
_TURSO_ENDPOINT = f"{_TURSO_HTTP}/v2/pipeline"
_TURSO_HEADERS  = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json",
}


# ── Turso HTTP client ─────────────────────────────────────────────────────────

def _turso_execute(sql: str, params: list = None) -> dict:
    """Executa um statement no Turso via API HTTP. Retorna o resultado."""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {
                "sql": sql,
                "args": [_turso_val(p) for p in (params or [])],
            }},
            {"type": "close"},
        ]
    }
    resp = _requests.post(_TURSO_ENDPOINT, json=payload, headers=_TURSO_HEADERS, timeout=15)
    if not resp.ok:
        logger.error("Turso HTTP %s: %s\nSQL: %s\nParams: %s",
                     resp.status_code, resp.text[:500], sql[:200], params)
        resp.raise_for_status()
    data = resp.json()

    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(f"Turso error: {result['error']['message']}")

    return result["response"]["result"]


def _turso_val(v):
    """Converte valor Python para o formato de argumento do Turso."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        # Turso espera float como número JSON nativo, não string
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _turso_rows(result: dict) -> list:
    """Converte resultado do Turso para lista de dicts com tipos corretos."""
    cols = [c["name"] for c in result.get("cols", [])]
    rows = []
    for row in result.get("rows", []):
        record = {}
        for col, cell in zip(cols, row):
            t = cell.get("type", "null")
            v = cell.get("value")
            if t == "null" or v is None:
                record[col] = None
            elif t == "integer":
                record[col] = int(v)
            elif t == "float":
                record[col] = float(v)
            else:
                record[col] = v
        rows.append(record)
    return rows


def _turso_lastrowid(result: dict):
    return result.get("last_insert_rowid")


# ── Conexão unificada ─────────────────────────────────────────────────────────

class _Conn:
    """
    Abstração que expõe execute() / fetchone() / fetchall() / commit()
    tanto para SQLite local quanto para Turso HTTP.
    """

    def __init__(self):
        if _USE_TURSO:
            self._sqlite = None
        else:
            self._sqlite = sqlite3.connect(DB_PATH)
            self._sqlite.row_factory = sqlite3.Row
        self._last_result = None

    def execute(self, sql: str, params=()):
        if _USE_TURSO:
            self._last_result = _turso_execute(sql, list(params))
        else:
            self._cur = self._sqlite.execute(sql, params)
            self._last_result = None
        return self

    def executemany(self, sql: str, seq):
        for params in seq:
            self.execute(sql, params)
        return self

    def fetchone(self):
        if _USE_TURSO:
            rows = _turso_rows(self._last_result)
            return rows[0] if rows else None
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        if _USE_TURSO:
            return _turso_rows(self._last_result)
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        if _USE_TURSO:
            return _turso_lastrowid(self._last_result)
        return self._cur.lastrowid

    def commit(self):
        if self._sqlite:
            self._sqlite.commit()

    def close(self):
        if self._sqlite:
            self._sqlite.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._sqlite:
            self._sqlite.commit()
            self._sqlite.close()


def get_connection() -> _Conn:
    return _Conn()


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS imoveis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        origem TEXT, titulo TEXT, preco REAL, area_m2 REAL,
        quartos INTEGER, banheiros INTEGER, vagas INTEGER,
        endereco TEXT, bairro TEXT, cidade TEXT,
        lat REAL, lng REAL,
        dist_supermercado_km REAL, dist_centro_carro_km REAL,
        dist_centro_onibus_km REAL, tempo_centro_carro_min REAL,
        tempo_centro_onibus_min REAL, imagem_url TEXT,
        imagens_json TEXT, linhas_onibus TEXT, score REAL,
        status TEXT DEFAULT 'pendente', disponivel INTEGER DEFAULT 1,
        checado_em TIMESTAMP,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS pesos (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        peso_preco REAL DEFAULT 30, peso_area REAL DEFAULT 20,
        peso_quartos REAL DEFAULT 15, peso_banheiros REAL DEFAULT 10,
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
    for stmt in _SCHEMA:
        with get_connection() as conn:
            conn.execute(stmt)

    for stmt in _MIGRATIONS:
        try:
            with get_connection() as conn:
                conn.execute(stmt)
        except Exception:
            pass

    with get_connection() as conn:
        conn.execute("""
            UPDATE imoveis SET origem = CASE
                WHEN url LIKE '%zapimoveis%'  THEN 'ZAP Imóveis'
                WHEN url LIKE '%vivareal%'    THEN 'VivaReal'
                WHEN url LIKE '%quintoandar%' THEN 'QuintoAndar'
                WHEN url LIKE '%olx%'         THEN 'OLX'
                ELSE 'Outro'
            END WHERE origem IS NULL
        """)

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
        return conn.execute(
            "SELECT * FROM imoveis ORDER BY score DESC NULLS LAST, criado_em DESC"
        ).fetchall()


def get_imovel(imovel_id: int) -> dict:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM imoveis WHERE id = ?", (imovel_id,)
        ).fetchone()


def get_imovel_by_url(url: str) -> dict:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM imoveis WHERE url = ?", (url,)
        ).fetchone()


def upsert_imovel(data: dict) -> int:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO imoveis (url, status) VALUES (?, ?)",
            (data["url"], data.get("status", "processando")),
        )

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM imoveis WHERE url = ?", (data["url"],)
        ).fetchone()
        imovel_id = row["id"] if row else None

    with get_connection() as conn:
        conn.execute("""
            UPDATE imoveis SET
                origem=?, titulo=?, preco=?, area_m2=?,
                quartos=?, banheiros=?, vagas=?,
                endereco=?, bairro=?, cidade=?,
                lat=?, lng=?,
                dist_supermercado_km=?, dist_centro_carro_km=?,
                dist_centro_onibus_km=?, tempo_centro_carro_min=?,
                tempo_centro_onibus_min=?, imagem_url=?,
                imagens_json=?, linhas_onibus=?,
                score=?, status=?,
                atualizado_em=CURRENT_TIMESTAMP
            WHERE url=?
        """, (
            data.get("origem"),        data.get("titulo"),
            data.get("preco"),         data.get("area_m2"),
            data.get("quartos"),       data.get("banheiros"),
            data.get("vagas"),         data.get("endereco"),
            data.get("bairro"),        data.get("cidade"),
            data.get("lat"),           data.get("lng"),
            data.get("dist_supermercado_km"),    data.get("dist_centro_carro_km"),
            data.get("dist_centro_onibus_km"),   data.get("tempo_centro_carro_min"),
            data.get("tempo_centro_onibus_min"), data.get("imagem_url"),
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
        return conn.execute("SELECT * FROM pesos WHERE id = 1").fetchone() or {}


def update_pesos(pesos: dict):
    with get_connection() as conn:
        conn.execute("""
            UPDATE pesos SET
                peso_preco=?, peso_area=?, peso_quartos=?,
                peso_banheiros=?, peso_dist_supermercado=?,
                peso_dist_centro_carro=?, peso_dist_centro_onibus=?
            WHERE id = 1
        """, (
            pesos["peso_preco"],             pesos["peso_area"],
            pesos["peso_quartos"],           pesos["peso_banheiros"],
            pesos["peso_dist_supermercado"], pesos["peso_dist_centro_carro"],
            pesos["peso_dist_centro_onibus"],
        ))


def recalculate_all_scores():
    from app.ranking import calcular_score_todos
    calcular_score_todos()

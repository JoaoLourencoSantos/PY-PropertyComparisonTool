import os
import logging

logger = logging.getLogger(__name__)

# ── Conexão: Turso (produção) ou SQLite local (desenvolvimento) ───────────────

TURSO_URL   = os.environ.get("TURSO_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "").strip()
DB_PATH     = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imoveis.db")

_USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)


def get_connection():
    if _USE_TURSO:
        import libsql_experimental as libsql
        conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row) -> dict:
    """Converte row para dict — compatível com sqlite3.Row e libsql."""
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    # libsql retorna tuplas — precisa do cursor para obter nomes das colunas
    return row


def init_db():
    # libsql fecha streams entre chamadas — reconecta para cada operação
    stmts = [
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

    for stmt in stmts:
        conn = get_connection()
        conn.execute(stmt)
        conn.commit()

    # Migração: adiciona colunas se banco já existia sem elas
    for col in ["imagens_json TEXT", "linhas_onibus TEXT", "disponivel INTEGER DEFAULT 1",
                "checado_em TIMESTAMP", "origem TEXT"]:
        try:
            conn = get_connection()
            conn.execute(f"ALTER TABLE imoveis ADD COLUMN {col}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    # Migração: preenche origem para imóveis já existentes com base na URL
    conn = get_connection()
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
    conn.commit()

    # Recuperação: imóveis presos em 'processando' há mais de 5 min voltam para 'pendente'
    conn = get_connection()
    conn.execute("""
        UPDATE imoveis SET status = 'pendente'
        WHERE status = 'processando'
          AND (atualizado_em IS NULL
               OR atualizado_em < datetime('now', '-5 minutes'))
    """)
    conn.commit()

    logger.info("DB inicializado (%s)", "Turso" if _USE_TURSO else f"SQLite local: {DB_PATH}")


def _fetchall_as_dicts(cursor) -> list:
    """Converte resultado do cursor para lista de dicts — compatível com ambos os drivers."""
    rows = cursor.fetchall()
    if not rows:
        return []
    # sqlite3.Row já tem keys(); libsql retorna tuplas
    if hasattr(rows[0], "keys"):
        return [dict(r) for r in rows]
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


def _fetchone_as_dict(cursor) -> dict:
    row = cursor.fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def get_all_imoveis():
    conn = get_connection()
    cur = conn.execute(
        "SELECT * FROM imoveis ORDER BY score DESC NULLS LAST, criado_em DESC"
    )
    rows = _fetchall_as_dicts(cur)
    return rows


def get_imovel(imovel_id):
    conn = get_connection()
    cur = conn.execute("SELECT * FROM imoveis WHERE id = ?", (imovel_id,))
    return _fetchone_as_dict(cur)


def get_imovel_by_url(url: str):
    conn = get_connection()
    cur = conn.execute("SELECT * FROM imoveis WHERE url = ?", (url,))
    return _fetchone_as_dict(cur)


def upsert_imovel(data: dict):
    conn = get_connection()

    # libsql_experimental não suporta ON CONFLICT DO UPDATE
    # Faz INSERT OR IGNORE + UPDATE separados
    conn.execute("""
        INSERT OR IGNORE INTO imoveis (url, status)
        VALUES (?, ?)
    """, (data["url"], data.get("status", "processando")))
    conn.commit()

    # Busca o id
    cur = conn.execute("SELECT id FROM imoveis WHERE url = ?", (data["url"],))
    row = cur.fetchone()
    imovel_id = row[0] if row else None

    # Atualiza todos os campos
    conn = get_connection()
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
        data.get("origem"), data.get("titulo"), data.get("preco"),
        data.get("area_m2"), data.get("quartos"), data.get("banheiros"),
        data.get("vagas"), data.get("endereco"), data.get("bairro"),
        data.get("cidade"), data.get("lat"), data.get("lng"),
        data.get("dist_supermercado_km"), data.get("dist_centro_carro_km"),
        data.get("dist_centro_onibus_km"), data.get("tempo_centro_carro_min"),
        data.get("tempo_centro_onibus_min"), data.get("imagem_url"),
        data.get("imagens_json"), data.get("linhas_onibus"),
        data.get("score"), data.get("status"),
        data["url"],
    ))
    conn.commit()

    return imovel_id


def delete_imovel(imovel_id):
    conn = get_connection()
    conn.execute("DELETE FROM imoveis WHERE id = ?", (imovel_id,))
    conn.commit()


def get_pesos():
    conn = get_connection()
    cur = conn.execute("SELECT * FROM pesos WHERE id = 1")
    return _fetchone_as_dict(cur) or {}


def update_pesos(pesos: dict):
    conn = get_connection()
    conn.execute("""
        UPDATE pesos SET
            peso_preco = ?,
            peso_area = ?,
            peso_quartos = ?,
            peso_banheiros = ?,
            peso_dist_supermercado = ?,
            peso_dist_centro_carro = ?,
            peso_dist_centro_onibus = ?
        WHERE id = 1
    """, (
        pesos["peso_preco"], pesos["peso_area"], pesos["peso_quartos"],
        pesos["peso_banheiros"], pesos["peso_dist_supermercado"],
        pesos["peso_dist_centro_carro"], pesos["peso_dist_centro_onibus"],
    ))
    conn.commit()


def recalculate_all_scores():
    """Recalcula scores de todos os imóveis com os pesos atuais."""
    from app.ranking import calcular_score_todos
    calcular_score_todos()

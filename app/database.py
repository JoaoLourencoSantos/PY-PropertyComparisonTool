import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imoveis.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS imoveis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
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
        );

        CREATE TABLE IF NOT EXISTS pesos (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            peso_preco REAL DEFAULT 30,
            peso_area REAL DEFAULT 20,
            peso_quartos REAL DEFAULT 15,
            peso_banheiros REAL DEFAULT 10,
            peso_dist_supermercado REAL DEFAULT 10,
            peso_dist_centro_carro REAL DEFAULT 7,
            peso_dist_centro_onibus REAL DEFAULT 8
        );

        INSERT OR IGNORE INTO pesos (id) VALUES (1);
    """)

    # Migração: adiciona colunas se banco já existia sem elas
    for col in ["imagens_json TEXT", "linhas_onibus TEXT", "disponivel INTEGER DEFAULT 1", "checado_em TIMESTAMP"]:
        try:
            cur.execute(f"ALTER TABLE imoveis ADD COLUMN {col}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    conn.commit()
    conn.close()


def get_all_imoveis():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM imoveis ORDER BY score DESC NULLS LAST, criado_em DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_imovel(imovel_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM imoveis WHERE id = ?", (imovel_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_imovel(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO imoveis (url, titulo, preco, area_m2, quartos, banheiros, vagas,
            endereco, bairro, cidade, lat, lng,
            dist_supermercado_km, dist_centro_carro_km, dist_centro_onibus_km,
            tempo_centro_carro_min, tempo_centro_onibus_min,
            imagem_url, imagens_json, linhas_onibus, score, status)
        VALUES (:url, :titulo, :preco, :area_m2, :quartos, :banheiros, :vagas,
            :endereco, :bairro, :cidade, :lat, :lng,
            :dist_supermercado_km, :dist_centro_carro_km, :dist_centro_onibus_km,
            :tempo_centro_carro_min, :tempo_centro_onibus_min,
            :imagem_url, :imagens_json, :linhas_onibus, :score, :status)
        ON CONFLICT(url) DO UPDATE SET
            titulo = excluded.titulo,
            preco = excluded.preco,
            area_m2 = excluded.area_m2,
            quartos = excluded.quartos,
            banheiros = excluded.banheiros,
            vagas = excluded.vagas,
            endereco = excluded.endereco,
            bairro = excluded.bairro,
            cidade = excluded.cidade,
            lat = excluded.lat,
            lng = excluded.lng,
            dist_supermercado_km = excluded.dist_supermercado_km,
            dist_centro_carro_km = excluded.dist_centro_carro_km,
            dist_centro_onibus_km = excluded.dist_centro_onibus_km,
            tempo_centro_carro_min = excluded.tempo_centro_carro_min,
            tempo_centro_onibus_min = excluded.tempo_centro_onibus_min,
            imagem_url = excluded.imagem_url,
            imagens_json = excluded.imagens_json,
            linhas_onibus = excluded.linhas_onibus,
            score = excluded.score,
            status = excluded.status,
            atualizado_em = CURRENT_TIMESTAMP
    """, data)
    conn.commit()
    imovel_id = cur.lastrowid or conn.execute(
        "SELECT id FROM imoveis WHERE url = ?", (data["url"],)
    ).fetchone()["id"]
    conn.close()
    return imovel_id


def delete_imovel(imovel_id):
    conn = get_connection()
    conn.execute("DELETE FROM imoveis WHERE id = ?", (imovel_id,))
    conn.commit()
    conn.close()


def get_pesos():
    conn = get_connection()
    row = conn.execute("SELECT * FROM pesos WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else {}


def update_pesos(pesos: dict):
    conn = get_connection()
    conn.execute("""
        UPDATE pesos SET
            peso_preco = :peso_preco,
            peso_area = :peso_area,
            peso_quartos = :peso_quartos,
            peso_banheiros = :peso_banheiros,
            peso_dist_supermercado = :peso_dist_supermercado,
            peso_dist_centro_carro = :peso_dist_centro_carro,
            peso_dist_centro_onibus = :peso_dist_centro_onibus
        WHERE id = 1
    """, pesos)
    conn.commit()
    conn.close()


def recalculate_all_scores():
    """Recalcula scores de todos os imóveis com os pesos atuais."""
    from app.ranking import calcular_score_todos
    calcular_score_todos()

"""
Sistema de ranking ponderado para imóveis.

Cada critério é normalizado para [0, 1] e multiplicado pelo seu peso.
Critérios onde "menor é melhor" (preço, distâncias) são invertidos.
"""

import logging
from app.database import get_connection, get_pesos

logger = logging.getLogger(__name__)


def _normalizar(valores: list, inverter: bool = False) -> list:
    """
    Normaliza uma lista de valores para [0, 1].
    Se inverter=True, menor valor → score maior (ex: preço, distância).
    Valores None são tratados como 0 após normalização.
    """
    validos = [v for v in valores if v is not None]
    if not validos:
        return [0.0] * len(valores)

    vmin, vmax = min(validos), max(validos)
    if vmax == vmin:
        return [0.5 if v is not None else 0.0 for v in valores]

    resultado = []
    for v in valores:
        if v is None:
            resultado.append(0.0)
        else:
            norm = (v - vmin) / (vmax - vmin)
            resultado.append(1.0 - norm if inverter else norm)
    return resultado


def calcular_score_todos():
    """
    Recalcula o score de todos os imóveis com status != 'pendente'.
    Atualiza a coluna `score` no banco.
    """
    conn = get_connection()
    pesos = get_pesos()

    rows = conn.execute(
        """SELECT id, preco, area_m2, quartos, banheiros,
                  dist_supermercado_km, dist_centro_carro_km, dist_centro_onibus_km
           FROM imoveis
           WHERE status = 'ok'"""
    ).fetchall()

    if not rows:
        conn.close()
        return

    ids = [r["id"] for r in rows]
    precos = [r["preco"] for r in rows]
    areas = [r["area_m2"] for r in rows]
    quartos = [r["quartos"] for r in rows]
    banheiros = [r["banheiros"] for r in rows]
    dist_super = [r["dist_supermercado_km"] for r in rows]
    dist_carro = [r["dist_centro_carro_km"] for r in rows]
    dist_onibus = [r["dist_centro_onibus_km"] for r in rows]

    # Normaliza — preço e distâncias: inverter=True (menor é melhor)
    n_preco = _normalizar(precos, inverter=True)
    n_area = _normalizar(areas, inverter=False)
    n_quartos = _normalizar(quartos, inverter=False)
    n_banheiros = _normalizar(banheiros, inverter=False)
    n_dist_super = _normalizar(dist_super, inverter=True)
    n_dist_carro = _normalizar(dist_carro, inverter=True)
    n_dist_onibus = _normalizar(dist_onibus, inverter=True)

    total_peso = (
        pesos["peso_preco"]
        + pesos["peso_area"]
        + pesos["peso_quartos"]
        + pesos["peso_banheiros"]
        + pesos["peso_dist_supermercado"]
        + pesos["peso_dist_centro_carro"]
        + pesos["peso_dist_centro_onibus"]
    )

    updates = []
    for i, imovel_id in enumerate(ids):
        score = (
            n_preco[i] * pesos["peso_preco"]
            + n_area[i] * pesos["peso_area"]
            + n_quartos[i] * pesos["peso_quartos"]
            + n_banheiros[i] * pesos["peso_banheiros"]
            + n_dist_super[i] * pesos["peso_dist_supermercado"]
            + n_dist_carro[i] * pesos["peso_dist_centro_carro"]
            + n_dist_onibus[i] * pesos["peso_dist_centro_onibus"]
        ) / total_peso * 100  # escala 0–100

        updates.append((round(score, 2), imovel_id))

    conn.executemany("UPDATE imoveis SET score = ? WHERE id = ?", updates)
    conn.commit()
    conn.close()
    logger.info("Scores recalculados para %d imóveis.", len(updates))


def score_badge(score: float) -> str:
    """Retorna uma classificação textual para o score."""
    if score is None:
        return "sem dados"
    if score >= 75:
        return "Excelente"
    if score >= 55:
        return "Bom"
    if score >= 35:
        return "Regular"
    return "Abaixo da média"

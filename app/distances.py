"""
Cálculo de distâncias para o comparador de imóveis.

Estratégia em camadas (sem chave de API obrigatória):
  1. OSRM público  — roteamento real de carro/a pé (quando disponível)
  2. Haversine     — distância em linha reta × fator de tortuosidade urbana
                     suficiente para ranking comparativo entre imóveis da
                     mesma cidade

Supermercado mais próximo: Overpass API (OpenStreetMap), sem chave.
Geocodificação: Nominatim (OpenStreetMap), sem chave.
"""

import re
import json
import math
import time
import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────

# Praça Sete de Setembro — centro de BH
CENTRO_BH_LAT = -19.9191
CENTRO_BH_LNG = -43.9386

OSRM_BASE      = "https://router.project-osrm.org/route/v1"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

def _overpass_post(query: str) -> dict:
    """Tenta os mirrors do Overpass em ordem até um responder."""
    for url in OVERPASS_MIRRORS:
        try:
            resp = requests.post(url, data={"data": query}, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Overpass mirror %s falhou: %s", url, e)
    return {}

HEADERS = {"User-Agent": "ImovelComparador/1.0"}

# Fator de tortuosidade urbana: distância real ≈ linha reta × 1.35
# (valor típico para cidades brasileiras de médio/grande porte)
TORTUOSITY = 1.35

# Velocidade média de carro em BH (km/h) — considera trânsito médio
VEL_CARRO_KMH = 30.0

# Velocidade média de ônibus em BH (km/h) — inclui paradas e espera
VEL_ONIBUS_KMH = 18.0

# Tempo mínimo de espera de ônibus (min)
ESPERA_ONIBUS_MIN = 8.0


# ── Haversine ────────────────────────────────────────────────────────────────

def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Distância em linha reta entre dois pontos (km)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _estimar_distancias(lat, lng, dest_lat, dest_lng):
    """
    Estima distância e tempos via Haversine + fatores urbanos.
    Retorna (dist_km, tempo_carro_min, tempo_onibus_min).
    """
    linha_reta = _haversine_km(lat, lng, dest_lat, dest_lng)
    dist_km    = round(linha_reta * TORTUOSITY, 2)
    t_carro    = round((dist_km / VEL_CARRO_KMH) * 60, 1)
    t_onibus   = round((dist_km / VEL_ONIBUS_KMH) * 60 + ESPERA_ONIBUS_MIN, 1)
    return dist_km, t_carro, t_onibus


# ── OSRM (com retry e fallback) ──────────────────────────────────────────────

def _osrm_route(profile: str, lat1, lng1, lat2, lng2, timeout=12):
    """
    Tenta OSRM. Retorna (dist_km, dur_min) ou (None, None) se falhar.
    """
    url = (
        f"{OSRM_BASE}/{profile}/"
        f"{lng1},{lat1};{lng2},{lat2}"
        "?overview=false"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 429:
            logger.warning("OSRM rate limit — usando Haversine como fallback")
            return None, None
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "Ok":
            route = data["routes"][0]
            return round(route["distance"] / 1000, 2), round(route["duration"] / 60, 1)
    except requests.exceptions.Timeout:
        logger.warning("OSRM timeout — usando Haversine como fallback")
    except Exception as e:
        logger.warning("OSRM erro (%s): %s — usando Haversine", profile, e)
    return None, None


def _rota_com_fallback(lat, lng, dest_lat, dest_lng):
    """
    Tenta OSRM driving; se falhar usa Haversine.
    Retorna (dist_km, tempo_carro_min, tempo_onibus_min).
    """
    dist_osrm, tempo_osrm = _osrm_route("driving", lat, lng, dest_lat, dest_lng)

    if dist_osrm is not None:
        # OSRM funcionou para carro
        dist_km    = dist_osrm
        t_carro    = tempo_osrm
        t_onibus   = round((dist_km / VEL_ONIBUS_KMH) * 60 + ESPERA_ONIBUS_MIN, 1)
    else:
        # Fallback Haversine
        dist_km, t_carro, t_onibus = _estimar_distancias(lat, lng, dest_lat, dest_lng)

    return dist_km, t_carro, t_onibus


# ── Supermercado mais próximo ─────────────────────────────────────────────────

def _nearest_supermarket_km(lat, lng) -> Optional[float]:
    """
    Busca supermercado mais próximo via Overpass API.
    Retorna distância em km ou None.
    """
    query = f"""
    [out:json][timeout:20];
    (
      node["shop"="supermarket"](around:4000,{lat},{lng});
      way["shop"="supermarket"](around:4000,{lat},{lng});
    );
    out center 5;
    """
    try:
        elements = _overpass_post(query).get("elements", [])
        if not elements:
            return None

        melhor = None
        for el in elements:
            s_lat = el.get("lat") or el.get("center", {}).get("lat")
            s_lng = el.get("lon") or el.get("center", {}).get("lon")
            if s_lat and s_lng:
                d = _haversine_km(lat, lng, s_lat, s_lng) * TORTUOSITY
                if melhor is None or d < melhor:
                    melhor = d

        return round(melhor, 2) if melhor else None

    except Exception as e:
        logger.warning("Overpass supermercado erro: %s", e)
        return None


# ── Linhas de ônibus próximas ─────────────────────────────────────────────────

def buscar_linhas_onibus(lat: float, lng: float, raio_m: int = 1000) -> dict:
    """
    Busca linhas de ônibus próximas e classifica em diretas ao centro e com baldeação.
    Retorna dict: {"diretas": [...], "baldeacao": [...]} ou None.
    """
    RAIO_CENTRO_KM = 0.5

    def get_nos(rel):
        nos = []
        for m in rel.get("members", []):
            if m.get("type") == "node" and "lat" in m:
                nos.append((m["lat"], m["lon"]))
            elif m.get("type") == "way":
                for g in m.get("geometry", []):
                    if "lat" in g:
                        nos.append((g["lat"], g["lon"]))
        return nos

    def passa_centro(nos):
        return any(
            _haversine_km(CENTRO_BH_LAT, CENTRO_BH_LNG, n[0], n[1]) <= RAIO_CENTRO_KM
            for n in nos
        )

    def is_linha_valida(ref):
        return bool(ref and re.match(r"^[A-Z]?\d{3,5}[A-Z]?$", ref, re.IGNORECASE))

    # Busca relações com geometria completa
    q = f"""
    [out:json][timeout:20];
    relation["type"="route"]["route"="bus"](around:{raio_m},{lat},{lng});
    out geom;
    """
    diretas   = set()
    baldeacao = set()

    try:
        for rel in _overpass_post(q).get("elements", []):
            ref = rel.get("tags", {}).get("ref", "")
            if not is_linha_valida(ref):
                continue
            nos = get_nos(rel)
            if passa_centro(nos):
                diretas.add(ref.upper())
            else:
                baldeacao.add(ref.upper())
    except Exception as e:
        logger.warning("Overpass linhas erro: %s", e)

    # Fallback sem geometria se não achou nada
    if not diretas and not baldeacao:
        q2 = f"""
        [out:json][timeout:20];
        (
          node["highway"="bus_stop"](around:{raio_m},{lat},{lng});
          node["public_transport"="stop_position"](around:{raio_m},{lat},{lng});
        );
        out tags 30;
        """
        try:
            for el in _overpass_post(q2).get("elements", []):
                tags = el.get("tags", {})
                for campo in ["route_ref", "ref", "local_ref"]:
                    val = tags.get(campo, "")
                    for parte in re.split(r"[;,/\s]+", val):
                        parte = parte.strip()
                        if is_linha_valida(parte):
                            baldeacao.add(parte.upper())
        except Exception as e:
            logger.warning("Overpass fallback erro: %s", e)

    if not diretas and not baldeacao:
        return None

    def sort_key(x):
        try: return (0, int(x))
        except: return (1, x)

    return {
        "diretas":   sorted(diretas,   key=sort_key),
        "baldeacao": sorted(baldeacao, key=sort_key),
    }

def geocode_address(address: str):
    """
    Geocodifica endereço via Nominatim.
    Retorna (lat, lng) ou (None, None).
    """
    try:
        resp = requests.get(
            f"{NOMINATIM_BASE}/search",
            params={
                "q": f"{address}, Belo Horizonte, MG, Brasil",
                "format": "json",
                "limit": 1,
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        logger.warning("Geocode erro: %s", e)
    return None, None


# ── API pública ───────────────────────────────────────────────────────────────

def calcular_distancias(lat: float, lng: float) -> dict:
    """
    Calcula todas as distâncias para um imóvel.
    Sempre retorna valores (usa Haversine se APIs externas falharem).
    Cada etapa tem timeout independente para não travar o processamento.
    """
    import concurrent.futures

    result = {
        "dist_supermercado_km":    None,
        "dist_centro_carro_km":    None,
        "dist_centro_onibus_km":   None,
        "tempo_centro_carro_min":  None,
        "tempo_centro_onibus_min": None,
        "linhas_onibus":           None,
    }

    if not lat or not lng:
        return result

    # ── 1. Distâncias ao centro (OSRM ou Haversine) — rápido ─────────────────
    try:
        dist_km, t_carro, t_onibus = _rota_com_fallback(
            lat, lng, CENTRO_BH_LAT, CENTRO_BH_LNG
        )
        result["dist_centro_carro_km"]    = dist_km
        result["dist_centro_onibus_km"]   = dist_km
        result["tempo_centro_carro_min"]  = t_carro
        result["tempo_centro_onibus_min"] = t_onibus
    except Exception as e:
        logger.warning("Erro ao calcular distância ao centro: %s — usando Haversine", e)
        dist_km, t_carro, t_onibus = _estimar_distancias(lat, lng, CENTRO_BH_LAT, CENTRO_BH_LNG)
        result["dist_centro_carro_km"]    = dist_km
        result["dist_centro_onibus_km"]   = dist_km
        result["tempo_centro_carro_min"]  = t_carro
        result["tempo_centro_onibus_min"] = t_onibus

    # ── 2. Supermercado e linhas de ônibus em paralelo, com timeout ───────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_super  = executor.submit(_nearest_supermarket_km, lat, lng)
        fut_linhas = executor.submit(buscar_linhas_onibus, lat, lng)

        try:
            result["dist_supermercado_km"] = fut_super.result(timeout=35)
        except concurrent.futures.TimeoutError:
            logger.warning("Timeout ao buscar supermercado — ignorando")
        except Exception as e:
            logger.warning("Erro ao buscar supermercado: %s", e)

        try:
            linhas = fut_linhas.result(timeout=35)
            result["linhas_onibus"] = json.dumps(linhas, ensure_ascii=False) if linhas else None
        except concurrent.futures.TimeoutError:
            logger.warning("Timeout ao buscar linhas de ônibus — ignorando")
        except Exception as e:
            logger.warning("Erro ao buscar linhas de ônibus: %s", e)

    return result

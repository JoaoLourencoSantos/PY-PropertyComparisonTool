"""
Scraper de imóveis — ZAP Imóveis, VivaReal, OLX.

Fontes de dados (em ordem de prioridade):
  1. self.__next_f baseData  — JSON inline do Next.js App Router (ZAP/VivaReal)
  2. JSON-LD Product         — schema.org embutido na página
  3. Meta tags og:*          — fallback rápido
  4. Regex no HTML           — último recurso
"""

import re
import json
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ── Playwright: uma instância por thread (evita greenlet cross-thread) ───────
# O sync_playwright não é thread-safe — cada thread precisa do seu próprio
# contexto. Usamos threading.local() para isso.
_thread_local = threading.local()


def _fetch_html(url: str) -> Optional[str]:
    """Abre a URL com Playwright e retorna o HTML renderizado."""
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
                viewport={"width": 1280, "height": 800},
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.error("Playwright erro: %s — %s", url, e)
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_numero(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(".", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _fix_img_url(url: str) -> str:
    """Substitui placeholders de template nas URLs de imagem do ZAP."""
    return (url
            .replace("{description}", "foto")
            .replace("{action}", "fit-in")
            .replace("{width}", "800")
            .replace("{height}", "600"))


# ── Extratores ───────────────────────────────────────────────────────────────

def _extract_base_data(html: str) -> dict:
    """
    Extrai do chunk self.__next_f que contém 'baseData' com pageData.
    Estrutura: baseData.pageData.{prices, images, address, listing, ...}
    """
    # Procura o chunk que tem baseData
    pattern = re.compile(
        r'self\.__next_f\.push\(\[1,"(.*?)"\]\)',
        re.DOTALL
    )
    for raw in pattern.finditer(html):
        chunk = raw.group(1)
        if "baseData" not in chunk and "pageData" not in chunk:
            continue
        # Decodifica escapes JSON dentro da string
        try:
            decoded = bytes(chunk, "utf-8").decode("unicode_escape")
        except Exception:
            decoded = chunk

        # Extrai o objeto JSON que começa com { e contém baseData
        # O chunk é um fragmento RSC — procura o JSON embutido
        json_match = re.search(r'\{.*?"baseData".*\}', decoded, re.DOTALL)
        if not json_match:
            # Tenta direto no chunk original
            json_match = re.search(r'\{.*?"baseData".*\}', chunk, re.DOTALL)
        if not json_match:
            continue

        try:
            # O JSON pode estar dentro de um array RSC maior, tenta parsear
            jd = json.loads(json_match.group())
            # Navega até baseData
            base = None
            if "baseData" in jd:
                base = jd["baseData"]
            else:
                # Pode estar aninhado em props de componente React
                for v in jd.values():
                    if isinstance(v, dict) and "baseData" in v:
                        base = v["baseData"]
                        break

            if not base:
                continue

            page_data = base.get("pageData", {})
            return _parse_page_data(page_data)

        except json.JSONDecodeError:
            continue

    return {}


def _parse_page_data(pd: dict) -> dict:
    """Parseia o objeto pageData do ZAP/VivaReal."""
    data = {}

    # Preço
    prices = pd.get("prices") or []
    for p in prices:
        if p.get("businessType") == "SALE":
            data["preco"] = _parse_numero(p.get("price"))
            break
    if not data.get("preco") and prices:
        data["preco"] = _parse_numero(prices[0].get("price"))

    # Imagem
    images = pd.get("images") or []
    if images:
        raw_url = images[0].get("dangerousSrc") or images[0].get("url") or ""
        if raw_url:
            data["imagem_url"] = _fix_img_url(raw_url)

    # Listing (área, quartos, banheiros, vagas, endereço)
    listing = pd.get("listing") or {}
    if listing:
        data.update(_parse_listing_obj(listing))

    # Address direto no pageData
    addr = pd.get("address") or {}
    if addr and not data.get("lat"):
        data.update(_parse_address(addr))

    return {k: v for k, v in data.items() if v is not None}


def _parse_listing_obj(listing: dict) -> dict:
    data = {}

    areas = listing.get("usableAreas") or listing.get("totalAreas") or []
    if areas:
        data["area_m2"] = _parse_numero(areas[0])

    beds = listing.get("bedrooms") or []
    if beds:
        data["quartos"] = int(_parse_numero(beds[0]) or 0) or None

    baths = listing.get("bathrooms") or []
    if baths:
        data["banheiros"] = int(_parse_numero(baths[0]) or 0) or None

    parks = listing.get("parkingSpaces") or []
    if parks:
        data["vagas"] = int(_parse_numero(parks[0]) or 0) or None

    addr = listing.get("address") or {}
    data.update(_parse_address(addr))

    return {k: v for k, v in data.items() if v is not None}


def _parse_address(addr: dict) -> dict:
    data = {}
    street = addr.get("street") or ""
    neighborhood = addr.get("neighborhood") or ""
    data["endereco"] = (f"{street}, {neighborhood}".strip(", ")) or None
    data["bairro"] = neighborhood or None
    data["cidade"] = addr.get("city") or "Belo Horizonte"

    point = addr.get("point") or {}
    lat = point.get("lat")
    lng = point.get("lon") or point.get("lng")
    if lat:
        data["lat"] = lat
    if lng:
        data["lng"] = lng

    return {k: v for k, v in data.items() if v is not None}


def _extract_json_ld(html: str) -> dict:
    """Extrai dados do JSON-LD schema.org/Product."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    data = {}

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            jd = json.loads(script.string or "")
            if jd.get("@type") == "Product":
                data["titulo"] = jd.get("name")
                imgs = jd.get("image") or []
                if imgs:
                    data["imagem_url"] = imgs[0]
                # Preço via offers
                offers = jd.get("offers") or {}
                if isinstance(offers, dict):
                    data["preco"] = _parse_numero(offers.get("price"))
                break
        except Exception:
            continue

    return {k: v for k, v in data.items() if v is not None}


def _extract_meta(html: str) -> dict:
    """Extrai dados das meta tags og:* e description."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    data = {}

    metas = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name") or ""
        val = tag.get("content") or ""
        if val:
            metas[key] = val

    data["titulo"] = metas.get("og:title") or metas.get("twitter:title")
    data["imagem_url"] = metas.get("og:image")

    # og:description contém: "X quartos ... por R$ 200.000"
    desc = metas.get("og:description") or metas.get("description") or ""
    if desc:
        preco_m = re.search(r"R\$\s*([\d.,]+)", desc)
        if preco_m:
            data["preco"] = _parse_numero(preco_m.group(1))

        area_m = re.search(r"(\d+)\s*m²", desc)
        if area_m:
            data["area_m2"] = float(area_m.group(1))

        quartos_m = re.search(r"(\d+)\s*quarto", desc, re.IGNORECASE)
        if quartos_m:
            data["quartos"] = int(quartos_m.group(1))

    return {k: v for k, v in data.items() if v is not None}


def _extract_next_f_basedata_v2(html: str) -> dict:
    """
    Extrai dados do HTML do ZAP/VivaReal (Next.js App Router).
    Os dados ficam em strings JSON escapadas dentro dos chunks self.__next_f,
    então os campos aparecem como \"bathrooms\":[1] no HTML bruto.
    Tentamos duas formas: com aspas escapadas e com aspas normais.
    """
    data = {}

    def search(patterns, cast=str):
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                try:
                    return cast(m.group(1))
                except Exception:
                    pass
        return None

    # Preço — aparece como \"price\":\"200000\" ou "price":"200000"
    price = search([
        r'\\"price\\":\\"(\d+)\\".*?\\"businessType\\":\\"SALE\\"',
        r'\\"businessType\\":\\"SALE\\".*?\\"price\\":\\"(\d+)\\"',
        r'"price"\s*:\s*"(\d+)".*?"businessType"\s*:\s*"SALE"',
        r'"businessType"\s*:\s*"SALE".*?"price"\s*:\s*"(\d+)"',
    ], float)
    if price:
        data["preco"] = price

    # amenities block: \"amenities\":{\"usableAreas\":[42],\"bedrooms\":[2],...}
    amenities_m = re.search(r'\\"amenities\\":\{(.*?)\}', html)
    if not amenities_m:
        amenities_m = re.search(r'"amenities"\s*:\s*\{(.*?)\}', html)

    if amenities_m:
        block = amenities_m.group(1)
        # Extrai cada campo do bloco amenities
        def get_array_val(key, block):
            m = re.search(rf'\\?"{key}\\?":\[(\d+)\]', block)
            return int(m.group(1)) if m else None

        data["area_m2"]    = get_array_val("usableAreas", block) and float(get_array_val("usableAreas", block))
        data["quartos"]    = get_array_val("bedrooms", block)
        data["banheiros"]  = get_array_val("bathrooms", block)
        data["vagas"]      = get_array_val("parkingSpaces", block)
    else:
        # Fallback campo a campo
        for key, field, cast in [
            ("usableAreas", "area_m2", float),
            ("bedrooms",    "quartos",   int),
            ("bathrooms",   "banheiros", int),
            ("parkingSpaces","vagas",    int),
        ]:
            v = search([
                rf'\\"{key}\\":\[(\d+)\]',
                rf'"{key}"\s*:\s*\[(\d+)\]',
            ], cast)
            if v is not None:
                data[field] = v

    # Bairro — \"neighborhood\":\"São Gabriel\" (unicode escapado ou não)
    neigh = search([
        r'\\"neighborhood\\":\\"([^"\\\\]+)\\"',
        r'"neighborhood"\s*:\s*"([^"]+)"',
    ])
    if neigh:
        data["bairro"] = neigh

    # Rua
    street = search([
        r'\\"street\\":\\"([^"\\\\]+)\\"',
        r'"street"\s*:\s*"([^"]+)"',
    ])
    if street:
        data["endereco"] = f"{street}, {neigh or ''}".strip(", ")

    # Cidade
    city = search([
        r'\\"city\\":\\"([^"\\\\]+)\\"',
        r'"city"\s*:\s*"([^"]+)"',
    ])
    if city:
        data["cidade"] = city

    # Coordenadas — podem estar no Google Maps embed URL
    # ex: maps/embed/v1/place?key=...&q=Rua+Ana+Pereira+Menezes
    # ou como lat/lng direto
    lat = search([
        r'\\"lat\\":\s*(-?\d{2,3}\.\d+)',
        r'"lat"\s*:\s*(-?\d{2,3}\.\d+)',
    ], float)
    lng = search([
        r'\\"lon\\":\s*(-?\d{2,3}\.\d+)',
        r'"lon"\s*:\s*(-?\d{2,3}\.\d+)',
        r'\\"lng\\":\s*(-?\d{2,3}\.\d+)',
        r'"lng"\s*:\s*(-?\d{2,3}\.\d+)',
    ], float)

    # Google Maps embed: &q=Rua+... — extrai endereço para geocodificar depois
    if not data.get("endereco"):
        maps_q = re.search(r'maps/embed[^"]*[?&]q=([^&"\\]+)', html)
        if maps_q:
            import urllib.parse
            addr_raw = urllib.parse.unquote_plus(maps_q.group(1))
            data["endereco"] = addr_raw.replace(" - ", ", ")

    if lat:
        data["lat"] = lat
    if lng:
        data["lng"] = lng

    # Imagens — coleta no máximo 3 dangerousSrc únicas (ZAP e VivaReal)
    all_img_matches = re.findall(
        r'(?:\\"dangerousSrc\\":\\"|\\"url\\":\\")(https://resizedimgs\.[^"\\]+)',
        html
    )
    urls_imgs = []
    seen = set()
    for raw_url in all_img_matches:
        fixed = _fix_img_url(raw_url)
        if fixed not in seen:
            seen.add(fixed)
            urls_imgs.append(fixed)
        if len(urls_imgs) == 3:
            break

    if urls_imgs:
        data["imagem_url"] = urls_imgs[0]
        data["imagens_json"] = json.dumps(urls_imgs, ensure_ascii=False)
    else:
        # Fallback: JSON-LD Product images
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                jd = json.loads(script.string or "")
                if jd.get("@type") == "Product":
                    imgs_ld = [u for u in (jd.get("image") or [])
                               if "resizedimgs." in u][:3]
                    if imgs_ld:
                        data["imagem_url"] = imgs_ld[0]
                        data["imagens_json"] = json.dumps(imgs_ld, ensure_ascii=False)
                    break
            except Exception:
                pass

    return {k: v for k, v in data.items() if v is not None}


# ── Dispatcher principal ─────────────────────────────────────────────────────

_DEFAULTS = {
    "titulo": None, "preco": None, "area_m2": None, "quartos": None,
    "banheiros": None, "vagas": None, "endereco": None, "bairro": None,
    "cidade": "Belo Horizonte", "lat": None, "lng": None,
    "dist_supermercado_km": None, "dist_centro_carro_km": None,
    "dist_centro_onibus_km": None, "tempo_centro_carro_min": None,
    "tempo_centro_onibus_min": None, "linhas_onibus": None,
    "imagem_url": None, "imagens_json": None,
    "score": None, "status": "processando",
}


def scrape_imovel(url: str) -> dict:
    html = _fetch_html(url)
    if not html:
        return {"erro": "Não foi possível acessar a URL"}

    data = {}

    # 1. Regex direto no HTML (mais robusto para ZAP/VivaReal App Router)
    regex_data = _extract_next_f_basedata_v2(html)
    data.update(regex_data)

    # 2. JSON-LD para título e imagem
    jsonld_data = _extract_json_ld(html)
    for k, v in jsonld_data.items():
        if not data.get(k):
            data[k] = v

    # 3. Meta tags como fallback
    meta_data = _extract_meta(html)
    for k, v in meta_data.items():
        if not data.get(k):
            data[k] = v

    if not data.get("preco") and not data.get("area_m2") and not data.get("titulo"):
        return {"erro": "Não foi possível extrair dados do imóvel"}

    result = dict(_DEFAULTS)
    result["url"] = url
    result.update({k: v for k, v in data.items() if v is not None})
    return result

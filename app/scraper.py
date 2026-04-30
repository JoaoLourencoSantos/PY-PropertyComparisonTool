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


def _fetch_html(url: str, wait_until: str = "domcontentloaded",
                extra_wait_ms: int = 2000) -> Optional[str]:
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
            page.goto(url, wait_until=wait_until, timeout=90000)
            if extra_wait_ms:
                page.wait_for_timeout(extra_wait_ms)
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

def _detectar_origem(url: str) -> str:
    """Detecta o portal de origem com base na URL."""
    u = url.lower()
    if "zapimoveis" in u:   return "ZAP Imóveis"
    if "vivareal" in u:     return "VivaReal"
    if "quintoandar" in u:  return "QuintoAndar"
    if "olx" in u:          return "OLX"
    return "Outro"


_DEFAULTS = {
    "origem": None,
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
    # Limpa parâmetros de query da URL (tracking, etc.)
    url_clean = url.split("?")[0].rstrip("/")

    # QuintoAndar renderiza o JSON-LD server-side no <head> — não depende de
    # hidratação do React. Usar "domcontentloaded" é suficiente e evita o
    # timeout causado por "networkidle" (o site tem dezenas de scripts de
    # analytics que nunca param de fazer requests, impedindo o networkidle
    # de ser atingido dentro do timeout de 90s).
    html = _fetch_html(
        url_clean,
        wait_until="domcontentloaded",
        extra_wait_ms=1500,
    )
    if not html:
        return {"erro": "Não foi possível acessar a URL"}

    data = {}

    # Dispatcher por domínio
    domain = url_clean.lower()
    if "quintoandar" in domain:
        data = _scrape_quintoandar(html, url_clean)
    else:
        # 1. Regex direto no HTML (ZAP/VivaReal App Router)
        data = _extract_next_f_basedata_v2(html)

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
    result["url"] = url_clean
    result["origem"] = _detectar_origem(url_clean)
    result.update({k: v for k, v in data.items() if v is not None})
    return result


# ── QuintoAndar ───────────────────────────────────────────────────────────────

_QA_BASE = "https://www.quintoandar.com.br"


def _qa_abs_img(url: str) -> str:
    """Garante URL absoluta e prefere resolução xlg para imagens do QuintoAndar."""
    if not url:
        return url
    if not url.startswith("http"):
        url = f"{_QA_BASE}{url}"
    # Sobe para resolução maior quando possível
    for low, high in (("/img/med/", "/img/xlg/"), ("/img/sml/", "/img/xlg/"),
                      ("/img/xsm/", "/img/xlg/")):
        url = url.replace(low, high)
    return url


def _scrape_quintoandar(html: str, url: str) -> dict:
    """
    Extrai dados do QuintoAndar via JSON-LD @type Apartment (fonte primária)
    com fallback para meta tags og:* e description.

    O QuintoAndar renderiza o JSON-LD schema.org/Apartment server-side no
    <head> — não depende de __NEXT_DATA__ nem de hidratação do React.

    Campos extraídos:
      titulo, preco, area_m2, quartos, banheiros, vagas,
      endereco, bairro, cidade, lat, lng,
      imagem_url, imagens_json
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    data: dict = {}

    # ── 1. JSON-LD @type Apartment ────────────────────────────────────────────
    apartment_ld = None
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            jd = json.loads(script.string or "")
            if jd.get("@type") == "Apartment":
                apartment_ld = jd
                break
        except Exception:
            continue

    if apartment_ld:
        logger.info("QuintoAndar: JSON-LD Apartment encontrado para %s", url)

        # Título — vem limpo no JSON-LD (sem o artefato &nbsp; do <title>)
        data["titulo"] = apartment_ld.get("name") or None

        # Preço — potentialAction.price (BuyAction) é o campo mais confiável
        action = apartment_ld.get("potentialAction") or {}
        price_val = action.get("price")
        if price_val is not None:
            try:
                data["preco"] = float(price_val)
            except (TypeError, ValueError):
                data["preco"] = _parse_numero(price_val)
        else:
            # Fallback: offers.price
            offers = apartment_ld.get("offers") or {}
            if offers.get("price") is not None:
                data["preco"] = _parse_numero(offers["price"])

        # Área — floorSize (m²)
        floor_size = apartment_ld.get("floorSize")
        if floor_size is not None:
            try:
                data["area_m2"] = float(floor_size)
            except (TypeError, ValueError):
                data["area_m2"] = _parse_numero(floor_size)

        # Quartos — numberOfBedrooms tem precedência sobre numberOfRooms
        for field in ("numberOfBedrooms", "numberOfRooms"):
            val = apartment_ld.get(field)
            if val is not None:
                try:
                    data["quartos"] = int(val)
                    break
                except (TypeError, ValueError):
                    pass

        # Banheiros
        bath_val = apartment_ld.get("numberOfFullBathrooms")
        if bath_val is not None:
            try:
                data["banheiros"] = int(bath_val)
            except (TypeError, ValueError):
                pass

        # Vagas — amenityFeature é uma lista de LocationFeatureSpecification.
        # O QuintoAndar não expõe o número exato de vagas nesse campo;
        # usa "Box" ou "Garagem" com value=true/int.
        # Estratégia: soma features de vaga com value numérico; se só booleano,
        # conta quantas features de vaga existem (cada uma = 1 vaga).
        vagas_count = 0
        vagas_bool = 0
        for feat in (apartment_ld.get("amenityFeature") or []):
            name = (feat.get("name") or "").lower()
            if any(k in name for k in ("vaga", "garagem", "parking", "box")):
                val = feat.get("value")
                if isinstance(val, (int, float)) and val > 0:
                    vagas_count += int(val)
                elif val is True:
                    vagas_bool += 1
        if vagas_count:
            data["vagas"] = vagas_count
        elif vagas_bool:
            data["vagas"] = vagas_bool

        # Endereço — pode ser string "Rua X, Bairro, Cidade" ou objeto PostalAddress
        addr_raw = apartment_ld.get("address") or ""
        if isinstance(addr_raw, str) and addr_raw.strip():
            # Ex: "Rua Alípio de Melo, Jardim Montanhês, Belo Horizonte"
            parts = [p.strip() for p in addr_raw.split(",")]
            data["endereco"] = addr_raw.strip()
            if len(parts) >= 2:
                data["bairro"] = parts[1].strip()
            data["cidade"] = parts[2].strip() if len(parts) >= 3 else "Belo Horizonte"
        elif isinstance(addr_raw, dict):
            street = addr_raw.get("streetAddress") or ""
            neighborhood = addr_raw.get("addressLocality") or ""
            city = addr_raw.get("addressRegion") or "Belo Horizonte"
            data["endereco"] = ", ".join(filter(None, [street, neighborhood])) or None
            data["bairro"] = neighborhood or None
            data["cidade"] = city

        # Coordenadas — geo.latitude / geo.longitude
        geo = apartment_ld.get("geo") or {}
        lat_val = geo.get("latitude")
        lng_val = geo.get("longitude")
        if lat_val is not None:
            try:
                data["lat"] = float(lat_val)
            except (TypeError, ValueError):
                pass
        if lng_val is not None:
            try:
                data["lng"] = float(lng_val)
            except (TypeError, ValueError):
                pass

        # Imagens — lista de URLs (podem ser relativas ou absolutas)
        imgs_ld = apartment_ld.get("image") or []
        urls_imgs = []
        seen: set = set()
        for img_url in imgs_ld[:10]:
            if not img_url:
                continue
            img_url = _qa_abs_img(str(img_url))
            if img_url not in seen:
                seen.add(img_url)
                urls_imgs.append(img_url)

        if urls_imgs:
            data["imagem_url"] = urls_imgs[0]
            data["imagens_json"] = json.dumps(urls_imgs, ensure_ascii=False)

    else:
        logger.warning("QuintoAndar: JSON-LD Apartment não encontrado em %s — usando meta tags", url)

    # ── 2. Complementa / fallback com meta tags ───────────────────────────────
    # Coleta todas as meta tags de uma vez
    metas: dict = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name") or tag.get("itemprop") or ""
        val = tag.get("content") or ""
        if key and val:
            metas[key] = val

    # Título: usa og:title apenas se ainda não temos (JSON-LD é mais limpo)
    if not data.get("titulo"):
        raw_title = metas.get("og:title") or metas.get("twitter:title") or ""
        # Remove sufixo " - QuintoAndar" e artefatos de encoding
        raw_title = re.sub(r"\s*-\s*QuintoAndar\s*$", "", raw_title).strip()
        # Corrige o artefato de &nbsp; que aparece como sequência UUID no <title>
        raw_title = re.sub(
            r"R[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}nbsp;",
            "R$ ",
            raw_title,
        )
        if raw_title:
            data["titulo"] = raw_title

    # Imagem: og:image como fallback (pode ser relativa)
    if not data.get("imagem_url"):
        og_img = (metas.get("og:image") or metas.get("twitter:image")
                  or metas.get("image") or metas.get("itemprop:image"))
        if og_img:
            data["imagem_url"] = _qa_abs_img(og_img)

    # Preço, área, quartos via description (último recurso)
    desc = metas.get("og:description") or metas.get("description") or ""
    if desc:
        if not data.get("preco"):
            preco_m = re.search(r"R\$\s*([\d.,]+)", desc)
            if preco_m:
                data["preco"] = _parse_numero(preco_m.group(1))

        if not data.get("area_m2"):
            area_m = re.search(r"(\d+)\s*m²", desc)
            if area_m:
                data["area_m2"] = float(area_m.group(1))

        if not data.get("quartos"):
            quartos_m = re.search(r"(\d+)\s*quarto", desc, re.IGNORECASE)
            if quartos_m:
                data["quartos"] = int(quartos_m.group(1))

        if not data.get("banheiros"):
            bath_m = re.search(r"(\d+)\s*banheiro", desc, re.IGNORECASE)
            if bath_m:
                data["banheiros"] = int(bath_m.group(1))

        if not data.get("vagas"):
            vagas_m = re.search(r"(\d+)\s*vaga", desc, re.IGNORECASE)
            if vagas_m:
                data["vagas"] = int(vagas_m.group(1))

    return {k: v for k, v in data.items() if v is not None}

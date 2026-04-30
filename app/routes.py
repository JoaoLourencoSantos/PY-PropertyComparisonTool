"""
Rotas Flask — API REST + página principal.
"""

import threading
import logging
import requests
from flask import Blueprint, jsonify, request, render_template, abort, Response

from app.database import (
    get_all_imoveis,
    get_imovel,
    get_imovel_by_url,
    upsert_imovel,
    delete_imovel,
    get_pesos,
    update_pesos,
    recalculate_all_scores,
)
from app.scraper import scrape_imovel
from app.distances import calcular_distancias, geocode_address
from app.ranking import calcular_score_todos, score_badge

logger = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

# Limita scraping simultâneo — cada Chromium usa ~150MB, starter tem 512MB
# 2 threads = ~300MB de Chromium + ~100MB Flask/Python = seguro
_scraping_semaphore = threading.Semaphore(2)


# ─── Página principal ────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("index.html")


# ─── Proxy de imagens (evita bloqueio de hotlink) ────────────────────────────

@bp.route("/img-proxy")
def img_proxy():
    """
    Busca a imagem no servidor de origem e repassa para o browser.
    Envia o Referer correto para passar pelo hotlink check do ZAP/VivaReal.
    """
    url = request.args.get("url", "")

    allowed = (
        "https://resizedimgs.zapimoveis.com.br",
        "https://resizedimgs.vivareal.com",
        "https://www.quintoandar.com.br/img/",
    )
    if not url or not any(url.startswith(a) for a in allowed):
        abort(400)

    if "vivareal.com" in url:
        referer = "https://www.vivareal.com.br/"
    elif "quintoandar" in url:
        referer = "https://www.quintoandar.com.br/"
    else:
        referer = "https://www.zapimoveis.com.br/"

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Referer": referer,
                "Accept": "image/webp,image/avif,image/*,*/*",
            },
            timeout=15,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/webp")
        return Response(
            resp.content,
            status=200,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as e:
        logger.warning("img-proxy erro: %s", e)
        abort(502)


# ─── API: Imóveis ─────────────────────────────────────────────────────────────

@bp.route("/api/imoveis", methods=["GET"])
def listar_imoveis():
    imoveis = get_all_imoveis()

    # Conta quantas threads de scraping estão rodando agora
    slots_livres = _scraping_semaphore._value

    # Lança no máximo `slots_livres` pendentes por chamada
    pendentes = [im for im in imoveis if im["status"] == "pendente"]
    para_lancar = pendentes[:slots_livres] if slots_livres > 0 else []

    for im in para_lancar:
        im["status"] = "processando"
        upsert_imovel(im)
        thread = threading.Thread(
            target=_processar_imovel, args=(im["id"], im["url"]), daemon=True
        )
        thread.start()

    if para_lancar:
        imoveis = get_all_imoveis()

    for im in imoveis:
        im["badge"] = score_badge(im.get("score"))
    return jsonify(imoveis)


@bp.route("/api/imoveis/<int:imovel_id>", methods=["GET"])
def detalhe_imovel(imovel_id):
    im = get_imovel(imovel_id)
    if not im:
        abort(404)
    im["badge"] = score_badge(im.get("score"))
    return jsonify(im)


@bp.route("/api/imoveis", methods=["POST"])
def adicionar_imovel():
    body = request.get_json(force=True)
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"erro": "URL é obrigatória"}), 400

    # Limpa parâmetros de tracking antes de salvar (mesma lógica do scraper)
    url = url.split("?")[0].rstrip("/")

    # Verifica duplicata
    existente = get_imovel_by_url(url)
    if existente:
        return jsonify({
            "erro": "Este imóvel já está na lista.",
            "id": existente["id"],
            "status": existente["status"],
            "duplicado": True,
        }), 409

    # Salva imediatamente com status pendente
    dados_iniciais = {
        "url": url,
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
    imovel_id = upsert_imovel(dados_iniciais)

    # Processa em background
    thread = threading.Thread(
        target=_processar_imovel, args=(imovel_id, url), daemon=True
    )
    thread.start()

    return jsonify({"id": imovel_id, "status": "processando"}), 202


@bp.route("/api/imoveis/importar-lote", methods=["POST"])
def importar_lote():
    """
    Importação síncrona via Server-Sent Events.
    Processa uma URL por vez — sem threads paralelas, sem OOM.
    O cliente recebe eventos de progresso em tempo real.
    """
    body = request.get_json(force=True)
    urls_raw = body.get("urls") or []
    if not urls_raw:
        return jsonify({"erro": "Lista de URLs vazia"}), 400

    # Limpa URLs
    urls = []
    for u in urls_raw:
        u = (u or "").strip().split("?")[0].rstrip("/")
        if u and u.startswith("http"):
            urls.append(u)

    def gerar_eventos():
        total = len(urls)
        yield f"data: {json.dumps({'tipo': 'inicio', 'total': total})}\n\n"

        for i, url in enumerate(urls):
            yield f"data: {json.dumps({'tipo': 'progresso', 'idx': i+1, 'total': total, 'url': url})}\n\n"

            try:
                # Verifica duplicata
                existente = get_imovel_by_url(url)
                if existente:
                    yield f"data: {json.dumps({'tipo': 'resultado', 'idx': i+1, 'total': total, 'url': url, 'id': existente['id'], 'status': 'duplicado'})}\n\n"
                    continue

                # Salva como processando
                dados_iniciais = {
                    "url": url, "origem": None, "titulo": None, "preco": None,
                    "area_m2": None, "quartos": None, "banheiros": None, "vagas": None,
                    "endereco": None, "bairro": None, "cidade": "Belo Horizonte",
                    "lat": None, "lng": None,
                    "dist_supermercado_km": None, "dist_centro_carro_km": None,
                    "dist_centro_onibus_km": None, "tempo_centro_carro_min": None,
                    "tempo_centro_onibus_min": None, "linhas_onibus": None,
                    "imagem_url": None, "imagens_json": None,
                    "score": None, "status": "processando",
                }
                imovel_id = upsert_imovel(dados_iniciais)

                # Processa de forma síncrona (sem thread)
                _processar_imovel_interno(imovel_id, url)

                # Verifica resultado
                im = get_imovel(imovel_id)
                status = im["status"] if im else "erro"
                yield f"data: {json.dumps({'tipo': 'resultado', 'idx': i+1, 'total': total, 'url': url, 'id': imovel_id, 'status': status})}\n\n"

            except Exception as e:
                logger.exception("Erro ao importar %s: %s", url, e)
                yield f"data: {json.dumps({'tipo': 'resultado', 'idx': i+1, 'total': total, 'url': url, 'status': 'erro', 'motivo': str(e)[:100]})}\n\n"

        # Recalcula scores ao final
        try:
            calcular_score_todos()
        except Exception:
            pass

        yield f"data: {json.dumps({'tipo': 'fim', 'total': total})}\n\n"

    import json as json_mod
    # Precisamos do json no escopo do generator
    import json
    return Response(gerar_eventos(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/api/imoveis/<int:imovel_id>", methods=["DELETE"])
def remover_imovel(imovel_id):
    delete_imovel(imovel_id)
    return jsonify({"ok": True})


@bp.route("/api/imoveis/<int:imovel_id>/reprocessar", methods=["POST"])
def reprocessar_imovel(imovel_id):
    im = get_imovel(imovel_id)
    if not im:
        abort(404)

    # Marca como processando
    im["status"] = "processando"
    upsert_imovel(im)

    thread = threading.Thread(
        target=_processar_imovel, args=(imovel_id, im["url"]), daemon=True
    )
    thread.start()
    return jsonify({"status": "processando"})


# ─── API: Pesos ───────────────────────────────────────────────────────────────

@bp.route("/api/pesos", methods=["GET"])
def obter_pesos():
    return jsonify(get_pesos())


@bp.route("/api/pesos", methods=["PUT"])
def salvar_pesos():
    body = request.get_json(force=True)
    campos = [
        "peso_preco", "peso_area", "peso_quartos", "peso_banheiros",
        "peso_dist_supermercado", "peso_dist_centro_carro", "peso_dist_centro_onibus",
    ]
    pesos = {}
    for campo in campos:
        val = body.get(campo)
        if val is None:
            return jsonify({"erro": f"Campo {campo} ausente"}), 400
        try:
            pesos[campo] = float(val)
        except (TypeError, ValueError):
            return jsonify({"erro": f"Valor inválido para {campo}"}), 400

    update_pesos(pesos)
    recalculate_all_scores()
    return jsonify({"ok": True})


# ─── Processamento em background ─────────────────────────────────────────────

# Timeout total para processar um imóvel (scraping + distâncias), em segundos.
# Chromium pode travar — esse limite garante que o status nunca fica preso.
_TIMEOUT_PROCESSAMENTO = 240


def _processar_imovel(imovel_id: int, url: str):
    """
    Faz scraping + geocodificação + distâncias + score.
    Usa semáforo para limitar Chromium simultâneos e evitar OOM.
    """
    import concurrent.futures as cf

    def _executar():
        with _scraping_semaphore:
            logger.info("[%d] Semáforo adquirido (slots restantes: %d)",
                        imovel_id, _scraping_semaphore._value)
            _processar_imovel_interno(imovel_id, url)

    try:
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_executar)
            try:
                fut.result(timeout=_TIMEOUT_PROCESSAMENTO)
            except cf.TimeoutError:
                logger.error(
                    "Timeout de %ds ao processar imóvel %d — marcando como erro",
                    _TIMEOUT_PROCESSAMENTO, imovel_id,
                )
                _marcar_erro(imovel_id, url, f"Timeout após {_TIMEOUT_PROCESSAMENTO}s")
            except Exception as e:
                logger.exception("Erro ao processar imóvel %d: %s", imovel_id, e)
                _marcar_erro(imovel_id, url, str(e))
    except Exception as e:
        # Segurança extra: garante que qualquer falha fora do executor
        # também marca o erro no banco
        logger.exception("Erro crítico ao processar imóvel %d: %s", imovel_id, e)
        _marcar_erro(imovel_id, url, str(e))


def _processar_imovel_interno(imovel_id: int, url: str):
    """Lógica real de processamento — chamada dentro de um executor com timeout."""
    # Chaves obrigatórias para o upsert — garante que nenhuma falta
    _REQUIRED = {
        "url": url, "origem": None, "titulo": None, "preco": None,
        "area_m2": None, "quartos": None, "banheiros": None, "vagas": None,
        "endereco": None, "bairro": None, "cidade": "Belo Horizonte",
        "lat": None, "lng": None,
        "dist_supermercado_km": None, "dist_centro_carro_km": None,
        "dist_centro_onibus_km": None, "tempo_centro_carro_min": None,
        "tempo_centro_onibus_min": None, "linhas_onibus": None,
        "imagem_url": None, "imagens_json": None,
        "score": None, "status": "processando",
    }

    try:
        logger.info("[%d] INÍCIO — %s", imovel_id, url)

        # 1. Scraping
        logger.info("[%d] Etapa 1/5: scraping...", imovel_id)
        dados = scrape_imovel(url)
        if "erro" in dados:
            logger.warning("[%d] Scraping falhou: %s", imovel_id, dados["erro"])
            _marcar_erro(imovel_id, url, dados["erro"])
            return
        logger.info("[%d] Scraping OK — preco=%s area=%s quartos=%s lat=%s lng=%s",
                    imovel_id, dados.get("preco"), dados.get("area_m2"),
                    dados.get("quartos"), dados.get("lat"), dados.get("lng"))

        # Garante todas as chaves necessárias
        base = dict(_REQUIRED)
        base.update(dados)
        dados = base
        dados["id"] = imovel_id

        # 2. Geocodificação (se não veio do scraper)
        if not dados.get("lat") and dados.get("endereco"):
            logger.info("[%d] Etapa 2/5: geocodificando '%s'...", imovel_id, dados["endereco"])
            lat, lng = geocode_address(dados["endereco"])
            dados["lat"] = lat
            dados["lng"] = lng
            logger.info("[%d] Geocode OK — lat=%s lng=%s", imovel_id, lat, lng)
        else:
            logger.info("[%d] Etapa 2/5: geocode pulado (lat/lng já disponíveis ou sem endereço)", imovel_id)

        # 3. Distâncias
        if dados.get("lat") and dados.get("lng"):
            logger.info("[%d] Etapa 3/5: calculando distâncias (lat=%s, lng=%s)...",
                        imovel_id, dados["lat"], dados["lng"])
            distancias = calcular_distancias(dados["lat"], dados["lng"])
            dados.update(distancias)
            dados["status"] = "ok"
            logger.info("[%d] Distâncias OK — centro=%.1fkm super=%s linhas=%s",
                        imovel_id,
                        distancias.get("dist_centro_carro_km") or 0,
                        distancias.get("dist_supermercado_km"),
                        "sim" if distancias.get("linhas_onibus") else "não")
        else:
            logger.warning("[%d] Etapa 3/5: sem coordenadas — distâncias ignoradas", imovel_id)
            dados["status"] = "sem_coordenadas"

        # 4. Salva
        logger.info("[%d] Etapa 4/5: salvando no banco...", imovel_id)
        upsert_imovel(dados)

        # 5. Recalcula scores de todos
        logger.info("[%d] Etapa 5/5: recalculando scores...", imovel_id)
        calcular_score_todos()

        logger.info("[%d] ✅ CONCLUÍDO com status '%s'", imovel_id, dados["status"])

    except Exception as e:
        logger.exception("[%d] ❌ Exceção não tratada: %s", imovel_id, e)
        _marcar_erro(imovel_id, url, str(e))


def _marcar_erro(imovel_id: int, url: str, mensagem: str):
    try:
        dados = {
            "id": imovel_id,
            "url": url, "origem": None,
            "titulo": f"Erro: {mensagem[:80]}",
            "preco": None, "area_m2": None, "quartos": None, "banheiros": None,
            "vagas": None, "endereco": None, "bairro": None, "cidade": None,
            "lat": None, "lng": None,
            "dist_supermercado_km": None, "dist_centro_carro_km": None,
            "dist_centro_onibus_km": None, "tempo_centro_carro_min": None,
            "tempo_centro_onibus_min": None, "linhas_onibus": None,
            "imagem_url": None, "imagens_json": None,
            "score": None, "status": "erro",
        }
        upsert_imovel(dados)
    except Exception as e:
        logger.exception("Falha ao marcar erro para imóvel %d: %s", imovel_id, e)

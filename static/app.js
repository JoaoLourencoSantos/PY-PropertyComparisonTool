/* ── Comparador de Imóveis — Frontend ──────────────────────────────────── */

const API = "";
let todosImoveis = [];
let pollingTimer = null;

// ── Utilitários ─────────────────────────────────────────────────────────────

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function fmt_preco(v) {
  if (v == null) return "—";
  return "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 0 });
}
function fmt_num(v, suffix = "") {
  if (v == null) return "—";
  return Number(v).toLocaleString("pt-BR") + suffix;
}
function fmt_dist(v) {
  if (v == null) return "—";
  return Number(v).toFixed(1) + " km";
}
function fmt_tempo(v) {
  if (v == null) return "—";
  const m = Math.round(v);
  if (m >= 60) return `${Math.floor(m/60)}h ${m%60}min`;
  return `${m} min`;
}
function scoreColor(score) {
  if (score == null) return "none";
  if (score >= 75) return "excellent";
  if (score >= 55) return "good";
  if (score >= 35) return "regular";
  return "low";
}
function badgeClass(badge) {
  if (!badge) return "badge-sem";
  if (badge === "Excelente") return "badge-Excelente";
  if (badge === "Bom") return "badge-Bom";
  if (badge === "Regular") return "badge-Regular";
  if (badge === "Abaixo da média") return "badge-abaixo";
  return "badge-sem";
}
function showMsg(el, text, type = "info") {
  el.textContent = text;
  el.className = `msg ${type}`;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 5000);
}

function parseLinhas(im) {
  if (!im.linhas_onibus) return null;
  try {
    const d = JSON.parse(im.linhas_onibus);
    if (d && (d.diretas || d.baldeacao)) return d;
  } catch(e) {}
  // Fallback: string legada
  return { diretas: [], baldeacao: im.linhas_onibus.split(", ") };
}

function renderLinhasCard(im) {
  const l = parseLinhas(im);
  if (!l) return `<div class="dist-row" style="font-size:.75rem;color:#94a3b8">🚏 Linhas OSM: não mapeado</div>`;
  const parts = [];
  if (l.diretas && l.diretas.length)
    parts.push(`<span title="Direto ao centro">✅ ${l.diretas.join(", ")}</span>`);
  if (l.baldeacao && l.baldeacao.length)
    parts.push(`<span title="Provável baldeação">🔄 ${l.baldeacao.join(", ")}</span>`);
  if (!parts.length) return "";
  return `<div class="dist-row">🚏 <span class="linhas-pill">${parts.join(" &nbsp;")}</span></div>`;
}

function renderLinhasDetalhe(im) {
  const l = parseLinhas(im);
  const nota = `<div style="font-size:.72rem;color:var(--text-muted);margin-top:6px">
    ⚠️ Baseado em dados do OpenStreetMap — cobertura parcial. Pode haver mais linhas.
  </div>`;

  if (!l) {
    return `<div class="detalhe-item" style="grid-column:1/-1">
      <div class="di-label">🚏 Linhas de ônibus próximas</div>
      <div style="font-size:.82rem;color:var(--text-muted);margin-top:4px">
        Não encontrado no OpenStreetMap para esta área.
      </div>
      ${nota}
    </div>`;
  }

  let html = `<div class="detalhe-item" style="grid-column:1/-1">
    <div class="di-label">🚏 Linhas de ônibus próximas (~1km)</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">`;
  (l.diretas || []).forEach(ref => {
    html += `<span class="linha-tag linha-direta" title="Direto ao centro">✅ ${ref}</span>`;
  });
  (l.baldeacao || []).forEach(ref => {
    html += `<span class="linha-tag linha-baldeacao" title="Provável baldeação">🔄 ${ref}</span>`;
  });
  html += `</div>
    <div style="font-size:.72rem;color:var(--text-muted);margin-top:4px">
      ✅ direto ao centro &nbsp;·&nbsp; 🔄 provável baldeação
    </div>
    ${nota}
  </div>`;
  return html;
}

function parseImagens(im) {
  if (im.imagens_json) {
    try { return JSON.parse(im.imagens_json).map(proxyImg); } catch(e) {}
  }
  return im.imagem_url ? [proxyImg(im.imagem_url)] : [];
}

function proxyImg(url) {
  if (!url) return url;
  if (
    url.includes("resizedimgs.zapimoveis.com.br") ||
    url.includes("resizedimgs.vivareal.com") ||
    url.includes("quintoandar.com.br/img/")
  ) {
    return `/img-proxy?url=${encodeURIComponent(url)}`;
  }
  return url;
}

// ── Carrossel ────────────────────────────────────────────────────────────────

function criarCarrossel(imgs, rank, altura = 180) {
  if (!imgs.length) {
    return `
      <div class="imovel-img-wrap" style="height:${altura}px">
        <div class="imovel-img-placeholder">🏠</div>
        ${rank != null ? `<span class="imovel-rank">#${rank}</span>` : ""}
      </div>`;
  }

  const id = "car_" + Math.random().toString(36).slice(2, 8);
  const slides = imgs.map((url, i) => `
    <div class="carousel-slide ${i === 0 ? "active" : ""}">
      <img src="${url}" alt="Foto ${i+1}"
           onerror="this.parentElement.style.display='none'" />
    </div>`).join("");

  const dots = imgs.length > 1
    ? `<div class="carousel-dots">
        ${imgs.map((_, i) => `<span class="carousel-dot ${i===0?'active':''}" data-idx="${i}"></span>`).join("")}
       </div>`
    : "";

  const arrows = imgs.length > 1
    ? `<button class="carousel-btn carousel-prev" aria-label="Anterior">&#8249;</button>
       <button class="carousel-btn carousel-next" aria-label="Próxima">&#8250;</button>`
    : "";

  return `
    <div class="imovel-img-wrap carousel" id="${id}" style="height:${altura}px" data-idx="0" data-total="${imgs.length}">
      <div class="carousel-track">${slides}</div>
      ${arrows}
      ${dots}
      ${rank != null ? `<span class="imovel-rank">#${rank}</span>` : ""}
    </div>`;
}

function initCarrossel(wrap) {
  if (!wrap || !wrap.classList.contains("carousel")) return;
  const total = Number(wrap.dataset.total);
  if (total <= 1) return;

  function goTo(idx) {
    const cur = Number(wrap.dataset.idx);
    const slides = wrap.querySelectorAll(".carousel-slide");
    const dots   = wrap.querySelectorAll(".carousel-dot");
    slides[cur].classList.remove("active");
    dots[cur] && dots[cur].classList.remove("active");
    wrap.dataset.idx = idx;
    slides[idx].classList.add("active");
    dots[idx] && dots[idx].classList.add("active");
  }

  wrap.querySelector(".carousel-prev")?.addEventListener("click", e => {
    e.stopPropagation();
    const cur = Number(wrap.dataset.idx);
    goTo((cur - 1 + total) % total);
  });
  wrap.querySelector(".carousel-next")?.addEventListener("click", e => {
    e.stopPropagation();
    goTo((Number(wrap.dataset.idx) + 1) % total);
  });
  wrap.querySelectorAll(".carousel-dot").forEach(dot => {
    dot.addEventListener("click", e => {
      e.stopPropagation();
      goTo(Number(dot.dataset.idx));
    });
  });
}

// ── Carregar imóveis ─────────────────────────────────────────────────────────

async function carregarImoveis() {
  const loading = $("#loadingLista");
  const empty   = $("#emptyState");
  const lista   = $("#listaImoveis");

  loading.classList.remove("hidden");
  lista.innerHTML = "";
  empty.classList.add("hidden");

  try {
    const res = await fetch(`${API}/api/imoveis`);
    todosImoveis = await res.json();
    renderLista();
  } catch (e) {
    console.error(e);
  } finally {
    loading.classList.add("hidden");
  }
}

function renderLista() {
  const lista  = $("#listaImoveis");
  const empty  = $("#emptyState");
  const filtro = $("#filtroStatus").value;

  const filtrados = filtro
    ? todosImoveis.filter(im => im.status === filtro)
    : todosImoveis;

  $("#totalCount").textContent = filtrados.length;
  lista.innerHTML = "";

  if (!filtrados.length) { empty.classList.remove("hidden"); return; }
  empty.classList.add("hidden");

  filtrados.forEach((im, idx) => {
    const card = criarCard(im, idx + 1);
    lista.appendChild(card);
    initCarrossel(card.querySelector(".carousel"));
  });

  // Polling se houver processando
  const processando = todosImoveis.some(im => im.status === "processando");
  if (processando && !pollingTimer) {
    pollingTimer = setInterval(async () => {
      try {
        const res   = await fetch(`${API}/api/imoveis`);
        const novos = await res.json();
        todosImoveis = novos;
        renderLista();
        if (!novos.some(im => im.status === "processando")) {
          clearInterval(pollingTimer);
          pollingTimer = null;
        }
      } catch (e) {
        console.error("Polling erro:", e);
      }
    }, 3000);
  } else if (!processando && pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

function disponivelBadge(disponivel) {
  // disponivel: 1 = ativo, 0 = indisponível, null = desconhecido
  if (disponivel === 0) return `<span class="disponivel-badge disponivel-nao">🔴 Indisponível</span>`;
  if (disponivel === 1) return `<span class="disponivel-badge disponivel-sim">🟢 Ativo</span>`;
  return "";
}

const ORIGEM_ICON = {
  "ZAP Imóveis":  { icon: "🏢", cls: "origem-zap" },
  "VivaReal":     { icon: "🔵", cls: "origem-vivareal" },
  "QuintoAndar":  { icon: "🟠", cls: "origem-quintoandar" },
  "OLX":          { icon: "🟣", cls: "origem-olx" },
};

function origemBadge(origem) {
  if (!origem) return "";
  const meta = ORIGEM_ICON[origem] || { icon: "🌐", cls: "origem-outro" };
  return `<span class="origem-badge ${meta.cls}">${meta.icon} ${origem}</span>`;
}

function criarCard(im, rank) {
  const card  = document.createElement("div");
  card.className = "imovel-card" + (im.disponivel === 0 ? " indisponivel" : "");
  card.dataset.id = im.id;

  const score = im.score != null ? im.score.toFixed(1) : null;
  const cor   = scoreColor(im.score);
  const imgs  = parseImagens(im);

  card.innerHTML = `
    ${criarCarrossel(imgs, rank, 180)}

    <div class="imovel-body">
      <div class="imovel-titulo">${im.titulo || "Imóvel sem título"}</div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <div class="imovel-preco">${fmt_preco(im.preco)}</div>
        ${disponivelBadge(im.disponivel)}
        ${origemBadge(im.origem)}
      </div>

      <div class="imovel-stats">
        ${im.area_m2   ? `<span class="stat-pill">📐 ${fmt_num(im.area_m2)} m²</span>` : ""}
        ${im.quartos   ? `<span class="stat-pill">🛏 ${im.quartos} quarto${im.quartos>1?"s":""}</span>` : ""}
        ${im.banheiros ? `<span class="stat-pill">🚿 ${im.banheiros} banheiro${im.banheiros>1?"s":""}</span>` : ""}
        ${im.vagas     ? `<span class="stat-pill">🚗 ${im.vagas} vaga${im.vagas>1?"s":""}</span>` : ""}
      </div>

      <div class="imovel-distancias">
        ${im.dist_centro_carro_km  != null ? `<div class="dist-row">🚗 Centro BH: ${fmt_dist(im.dist_centro_carro_km)} · ${fmt_tempo(im.tempo_centro_carro_min)}</div>` : ""}
        ${im.dist_centro_onibus_km != null ? `<div class="dist-row">🚌 Ônibus: ~${fmt_tempo(im.tempo_centro_onibus_min)}</div>` : ""}
        ${renderLinhasCard(im)}
        ${im.dist_supermercado_km  != null ? `<div class="dist-row">🛒 Supermercado: ${fmt_dist(im.dist_supermercado_km)}</div>` : ""}
      </div>

      <span class="status-badge status-${im.status}">
        ${{ ok:"✅ Processado", processando:"⏳ Processando...", erro:"❌ Erro",
            sem_coordenadas:"📍 Sem localização", pendente:"⏸ Pendente" }[im.status] || im.status}
      </span>
    </div>

    <div class="imovel-footer">
      <div class="score-wrap">
        <div>
          <div class="score-num">${score ?? "—"}</div>
          <div class="score-label">/ 100</div>
        </div>
        <div style="flex:1">
          <div class="score-bar-wrap">
            <div class="score-bar ${cor}" style="width:${score ?? 0}%"></div>
          </div>
          <span class="badge-score ${badgeClass(im.badge)}">${im.badge || "sem dados"}</span>
        </div>
      </div>
      <div class="card-actions">
        <button class="btn-icon" title="Ver detalhes"  data-action="detalhe"     data-id="${im.id}">🔍</button>
        <button class="btn-icon" title="Reprocessar"   data-action="reprocessar" data-id="${im.id}">🔄</button>
        <button class="btn-icon danger" title="Remover" data-action="remover"    data-id="${im.id}">🗑</button>
      </div>
    </div>`;

  card.addEventListener("click", e => {
    if (e.target.closest("[data-action]") || e.target.closest(".carousel-btn") || e.target.closest(".carousel-dot")) return;
    abrirDetalhe(im.id);
  });
  card.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", async e => {
      e.stopPropagation();
      const { action, id } = btn.dataset;
      if (action === "detalhe")     abrirDetalhe(Number(id));
      if (action === "reprocessar") await reprocessar(Number(id));
      if (action === "remover")     await remover(Number(id));
    });
  });

  return card;
}

// ── Adicionar imóvel ─────────────────────────────────────────────────────────

async function adicionarImovel() {
  const input = $("#inputUrl");
  const msg   = $("#addMsg");
  const url   = input.value.trim();
  if (!url) { showMsg(msg, "Por favor, cole um link válido.", "error"); return; }

  const btn = $("#btnAdicionar");
  btn.disabled = true; btn.textContent = "Adicionando...";

  try {
    const res  = await fetch(`${API}/api/imoveis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) { showMsg(msg, data.erro || "Erro ao adicionar.", "error"); return; }
    showMsg(msg, "Imóvel adicionado! Processando em segundo plano...", "success");
    input.value = "";
    await carregarImoveis();
  } catch (e) {
    showMsg(msg, "Erro de conexão.", "error");
  } finally {
    btn.disabled = false; btn.textContent = "Adicionar";
  }
}

async function reprocessar(id) {
  await fetch(`${API}/api/imoveis/${id}/reprocessar`, { method: "POST" });
  await carregarImoveis();
}
async function remover(id) {
  if (!confirm("Remover este imóvel da lista?")) return;
  await fetch(`${API}/api/imoveis/${id}`, { method: "DELETE" });
  await carregarImoveis();
}

// ── Modal Detalhe ────────────────────────────────────────────────────────────

async function abrirDetalhe(id) {
  const modal   = $("#modalDetalhe");
  const content = $("#detalheContent");
  const title   = $("#detalheTitle");

  content.innerHTML = `<div class="detalhe-wrap"><div class="spinner"></div></div>`;
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`${API}/api/imoveis/${id}`);
    const im  = await res.json();
    title.textContent = im.titulo || "Detalhes do Imóvel";

    const score = im.score != null ? im.score.toFixed(1) : "—";
    const cor   = scoreColor(im.score);
    const imgs  = parseImagens(im);

    content.innerHTML = `
      <div class="detalhe-wrap">
        ${criarCarrossel(imgs, null, 260)}

        <div class="detalhe-section">
          <h4>Identificação</h4>
          <div class="detalhe-grid">
            <div class="detalhe-item"><div class="di-label">Preço</div><div class="di-val">${fmt_preco(im.preco)}</div></div>
            <div class="detalhe-item"><div class="di-label">Área</div><div class="di-val">${im.area_m2 ? fmt_num(im.area_m2)+" m²" : "—"}</div></div>
            <div class="detalhe-item"><div class="di-label">Quartos</div><div class="di-val">${im.quartos ?? "—"}</div></div>
            <div class="detalhe-item"><div class="di-label">Banheiros</div><div class="di-val">${im.banheiros ?? "—"}</div></div>
            <div class="detalhe-item"><div class="di-label">Vagas</div><div class="di-val">${im.vagas ?? "—"}</div></div>
            <div class="detalhe-item"><div class="di-label">Status</div><div class="di-val"><span class="status-badge status-${im.status}">${im.status}</span></div></div>
            <div class="detalhe-item"><div class="di-label">Disponível</div><div class="di-val">${disponivelBadge(im.disponivel) || "—"}</div></div>
            <div class="detalhe-item"><div class="di-label">Origem</div><div class="di-val">${origemBadge(im.origem) || "—"}</div></div>
          </div>
        </div>

        <div class="detalhe-section">
          <h4>Localização</h4>
          <div class="detalhe-grid">
            <div class="detalhe-item" style="grid-column:1/-1">
              <div class="di-label">Endereço</div>
              <div class="di-val" style="font-size:.9rem">${im.endereco || im.bairro || "—"}</div>
            </div>
            <div class="detalhe-item"><div class="di-label">🛒 Supermercado</div><div class="di-val">${fmt_dist(im.dist_supermercado_km)}</div></div>
            <div class="detalhe-item"><div class="di-label">🚗 Centro (carro)</div><div class="di-val">${fmt_dist(im.dist_centro_carro_km)}</div></div>
            <div class="detalhe-item"><div class="di-label">⏱ Tempo carro</div><div class="di-val">${fmt_tempo(im.tempo_centro_carro_min)}</div></div>
            <div class="detalhe-item"><div class="di-label">🚌 Tempo ônibus</div><div class="di-val">${fmt_tempo(im.tempo_centro_onibus_min)}</div></div>
            ${renderLinhasDetalhe(im)}
          </div>
        </div>

        <div class="detalhe-section">
          <h4>Score de Ranking</h4>
          <div style="display:flex;align-items:center;gap:16px;padding:12px;background:var(--bg);border-radius:8px">
            <div style="font-size:2.5rem;font-weight:800;color:var(--text)">${score}</div>
            <div style="flex:1">
              <div class="score-bar-wrap" style="height:10px;margin-bottom:6px">
                <div class="score-bar ${cor}" style="width:${im.score ?? 0}%"></div>
              </div>
              <span class="badge-score ${badgeClass(im.badge)}">${im.badge || "sem dados"}</span>
            </div>
          </div>
        </div>

        <a class="detalhe-link" href="${im.url}" target="_blank" rel="noopener">🔗 Ver anúncio original</a>
      </div>`;

    // Inicializa carrossel do modal
    initCarrossel(content.querySelector(".carousel"));

  } catch (e) {
    content.innerHTML = `<div class="detalhe-wrap"><p>Erro ao carregar detalhes.</p></div>`;
  }
}

// ── Modal Pesos ──────────────────────────────────────────────────────────────

const PESOS_META = [
  { key: "peso_preco",              label: "💰 Preço",               desc: "Menor preço = melhor" },
  { key: "peso_area",               label: "📐 Área (m²)",           desc: "Maior área = melhor" },
  { key: "peso_quartos",            label: "🛏 Quartos",             desc: "Mais quartos = melhor" },
  { key: "peso_banheiros",          label: "🚿 Banheiros",           desc: "Mais banheiros = melhor" },
  { key: "peso_dist_supermercado",  label: "🛒 Dist. Supermercado",  desc: "Mais perto = melhor" },
  { key: "peso_dist_centro_carro",  label: "🚗 Dist. Centro (carro)",desc: "Mais perto = melhor" },
  { key: "peso_dist_centro_onibus", label: "🚌 Dist. Centro (ônibus)",desc: "Mais perto = melhor" },
];

async function abrirPesos() {
  const res   = await fetch(`${API}/api/pesos`);
  const pesos = await res.json();
  $("#pesosForm").innerHTML = PESOS_META.map(p => `
    <div class="peso-item">
      <label for="p_${p.key}">${p.label}</label>
      <small style="color:var(--text-muted);font-size:.75rem">${p.desc}</small>
      <input type="range" id="p_${p.key}" name="${p.key}" min="0" max="100" step="1"
             value="${pesos[p.key] ?? 10}" oninput="this.nextElementSibling.textContent=this.value" />
      <div class="peso-val">${pesos[p.key] ?? 10}</div>
    </div>`).join("");
  $("#modalPesos").classList.remove("hidden");
}

async function salvarPesos() {
  const msg = $("#pesosMsg");
  const btn = $("#btnSalvarPesos");
  const body = {};
  PESOS_META.forEach(p => {
    const el = $(`#p_${p.key}`);
    body[p.key] = el ? Number(el.value) : 10;
  });
  btn.disabled = true; btn.textContent = "Salvando...";
  try {
    const res = await fetch(`${API}/api/pesos`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      showMsg(msg, "Pesos salvos! Scores recalculados.", "success");
      await carregarImoveis();
      setTimeout(() => $("#modalPesos").classList.add("hidden"), 1500);
    } else {
      const d = await res.json();
      showMsg(msg, d.erro || "Erro ao salvar.", "error");
    }
  } catch (e) {
    showMsg(msg, "Erro de conexão.", "error");
  } finally {
    btn.disabled = false; btn.textContent = "Salvar e Recalcular";
  }
}

// ── Event listeners ──────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  carregarImoveis();

  $("#btnAdicionar").addEventListener("click", adicionarImovel);
  $("#inputUrl").addEventListener("keydown", e => { if (e.key === "Enter") adicionarImovel(); });
  $("#btnAtualizar").addEventListener("click", carregarImoveis);
  $("#filtroStatus").addEventListener("change", renderLista);

  $("#btnPesos").addEventListener("click", abrirPesos);
  $("#btnSalvarPesos").addEventListener("click", salvarPesos);
  $("#btnCancelarPesos").addEventListener("click", () => $("#modalPesos").classList.add("hidden"));
  $("#btnFecharPesos").addEventListener("click",   () => $("#modalPesos").classList.add("hidden"));
  $("#btnFecharDetalhe").addEventListener("click", () => $("#modalDetalhe").classList.add("hidden"));

  $$(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", e => {
      if (e.target === overlay) overlay.classList.add("hidden");
    });
  });
});

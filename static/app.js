/* ── Comparador de Imóveis — Frontend ──────────────────────────────────── */

const API = "";
let todosImoveis = [];
let pollingTimer = null;

// ── Utilitários ──────────────────────────────────────────────────────────────

const $  = (sel, ctx = document) => ctx.querySelector(sel);
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
function scoreBadgeClass(badge) {
  if (!badge) return "badge-ghost";
  if (badge === "Excelente")     return "badge-success";
  if (badge === "Bom")           return "badge-info";
  if (badge === "Regular")       return "badge-warning";
  if (badge === "Abaixo da média") return "badge-error";
  return "badge-ghost";
}
function statusBadgeClass(status) {
  if (status === "ok")               return "badge-success";
  if (status === "processando")      return "badge-warning";
  if (status === "erro")             return "badge-error";
  if (status === "sem_coordenadas")  return "badge-ghost";
  return "badge-ghost";
}
function statusLabel(status) {
  return { ok:"✅ Processado", processando:"⏳ Processando...", erro:"❌ Erro",
           sem_coordenadas:"📍 Sem localização", pendente:"⏸ Pendente" }[status] || status;
}

function showMsg(el, text, type = "info") {
  const cls = { success: "alert alert-success", error: "alert alert-error", info: "alert alert-info" };
  el.className = (cls[type] || "alert") + " text-sm py-2 mt-2";
  el.textContent = text;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 5000);
}

function parseLinhas(im) {
  if (!im.linhas_onibus) return null;
  try {
    const d = JSON.parse(im.linhas_onibus);
    if (d && (d.diretas || d.baldeacao)) return d;
  } catch(e) {}
  return { diretas: [], baldeacao: im.linhas_onibus.split(", ") };
}

function renderLinhasCard(im) {
  const l = parseLinhas(im);
  if (!l) return `<div class="text-xs text-base-content/40">🚏 Linhas OSM: não mapeado</div>`;
  const parts = [];
  if (l.diretas?.length)   parts.push(`<span title="Direto ao centro" class="linha-direta text-xs font-bold px-2 py-0.5 rounded-full">✅ ${l.diretas.join(", ")}</span>`);
  if (l.baldeacao?.length) parts.push(`<span title="Provável baldeação" class="linha-baldeacao text-xs font-bold px-2 py-0.5 rounded-full">🔄 ${l.baldeacao.join(", ")}</span>`);
  if (!parts.length) return "";
  return `<div class="flex items-center gap-1 flex-wrap">🚏 ${parts.join(" ")}</div>`;
}

function renderLinhasDetalhe(im) {
  const l = parseLinhas(im);
  const nota = `<p class="text-xs text-base-content/40 mt-1">⚠️ Dados do OpenStreetMap — cobertura parcial.</p>`;
  if (!l) return `<div class="col-span-full bg-base-200 rounded-lg p-3">
    <div class="text-xs text-base-content/50 font-semibold mb-1">🚏 Linhas de ônibus próximas</div>
    <div class="text-sm text-base-content/40">Não encontrado no OpenStreetMap para esta área.</div>${nota}</div>`;

  return `<div class="col-span-full bg-base-200 rounded-lg p-3">
    <div class="text-xs text-base-content/50 font-semibold mb-2">🚏 Linhas de ônibus próximas (~1km)</div>
    <div class="flex flex-wrap gap-1 mb-1">
      ${(l.diretas||[]).map(r=>`<span class="linha-direta text-xs font-bold px-2 py-0.5 rounded-full" title="Direto ao centro">✅ ${r}</span>`).join("")}
      ${(l.baldeacao||[]).map(r=>`<span class="linha-baldeacao text-xs font-bold px-2 py-0.5 rounded-full" title="Provável baldeação">🔄 ${r}</span>`).join("")}
    </div>
    <p class="text-xs text-base-content/40">✅ direto ao centro · 🔄 provável baldeação</p>
    ${nota}
  </div>`;
}

function parseImagens(im) {
  if (im.imagens_json) {
    try { return JSON.parse(im.imagens_json).map(proxyImg); } catch(e) {}
  }
  return im.imagem_url ? [proxyImg(im.imagem_url)] : [];
}

function proxyImg(url) {
  if (!url) return url;
  if (url.includes("resizedimgs.zapimoveis.com.br") ||
      url.includes("resizedimgs.vivareal.com") ||
      url.includes("quintoandar.com.br/img/")) {
    return `/img-proxy?url=${encodeURIComponent(url)}`;
  }
  return url;
}

// ── Carrossel ────────────────────────────────────────────────────────────────

function criarCarrossel(imgs, rank, altura = 200) {
  const h = `style="height:${altura}px"`;
  if (!imgs.length) {
    return `<div class="carousel-custom bg-base-200 flex items-center justify-center" ${h}>
      <span class="text-5xl text-base-content/20">🏠</span>
      ${rank != null ? `<span class="imovel-rank">#${rank}</span>` : ""}
    </div>`;
  }
  const id = "car_" + Math.random().toString(36).slice(2, 8);
  const slides = imgs.map((url, i) => `
    <div class="carousel-slide ${i===0?"active":""}">
      <img src="${url}" alt="Foto ${i+1}" onerror="this.parentElement.style.display='none'" />
    </div>`).join("");
  const dots = imgs.length > 1
    ? `<div class="carousel-dots">${imgs.map((_,i)=>`<span class="carousel-dot ${i===0?"active":""}" data-idx="${i}"></span>`).join("")}</div>` : "";
  const arrows = imgs.length > 1
    ? `<button class="carousel-btn carousel-prev" aria-label="Anterior">&#8249;</button>
       <button class="carousel-btn carousel-next" aria-label="Próxima">&#8250;</button>` : "";
  return `
    <div class="carousel-custom img-wrap" id="${id}" ${h} data-idx="0" data-total="${imgs.length}">
      <div class="carousel-track">${slides}</div>
      ${arrows}${dots}
      ${rank != null ? `<span class="imovel-rank">#${rank}</span>` : ""}
    </div>`;
}

function initCarrossel(wrap) {
  if (!wrap || !wrap.dataset.total) return;
  const total = Number(wrap.dataset.total);
  if (total <= 1) return;
  function goTo(idx) {
    const cur = Number(wrap.dataset.idx);
    const slides = wrap.querySelectorAll(".carousel-slide");
    const dots   = wrap.querySelectorAll(".carousel-dot");
    slides[cur].classList.remove("active"); dots[cur]?.classList.remove("active");
    wrap.dataset.idx = idx;
    slides[idx].classList.add("active");   dots[idx]?.classList.add("active");
  }
  wrap.querySelector(".carousel-prev")?.addEventListener("click", e => { e.stopPropagation(); goTo((Number(wrap.dataset.idx)-1+total)%total); });
  wrap.querySelector(".carousel-next")?.addEventListener("click", e => { e.stopPropagation(); goTo((Number(wrap.dataset.idx)+1)%total); });
  wrap.querySelectorAll(".carousel-dot").forEach(dot => {
    dot.addEventListener("click", e => { e.stopPropagation(); goTo(Number(dot.dataset.idx)); });
  });
}

// ── Badges ───────────────────────────────────────────────────────────────────

const ORIGEM_META = {
  "ZAP Imóveis": { icon:"🏢", cls:"badge-warning" },
  "VivaReal":    { icon:"🔵", cls:"badge-info" },
  "QuintoAndar": { icon:"🟠", cls:"badge-warning" },
  "OLX":         { icon:"🟣", cls:"badge-secondary" },
};

function origemBadge(origem) {
  if (!origem) return "";
  const m = ORIGEM_META[origem] || { icon:"🌐", cls:"badge-ghost" };
  return `<span class="badge ${m.cls} badge-sm gap-1">${m.icon} ${origem}</span>`;
}
function disponivelBadge(disponivel) {
  if (disponivel === 0) return `<span class="badge badge-error badge-sm">🔴 Indisponível</span>`;
  if (disponivel === 1) return `<span class="badge badge-success badge-sm">🟢 Ativo</span>`;
  return "";
}

// ── Carregar imóveis ──────────────────────────────────────────────────────────

async function carregarImoveis() {
  $("#loadingLista").classList.remove("hidden");
  $("#listaImoveis").innerHTML = "";
  $("#emptyState").classList.add("hidden");
  try {
    const res = await fetch(`${API}/api/imoveis`);
    todosImoveis = await res.json();
    atualizarFiltroBairros();
    renderLista();
  } catch(e) { console.error(e); }
  finally { $("#loadingLista").classList.add("hidden"); }
}

function atualizarFiltroBairros() {
  const sel = $("#filtroBairro");
  const atual = sel.value;
  const bairros = [...new Set(todosImoveis.map(im=>im.bairro).filter(b=>b?.trim()))].sort((a,b)=>a.localeCompare(b,"pt-BR"));
  sel.innerHTML = `<option value="">Todos os bairros</option>` +
    bairros.map(b=>`<option value="${b}"${b===atual?" selected":""}>${b}</option>`).join("");
}

function renderLista() {
  const lista  = $("#listaImoveis");
  const filtro = $("#filtroStatus").value;
  const origem = $("#filtroOrigem").value;
  const bairro = $("#filtroBairro").value;

  const filtrados = todosImoveis.filter(im => {
    if (filtro && im.status !== filtro) return false;
    if (origem && im.origem !== origem) return false;
    if (bairro && im.bairro !== bairro) return false;
    return true;
  });

  $("#totalCount").textContent = filtrados.length;
  lista.innerHTML = "";

  if (!filtrados.length) { $("#emptyState").classList.remove("hidden"); return; }
  $("#emptyState").classList.add("hidden");

  filtrados.forEach((im, idx) => {
    const card = criarCard(im, idx + 1);
    lista.appendChild(card);
    initCarrossel(card.querySelector("[data-total]"));
  });

  // Polling
  const processando = todosImoveis.some(im => im.status === "processando");
  if (processando && !pollingTimer) {
    pollingTimer = setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/imoveis`);
        const novos = await res.json();
        todosImoveis = novos;
        atualizarFiltroBairros();
        renderLista();
        if (!novos.some(im => im.status === "processando")) {
          clearInterval(pollingTimer); pollingTimer = null;
        }
      } catch(e) { console.error("Polling erro:", e); }
    }, 3000);
  } else if (!processando && pollingTimer) {
    clearInterval(pollingTimer); pollingTimer = null;
  }
}

// ── Card ──────────────────────────────────────────────────────────────────────

function criarCard(im, rank) {
  const card = document.createElement("div");
  card.className = "card bg-base-100 border border-base-300 shadow-sm hover:shadow-md transition-shadow cursor-pointer overflow-hidden" +
    (im.disponivel === 0 ? " card-indisponivel" : "");
  card.dataset.id = im.id;

  const score = im.score != null ? im.score.toFixed(1) : null;
  const cor   = scoreColor(im.score);
  const imgs  = parseImagens(im);

  card.innerHTML = `
    ${criarCarrossel(imgs, rank, 200)}
    <div class="card-body p-4 gap-2">
      <p class="font-semibold text-sm titulo-clamp">${im.titulo || "Imóvel sem título"}</p>
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-primary font-bold text-lg">${fmt_preco(im.preco)}</span>
        ${disponivelBadge(im.disponivel)}
        ${origemBadge(im.origem)}
      </div>
      <div class="flex flex-wrap gap-1.5">
        ${im.area_m2   ? `<span class="badge badge-ghost badge-sm">📐 ${fmt_num(im.area_m2)} m²</span>` : ""}
        ${im.quartos   ? `<span class="badge badge-ghost badge-sm">🛏 ${im.quartos} quarto${im.quartos>1?"s":""}</span>` : ""}
        ${im.banheiros ? `<span class="badge badge-ghost badge-sm">🚿 ${im.banheiros} banheiro${im.banheiros>1?"s":""}</span>` : ""}
        ${im.vagas     ? `<span class="badge badge-ghost badge-sm">🚗 ${im.vagas} vaga${im.vagas>1?"s":""}</span>` : ""}
      </div>
      <div class="text-xs text-base-content/60 flex flex-col gap-0.5">
        ${im.dist_centro_carro_km  != null ? `<div>🚗 Centro BH: ${fmt_dist(im.dist_centro_carro_km)} · ${fmt_tempo(im.tempo_centro_carro_min)}</div>` : ""}
        ${im.dist_centro_onibus_km != null ? `<div>🚌 Ônibus: ~${fmt_tempo(im.tempo_centro_onibus_min)}</div>` : ""}
        ${renderLinhasCard(im)}
        ${im.dist_supermercado_km  != null ? `<div>🛒 Supermercado: ${fmt_dist(im.dist_supermercado_km)}</div>` : ""}
      </div>
      <span class="badge ${statusBadgeClass(im.status)} badge-sm self-start">${statusLabel(im.status)}</span>
    </div>
    <div class="px-4 pb-3 border-t border-base-200 pt-3 flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 flex-1 min-w-0">
        <span class="font-black text-xl shrink-0">${score ?? "—"}</span>
        <div class="flex-1 min-w-0">
          <div class="score-bar-track mb-1"><div class="score-bar ${cor}" style="width:${score ?? 0}%"></div></div>
          <span class="badge ${scoreBadgeClass(im.badge)} badge-sm">${im.badge || "sem dados"}</span>
        </div>
      </div>
      <div class="flex gap-1 shrink-0">
        <button class="btn btn-ghost btn-xs" title="Ver detalhes"  data-action="detalhe"     data-id="${im.id}">🔍</button>
        <button class="btn btn-ghost btn-xs" title="Reprocessar"   data-action="reprocessar" data-id="${im.id}">🔄</button>
        <button class="btn btn-ghost btn-xs text-error" title="Remover" data-action="remover" data-id="${im.id}">🗑</button>
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

// ── Adicionar imóvel ──────────────────────────────────────────────────────────

async function adicionarImovel() {
  const input = $("#inputUrl");
  const msg   = $("#addMsg");
  const url   = input.value.trim();
  if (!url) { showMsg(msg, "Por favor, cole um link válido.", "error"); return; }

  const btn = $("#btnAdicionar");
  btn.disabled = true; btn.textContent = "Adicionando...";
  try {
    const res  = await fetch(`${API}/api/imoveis`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) { showMsg(msg, data.erro || "Erro ao adicionar.", "error"); return; }
    showMsg(msg, "Imóvel adicionado! Processando em segundo plano...", "success");
    input.value = "";
    await carregarImoveis();
  } catch(e) { showMsg(msg, "Erro de conexão.", "error"); }
  finally { btn.disabled = false; btn.textContent = "Adicionar"; }
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

// ── Modal Detalhe ─────────────────────────────────────────────────────────────

async function abrirDetalhe(id) {
  const modal   = $("#modalDetalhe");
  const content = $("#detalheContent");
  $("#detalheTitle").textContent = "Carregando...";
  content.innerHTML = `<div class="flex justify-center py-10"><span class="loading loading-spinner loading-lg"></span></div>`;
  modal.showModal();

  try {
    const res = await fetch(`${API}/api/imoveis/${id}`);
    const im  = await res.json();
    $("#detalheTitle").textContent = im.titulo || "Detalhes do Imóvel";

    const score = im.score != null ? im.score.toFixed(1) : "—";
    const cor   = scoreColor(im.score);
    const imgs  = parseImagens(im);

    content.innerHTML = `
      <div class="flex flex-col gap-4">
        ${criarCarrossel(imgs, null, 260)}

        <div>
          <p class="text-xs font-bold uppercase tracking-widest text-base-content/40 mb-2">Identificação</p>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
            ${detalheItem("Preço", fmt_preco(im.preco))}
            ${detalheItem("Área", im.area_m2 ? fmt_num(im.area_m2)+" m²" : "—")}
            ${detalheItem("Quartos", im.quartos ?? "—")}
            ${detalheItem("Banheiros", im.banheiros ?? "—")}
            ${detalheItem("Vagas", im.vagas ?? "—")}
            ${detalheItem("Status", `<span class="badge ${statusBadgeClass(im.status)} badge-sm">${statusLabel(im.status)}</span>`)}
            ${detalheItem("Disponível", disponivelBadge(im.disponivel) || "—")}
            ${detalheItem("Origem", origemBadge(im.origem) || "—")}
          </div>
        </div>

        <div>
          <p class="text-xs font-bold uppercase tracking-widest text-base-content/40 mb-2">Localização</p>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <div class="col-span-full bg-base-200 rounded-lg p-3">
              <div class="text-xs text-base-content/50">Endereço</div>
              <div class="font-semibold text-sm mt-0.5">${im.endereco || im.bairro || "—"}</div>
            </div>
            ${detalheItem("🛒 Supermercado", fmt_dist(im.dist_supermercado_km))}
            ${detalheItem("🚗 Centro (carro)", fmt_dist(im.dist_centro_carro_km))}
            ${detalheItem("⏱ Tempo carro", fmt_tempo(im.tempo_centro_carro_min))}
            ${detalheItem("🚌 Tempo ônibus", fmt_tempo(im.tempo_centro_onibus_min))}
            ${renderLinhasDetalhe(im)}
          </div>
        </div>

        <div>
          <p class="text-xs font-bold uppercase tracking-widest text-base-content/40 mb-2">Score de Ranking</p>
          <div class="bg-base-200 rounded-lg p-4 flex items-center gap-4">
            <span class="text-4xl font-black">${score}</span>
            <div class="flex-1">
              <div class="score-bar-track mb-2" style="height:10px">
                <div class="score-bar ${cor}" style="width:${im.score ?? 0}%"></div>
              </div>
              <span class="badge ${scoreBadgeClass(im.badge)}">${im.badge || "sem dados"}</span>
            </div>
          </div>
        </div>

        <a href="${im.url}" target="_blank" rel="noopener"
           class="btn btn-outline btn-primary btn-sm self-start">🔗 Ver anúncio original</a>
      </div>`;

    initCarrossel(content.querySelector("[data-total]"));
  } catch(e) {
    content.innerHTML = `<p class="text-error py-4">Erro ao carregar detalhes.</p>`;
  }
}

function detalheItem(label, val) {
  return `<div class="bg-base-200 rounded-lg p-3">
    <div class="text-xs text-base-content/50">${label}</div>
    <div class="font-bold text-sm mt-0.5">${val}</div>
  </div>`;
}

// ── Modal Pesos ───────────────────────────────────────────────────────────────

const PESOS_META = [
  { key: "peso_preco",              label: "💰 Preço",                desc: "Menor preço = melhor" },
  { key: "peso_area",               label: "📐 Área (m²)",            desc: "Maior área = melhor" },
  { key: "peso_quartos",            label: "🛏 Quartos",              desc: "Mais quartos = melhor" },
  { key: "peso_banheiros",          label: "🚿 Banheiros",            desc: "Mais banheiros = melhor" },
  { key: "peso_dist_supermercado",  label: "🛒 Dist. Supermercado",   desc: "Mais perto = melhor" },
  { key: "peso_dist_centro_carro",  label: "🚗 Dist. Centro (carro)", desc: "Mais perto = melhor" },
  { key: "peso_dist_centro_onibus", label: "🚌 Dist. Centro (ônibus)",desc: "Mais perto = melhor" },
];

async function abrirPesos() {
  const res   = await fetch(`${API}/api/pesos`);
  const pesos = await res.json();
  $("#pesosForm").innerHTML = PESOS_META.map(p => `
    <div>
      <label class="text-xs font-semibold text-base-content/60">${p.label}</label>
      <p class="text-xs text-base-content/40 mb-1">${p.desc}</p>
      <input type="range" id="p_${p.key}" min="0" max="100" step="1"
             value="${pesos[p.key] ?? 10}" class="range range-primary range-xs w-full"
             oninput="this.nextElementSibling.textContent=this.value" />
      <div class="peso-val">${pesos[p.key] ?? 10}</div>
    </div>`).join("");
  $("#modalPesos").showModal();
}

async function salvarPesos() {
  const msg = $("#pesosMsg");
  const btn = $("#btnSalvarPesos");
  const body = {};
  PESOS_META.forEach(p => { body[p.key] = Number($(`#p_${p.key}`)?.value ?? 10); });
  btn.disabled = true; btn.textContent = "Salvando...";
  try {
    const res = await fetch(`${API}/api/pesos`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      showMsg(msg, "Pesos salvos! Scores recalculados.", "success");
      await carregarImoveis();
      setTimeout(() => $("#modalPesos").close(), 1500);
    } else {
      const d = await res.json();
      showMsg(msg, d.erro || "Erro ao salvar.", "error");
    }
  } catch(e) { showMsg(msg, "Erro de conexão.", "error"); }
  finally { btn.disabled = false; btn.textContent = "Salvar e Recalcular"; }
}

// ── Importar TXT ──────────────────────────────────────────────────────────────

async function importarTxt(file) {
  const text = await file.text();

  // Extrai URLs válidas — uma por linha, ignora linhas vazias e comentários (#)
  const urls = text.split("\n")
    .map(l => l.trim())
    .filter(l => l && !l.startsWith("#") && l.startsWith("http"));

  if (!urls.length) {
    alert("Nenhuma URL válida encontrada no arquivo.");
    return;
  }

  const modal     = $("#modalImport");
  const bar       = $("#importBar");
  const status    = $("#importStatus");
  const pct       = $("#importPct");
  const log       = $("#importLog");
  const desc      = $("#importDesc");
  const btnFechar = $("#btnFecharImport");

  log.innerHTML = "";
  bar.style.width = "0%";
  btnFechar.disabled = true;
  desc.textContent = `Enviando ${urls.length} link${urls.length > 1 ? "s" : ""} para a fila...`;
  status.textContent = "0 / 0";
  pct.textContent = "0%";
  modal.showModal();

  function addLog(msg, type = "normal") {
    const el = document.createElement("div");
    el.className = type === "ok"   ? "text-success" :
                   type === "erro" ? "text-error"   :
                   type === "skip" ? "text-base-content/40" : "";
    el.textContent = msg;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  try {
    // Envia todas as URLs de uma vez — backend salva como 'pendente' sem lançar threads
    const res  = await fetch(`${API}/api/imoveis/importar-lote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }),
    });
    const data = await res.json();

    if (!res.ok) {
      addLog(`❌ Erro: ${data.erro || res.status}`, "erro");
      desc.textContent = "Erro ao importar.";
      btnFechar.disabled = false;
      return;
    }

    // Mostra resultado por URL
    (data.resultados || []).forEach(r => {
      if (r.status === "pendente")
        addLog(`✅ Na fila #${r.id}: ${r.url.slice(0, 70)}`, "ok");
      else if (r.status === "ignorado")
        addLog(`⏭ Ignorado: ${r.url.slice(0, 70)} — ${r.motivo}`, "skip");
      else
        addLog(`❌ Erro: ${r.url.slice(0, 70)} — ${r.motivo}`, "erro");
    });

    const total = data.resultados?.length || 0;
    bar.style.width = "100%";
    status.textContent = `${total} / ${total}`;
    pct.textContent = "100%";
    desc.textContent = `${data.adicionados} link${data.adicionados !== 1 ? "s" : ""} adicionados à fila. O processamento acontece automaticamente.`;

    await carregarImoveis();

  } catch(e) {
    addLog(`❌ Falha de conexão: ${e.message}`, "erro");
    desc.textContent = "Erro de conexão.";
  }

  btnFechar.disabled = false;
}

// ── Event listeners ───────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  carregarImoveis();

  $("#btnAdicionar").addEventListener("click", adicionarImovel);
  $("#inputUrl").addEventListener("keydown", e => { if (e.key === "Enter") adicionarImovel(); });
  $("#btnAtualizar").addEventListener("click", carregarImoveis);
  $("#filtroStatus").addEventListener("change", renderLista);
  $("#filtroOrigem").addEventListener("change", renderLista);
  $("#filtroBairro").addEventListener("change", renderLista);

  // Importar TXT
  $("#inputImportTxt").addEventListener("change", e => {
    const file = e.target.files[0];
    if (file) {
      importarTxt(file);
      e.target.value = ""; // reset para permitir reimportar o mesmo arquivo
    }
  });
  $("#btnFecharImport").addEventListener("click", () => $("#modalImport").close());

  $("#btnPesos").addEventListener("click", abrirPesos);
  $("#btnSalvarPesos").addEventListener("click", salvarPesos);
  $("#btnCancelarPesos").addEventListener("click", () => $("#modalPesos").close());
  $("#btnFecharPesos").addEventListener("click",   () => $("#modalPesos").close());
  $("#btnFecharDetalhe").addEventListener("click", () => $("#modalDetalhe").close());
});

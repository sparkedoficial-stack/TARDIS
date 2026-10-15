/**
 * TARDIS Syntropic Price Sentinel & Deal Oracle - Frontend Engine
 */

const API_BASE = "";

// State
let currentTab = "deals";
let selectedMerchant = "todos";
let selectedCategory = "todos";
let minDiscount = 0;
let onlyGlitches = false;
let onlyFree = false;
let searchQuery = "";
let sortBy = "syntropy_score";
let audioEnabled = true;
let fastCartMode = false;
let autoRefreshEnabled = true;
let lastSyncSeconds = 0;

// Web Audio API Synthesizer for futuristic sci-fi alerts
function playChime(isGlitch = false) {
  if (!audioEnabled) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    if (isGlitch) {
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.3);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } else {
      osc.type = "sine";
      osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
      osc.frequency.setValueAtTime(880, ctx.currentTime + 0.1); // A5
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    }
  } catch (e) {
    console.error("Audio error:", e);
  }
}

// DOM Loaded
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupFilters();
  setupActions();
  loadStats();
  loadDeals();
  loadCoupons();
  loadWatchlist();
  checkDaemonStatus();

  // Live Sync ticker (every second)
  setInterval(() => {
    lastSyncSeconds++;
    const syncText = document.getElementById("sync-text");
    if (syncText) {
      if (lastSyncSeconds < 5) {
        syncText.innerText = "Sincronizado ahora";
      } else {
        syncText.innerText = `Sincronizado hace ${lastSyncSeconds}s`;
      }
    }
  }, 1000);

  // Auto-refresh offers cycle (every 30 seconds)
  setInterval(() => {
    if (autoRefreshEnabled) {
      lastSyncSeconds = 0;
      loadStats();
      if (currentTab === "deals") loadDeals(true);
      else if (currentTab === "glitches") loadGlitches();
    }
  }, 30000);
});

// Tab Navigation
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));

      btn.classList.add("active");
      currentTab = btn.dataset.tab;
      document.getElementById(`tab-${currentTab}`).classList.remove("hidden");

      if (currentTab === "deals") loadDeals();
      else if (currentTab === "glitches") loadGlitches();
      else if (currentTab === "banking") loadCoupons();
      else if (currentTab === "watchlist") loadWatchlist();
    });
  });
}

// Filters & Search
function setupFilters() {
  const searchInput = document.getElementById("search-input");
  let debounceTimeout;
  searchInput.addEventListener("input", (e) => {
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      searchQuery = e.target.value.trim();
      loadDeals();
    }, 400);
  });

  // Merchant Chips
  document.querySelectorAll(".chip-group .chip").forEach(chip => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip-group .chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      selectedMerchant = chip.dataset.merchant;
      loadDeals();
    });
  });

  // Category select
  const catSelect = document.getElementById("category-select");
  if (catSelect) {
    catSelect.addEventListener("change", (e) => {
      selectedCategory = e.target.value;
      loadDeals();
    });
  }

  // Sort select
  const sortSelect = document.getElementById("sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", (e) => {
      sortBy = e.target.value;
      loadDeals();
    });
  }

  // Glitch toggle
  const glitchToggle = document.getElementById("toggle-glitches");
  if (glitchToggle) {
    glitchToggle.addEventListener("change", (e) => {
      onlyGlitches = e.target.checked;
      loadDeals();
    });
  }

  // Free toggle
  const freeToggle = document.getElementById("toggle-free");
  if (freeToggle) {
    freeToggle.addEventListener("change", (e) => {
      onlyFree = e.target.checked;
      loadDeals();
    });
  }
}

// Global actions
function setupActions() {
  // Scan Button
  const btnScan = document.getElementById("btn-scan");
  if (btnScan) {
    btnScan.addEventListener("click", async () => {
      btnScan.disabled = true;
      btnScan.innerHTML = "⚡ Escaneando Red...";
      try {
        const resp = await fetch(`${API_BASE}/api/scan`, { method: "POST" });
        const data = await resp.json();
        playChime(false);
        loadStats();
        loadDeals();
        alert(`✅ Barrido completado: ${data.result.total_collected} ofertas analizadas, ${data.result.new_deals} nuevas, ${data.result.glitches_detected} glitches.`);
      } catch (err) {
        alert("Error al ejecutar escaneo: " + err);
      } finally {
        btnScan.disabled = false;
        btnScan.innerHTML = "🔄 Barrido Rápido";
      }
    });
  }

  // Test Alert Button
  const btnTestAlert = document.getElementById("btn-test-alert");
  if (btnTestAlert) {
    btnTestAlert.addEventListener("click", async () => {
      playChime(true);
      try {
        const resp = await fetch(`${API_BASE}/api/test-alert`, { method: "POST" });
        const res = await resp.json();
        alert(res.message);
      } catch (e) {
        console.error(e);
      }
    });
  }

  // Arbitrage Form
  const btnArbitrage = document.getElementById("btn-run-arbitrage");
  const arbInput = document.getElementById("arbitrage-query");
  if (btnArbitrage && arbInput) {
    btnArbitrage.addEventListener("click", () => runArbitrage(arbInput.value.trim()));
    arbInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") runArbitrage(arbInput.value.trim());
    });
  }

  // Stacking Calculator inputs
  const calcPrice = document.getElementById("calc-price");
  const calcCoupon = document.getElementById("calc-coupon");
  const calcBank = document.getElementById("calc-bank");
  if (calcPrice && calcCoupon && calcBank) {
    const runCalc = () => calculateStacking();
    calcPrice.addEventListener("input", runCalc);
    calcCoupon.addEventListener("input", runCalc);
    calcBank.addEventListener("change", runCalc);
  }

  // Watchlist Add
  const btnAddWatch = document.getElementById("btn-add-watch");
  if (btnAddWatch) {
    btnAddWatch.addEventListener("click", () => addWatchItem());
  }

  // Fast Cart Mode Toggle
  const btnFastCart = document.getElementById("btn-toggle-fast-cart");
  if (btnFastCart) {
    btnFastCart.addEventListener("click", () => {
      fastCartMode = !fastCartMode;
      document.body.classList.toggle("fast-cart-active", fastCartMode);
      if (fastCartMode) {
        btnFastCart.innerHTML = "⚡ 1-Clic Carrito: ON (Activo)";
        btnFastCart.classList.add("btn-primary");
        showToast("⚡ Modo 1-Clic Carrito Activado", "Haz clic en cualquier tarjeta de oferta para abrirla inmediatamente en tu carrito.");
      } else {
        btnFastCart.innerHTML = "⚡ 1-Clic Carrito: OFF";
        btnFastCart.classList.remove("btn-primary");
      }
    });
  }

  // Auto-refresh Toggle
  const toggleAuto = document.getElementById("toggle-autorefresh");
  if (toggleAuto) {
    toggleAuto.addEventListener("change", (e) => {
      autoRefreshEnabled = e.target.checked;
    });
  }
}

// Toast helper
function showToast(title, desc) {
  const toast = document.getElementById("cart-toast");
  const titleEl = document.getElementById("toast-title");
  const descEl = document.getElementById("toast-desc");
  if (toast) {
    if (titleEl) titleEl.innerText = title;
    if (descEl) descEl.innerText = desc;
    toast.classList.remove("hidden");
    setTimeout(() => {
      toast.classList.add("hidden");
    }, 4500);
  }
}

// Cart Jump Action Handler
function triggerCartAction(e, dealId, merchant, targetUrl) {
  if (e) {
    e.stopPropagation();
  }
  playChime(false);

  showToast(`🛒 Abriendo Carrito de ${merchant}`, "Agregando producto y lanzando tu navegador con el carrito o pasarela de pago...");

  // Send dispatch request to backend to ensure browser opens on system screen
  fetch(`${API_BASE}/api/cart/open`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      deal_id: dealId,
      url: targetUrl,
      merchant: merchant
    })
  }).catch(err => console.debug("Desktop cart dispatch note:", err));
}

// Card Click Handler (when Fast Cart Mode is active)
function handleCardClick(e, dealId, merchant, targetUrl) {
  if (!fastCartMode) return;
  // If clicked an <a>, <button>, or input, ignore to let its own handler execute
  if (e.target.closest("a") || e.target.closest("button") || e.target.closest("input")) {
    return;
  }
  triggerCartAction(e, dealId, merchant, targetUrl);
  window.open(`/api/cart/jump/${dealId}`, "_blank");
}

// Load Stats
async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/api/stats`);
    const data = await res.json();
    document.getElementById("stat-total-deals").innerText = data.total_deals.toLocaleString();
    document.getElementById("stat-glitches").innerText = data.active_glitches.toLocaleString();
    document.getElementById("stat-free").innerText = data.active_free.toLocaleString();
    document.getElementById("stat-max-discount").innerText = `${data.max_discount}%`;
  } catch (err) {
    console.error("Stats load error:", err);
  }
}

// Load Deals Grid
async function loadDeals(isAuto = false) {
  const container = document.getElementById("deals-container");
  if (!isAuto) {
    container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 2rem; color: var(--text-muted);">Cargando ofertas con telemetría sintrópica...</div>';
  }

  try {
    const params = new URLSearchParams();
    if (searchQuery) params.append("q", searchQuery);
    if (selectedMerchant !== "todos") params.append("merchant", selectedMerchant);
    if (selectedCategory !== "todos") params.append("category", selectedCategory);
    if (onlyGlitches) params.append("is_glitch", "true");
    if (onlyFree) params.append("is_free", "true");
    if (sortBy) params.append("sort_by", sortBy);
    params.append("limit", "60");

    const resp = await fetch(`${API_BASE}/api/deals?${params.toString()}`);
    const data = await resp.json();

    if (!data.deals || data.deals.length === 0) {
      container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-muted);">No se encontraron ofertas con los filtros actuales.<br>Prueba ejecutar un "Barrido Rápido" para actualizar las fuentes.</div>';
      return;
    }

    container.innerHTML = data.deals.map(renderDealCard).join("");
    lastSyncSeconds = 0;
  } catch (err) {
    if (!isAuto) {
      container.innerHTML = `<div style="grid-column: 1/-1; color: var(--accent-red); text-align: center;">Error al cargar ofertas: ${err}</div>`;
    }
  }
}

// Load Glitches Grid
async function loadGlitches() {
  const container = document.getElementById("glitches-container");
  container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 2rem;">Rastreando errores de precio y liquidaciones masivas...</div>';

  try {
    const resp = await fetch(`${API_BASE}/api/glitches?limit=50`);
    const data = await resp.json();

    if (!data.glitches || data.glitches.length === 0) {
      container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-muted);">No hay errores de precio activos registrados en este momento.</div>';
      return;
    }

    container.innerHTML = data.glitches.map(renderDealCard).join("");
  } catch (err) {
    container.innerHTML = `<div style="color: var(--accent-red);">Error al cargar glitches: ${err}</div>`;
  }
}

// Render Deal Card
function renderDealCard(deal) {
  const borderClass = deal.is_glitch ? "glitch-border" : (deal.is_free ? "free-border" : "");
  const defaultImg = "https://images.unsplash.com/photo-REDACTED_PHONE-4d8ecf77b99f?w=400&auto=format&fit=crop&q=60";
  const imgUrl = deal.image_url || defaultImg;

  let badges = '<span class="badge" style="background: rgba(6, 214, 160, 0.2); border: 1px solid var(--accent-green); color: var(--accent-green); font-weight: 700; font-size: 0.7rem;">🟢 VIGENTE</span>';
  if (deal.is_glitch) badges += ' <span class="badge badge-glitch">🚨 ERROR DE PRECIO</span>';
  if (deal.is_free) badges += ' <span class="badge badge-free">🎁 100% GRATIS</span>';
  if (deal.discount_percent > 0 && !deal.is_free) badges += ` <span class="badge badge-discount">-${deal.discount_percent}%</span>`;
  if (deal.liquidation_phase > 0) badges += ` <span class="badge badge-phase">FASE ${deal.liquidation_phase} (.0${deal.liquidation_phase})</span>`;

  const voucherHtml = deal.voucher_code ? `
    <div class="voucher-row">
      <span>🎟️ Cupón disponible:</span>
      <span class="voucher-code">${escapeHtml(deal.voucher_code)}</span>
    </div>
  ` : "";

  const notesHtml = deal.notes ? `
    <div style="font-size: 0.75rem; color: var(--accent-amber); margin-bottom: 0.5rem;">
      ⚡ ${escapeHtml(deal.notes)}
    </div>
  ` : "";

  const formattedPrice = deal.price <= 0 ? "GRATIS" : `$${deal.price.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const origPriceHtml = deal.original_price > deal.price ? `<span class="original-price">$${deal.original_price.toLocaleString("es-MX", { minimumFractionDigits: 2 })}</span>` : "";
  const jumpUrl = deal.cart_jump_url || `/api/cart/jump/${deal.id}`;

  return `
    <div class="deal-card ${borderClass}" data-deal-id="${escapeHtml(deal.id)}" onclick="handleCardClick(event, '${escapeHtml(deal.id)}', '${escapeHtml(deal.merchant)}', '${escapeHtml(deal.link)}')">
      <div class="deal-header">
        <div class="badges-bar">${badges}</div>
        ${deal.temperature > 0 ? `<div class="temp-tag">🔥 ${Math.round(deal.temperature)}°</div>` : ""}
        <img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(deal.title)}" loading="lazy" onerror="this.src='${defaultImg}'">
      </div>
      <div class="deal-body">
        <div class="deal-merchant">${escapeHtml(deal.merchant)} • ${escapeHtml(deal.category)}</div>
        <div class="deal-title" title="${escapeHtml(deal.title)}">${escapeHtml(deal.title)}</div>
        
        <div class="price-row">
          <span class="current-price">${formattedPrice}</span>
          ${origPriceHtml}
        </div>

        ${voucherHtml}
        ${notesHtml}

        <div class="deal-footer">
          <div class="deal-score">Sintropía: <strong>${Math.round(deal.syntropy_score)}</strong></div>
          <div class="deal-actions-group">
            <a href="${escapeHtml(jumpUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-cart" title="Abrir directo en el carrito de compras de ${escapeHtml(deal.merchant)}" onclick="triggerCartAction(event, '${escapeHtml(deal.id)}', '${escapeHtml(deal.merchant)}', '${escapeHtml(deal.link)}')">
              🛒 Abrir en Carrito
            </a>
            <a href="${escapeHtml(deal.link)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" title="Ver publicación original">
              Ver ↗
            </a>
          </div>
        </div>
      </div>
    </div>
  `;
}

// Arbitrage Comparison
async function runArbitrage(query) {
  if (!query) {
    alert("Ingresa un producto para comparar (ej: 'Nintendo Switch', 'RTX 4060', 'iPad')");
    return;
  }

  const container = document.getElementById("arbitrage-results");
  container.innerHTML = '<div style="text-align: center; padding: 2rem;">Analizando precios y márgenes de arbitraje entre tiendas...</div>';

  try {
    const resp = await fetch(`${API_BASE}/api/arbitrage?q=${encodeURIComponent(query)}`);
    const data = await resp.json();

    if (data.found === 0) {
      container.innerHTML = `<div style="text-align: center; padding: 2rem; color: var(--text-muted);">No se encontraron ofertas activas para "${escapeHtml(query)}". Prueba con otro término.</div>`;
      return;
    }

    let summaryHtml = `
      <div class="arbitrage-summary">
        <div class="summary-box">
          <div class="stat-label">Mejor Precio Encontrado</div>
          <div class="stat-value" style="color: var(--accent-cyan);">$${data.lowest_price.toLocaleString("es-MX", { minimumFractionDigits: 2 })}</div>
          <div style="font-size: 0.8rem; color: var(--text-muted);">En <strong>${escapeHtml(data.best_store)}</strong></div>
        </div>
        <div class="summary-box">
          <div class="stat-label">Precio Máximo Observado</div>
          <div class="stat-value" style="color: var(--text-muted);">$${data.highest_price.toLocaleString("es-MX", { minimumFractionDigits: 2 })}</div>
        </div>
        <div class="summary-box">
          <div class="stat-label">Ahorro Máximo Posible</div>
          <div class="stat-value" style="color: var(--accent-green);">$${data.max_savings.toLocaleString("es-MX", { minimumFractionDigits: 2 })} (${data.savings_pct}%)</div>
        </div>
      </div>
    `;

    let tableRows = data.offers.map((off, idx) => {
      const isBest = idx === 0;
      return `
        <tr style="${isBest ? 'background: rgba(0, 243, 255, 0.08); font-weight: 600;' : ''}">
          <td>${isBest ? '⭐ MEJOR OPCIÓN' : `#${idx + 1}`}</td>
          <td><strong>${escapeHtml(off.merchant)}</strong></td>
          <td>${escapeHtml(off.title.substring(0, 70))}...</td>
          <td style="color: var(--accent-cyan); font-weight: 700;">$${off.price.toLocaleString("es-MX", { minimumFractionDigits: 2 })}</td>
          <td>${off.discount_percent > 0 ? `-${off.discount_percent}%` : 'Normal'}</td>
          <td>
            <div style="display: flex; gap: 0.35rem;">
              <a href="${off.id ? `/api/cart/jump/${escapeHtml(off.id)}` : escapeHtml(off.link)}" target="_blank" class="btn btn-cart" style="padding: 0.25rem 0.55rem; font-size: 0.75rem;" onclick="triggerCartAction(event, '${escapeHtml(off.id || '')}', '${escapeHtml(off.merchant)}', '${escapeHtml(off.link)}')">
                🛒 Carrito
              </a>
              <a href="${escapeHtml(off.link)}" target="_blank" class="btn btn-secondary" style="padding: 0.25rem 0.45rem; font-size: 0.75rem;">
                Ver ↗
              </a>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    let tableHtml = `
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>Ranking</th>
              <th>Tienda</th>
              <th>Publicación</th>
              <th>Precio</th>
              <th>Descuento</th>
              <th>Acción</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
          </tbody>
        </table>
      </div>
    `;

    container.innerHTML = summaryHtml + tableHtml;
  } catch (err) {
    container.innerHTML = `<div style="color: var(--accent-red);">Error en análisis de arbitraje: ${err}</div>`;
  }
}

// Coupons & Stacking
async function loadCoupons() {
  try {
    const resp = await fetch(`${API_BASE}/api/coupons`);
    const data = await resp.json();

    // Render Bank Promos
    const bankGrid = document.getElementById("bank-promos-grid");
    if (bankGrid) {
      bankGrid.innerHTML = data.bank_promos.map(b => `
        <div class="stat-card">
          <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <div class="stat-label" style="font-weight: 700; color: var(--accent-cyan);">${escapeHtml(b.bank)}</div>
            <span class="badge badge-discount">${b.discount_rate} OFF</span>
          </div>
          <p style="font-size: 0.85rem; margin: 0.5rem 0; color: var(--text-main);">${escapeHtml(b.description)}</p>
          <div style="font-size: 0.75rem; color: var(--text-muted);">
            Min. Compra: <strong>$${b.min_purchase.toLocaleString()}</strong> | ${escapeHtml(b.card_type)}
          </div>
        </div>
      `).join("");

      // Populate select
      const calcBank = document.getElementById("calc-bank");
      if (calcBank && calcBank.options.length <= 1) {
        data.bank_promos.forEach(b => {
          const opt = document.createElement("option");
          opt.value = b.bank;
          opt.textContent = `${b.bank} (${b.discount_rate})`;
          calcBank.appendChild(opt);
        });
      }
    }

    // Render Discovered Coupons
    const vouchersList = document.getElementById("discovered-coupons-list");
    if (vouchersList) {
      if (data.discovered_coupons.length === 0) {
        vouchersList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No hay cupones detectados recientemente.</div>';
      } else {
        vouchersList.innerHTML = data.discovered_coupons.map(c => `
          <div style="background: var(--bg-primary); padding: 0.75rem 1rem; border-radius: 6px; border: 1px dashed var(--accent-cyan); margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
            <div>
              <span class="voucher-code" style="font-size: 1rem;">${escapeHtml(c.code)}</span>
              <span style="font-size: 0.8rem; color: var(--text-muted); margin-left: 0.5rem;">(${escapeHtml(c.merchant)})</span>
              <div style="font-size: 0.75rem; color: var(--text-main); margin-top: 0.2rem;">${escapeHtml(c.deal_title)}</div>
            </div>
            <a href="${escapeHtml(c.link)}" target="_blank" class="btn" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;">Usar ↗</a>
          </div>
        `).join("");
      }
    }
  } catch (err) {
    console.error("Error loading coupons:", err);
  }
}

// Calculate Stacking
async function calculateStacking() {
  const price = parseFloat(document.getElementById("calc-price").value) || 0;
  const coupon = parseFloat(document.getElementById("calc-coupon").value) || 0;
  const bank = document.getElementById("calc-bank").value;

  if (price <= 0) return;

  try {
    const resp = await fetch(`${API_BASE}/api/calculator/stacking`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        price: price,
        coupon_percent: coupon,
        bank_name: bank || null
      })
    });
    const res = await resp.json();

    document.getElementById("calc-result-final").innerText = `$${res.final_effective_price.toLocaleString("es-MX", { minimumFractionDigits: 2 })}`;
    document.getElementById("calc-result-savings").innerText = `$${res.total_savings.toLocaleString("es-MX", { minimumFractionDigits: 2 })} (-${res.total_savings_pct}%)`;
    document.getElementById("calc-result-bank-info").innerText = res.qualified_for_bank 
      ? `Aplica bonificación ${res.bank_promo} por -$${res.bank_bonus_amount.toLocaleString("es-MX", { minimumFractionDigits: 2 })}`
      : `No alcanza monto mínimo para bonificación bancaria.`;
  } catch (e) {
    console.error("Calc error:", e);
  }
}

// Watchlist
async function loadWatchlist() {
  const container = document.getElementById("watchlist-items");
  if (!container) return;

  try {
    const resp = await fetch(`${API_BASE}/api/watchlist`);
    const data = await resp.json();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = '<div style="color: var(--text-muted); padding: 1rem;">No tienes alertas en tu Watchlist. Agrega una arriba.</div>';
      return;
    }

    container.innerHTML = data.items.map(item => `
      <div style="background: var(--bg-primary); border: 1px solid var(--border-color); padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <strong style="color: var(--accent-cyan); font-size: 1rem;">${escapeHtml(item.keyword)}</strong>
          <div style="font-size: 0.8rem; color: var(--text-muted);">
            Precio Máx: ${item.max_price ? `$${item.max_price.toLocaleString()}` : "Cualquiera"} | 
            Desc. Mín: ${item.min_discount ? `${item.min_discount}%` : "Cualquiera"} | 
            Categoría: ${escapeHtml(item.category)}
          </div>
        </div>
        <button class="btn btn-danger" onclick="deleteWatchItem(${item.id})">Eliminar</button>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<div style="color: var(--accent-red);">Error al cargar watchlist: ${err}</div>`;
  }
}

async function addWatchItem() {
  const keyword = document.getElementById("watch-keyword").value.trim();
  const maxPrice = parseFloat(document.getElementById("watch-price").value) || null;
  const minDiscount = parseFloat(document.getElementById("watch-discount").value) || null;

  if (!keyword) {
    alert("Ingresa una palabra clave para monitorear.");
    return;
  }

  try {
    const resp = await fetch(`${API_BASE}/api/watchlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keyword: keyword,
        max_price: maxPrice,
        min_discount: minDiscount,
        category: "all"
      })
    });
    if (resp.ok) {
      document.getElementById("watch-keyword").value = "";
      document.getElementById("watch-price").value = "";
      document.getElementById("watch-discount").value = "";
      loadWatchlist();
      loadStats();
    }
  } catch (err) {
    alert("Error al agregar alerta: " + err);
  }
}

async function deleteWatchItem(id) {
  try {
    await fetch(`${API_BASE}/api/watchlist/${id}`, { method: "DELETE" });
    loadWatchlist();
    loadStats();
  } catch (e) {
    console.error(e);
  }
}

// Daemon Status
async function checkDaemonStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/daemon/status`);
    const data = await resp.json();
    const tag = document.getElementById("daemon-status-tag");
    if (tag) {
      if (data.state === "running") {
        tag.innerHTML = `🟢 Centinela Activo (PID: ${data.pid})`;
        tag.style.color = "var(--accent-green)";
      } else {
        tag.innerHTML = `⚪ Centinela en Reposo`;
        tag.style.color = "var(--text-muted)";
      }
    }
  } catch (e) {
    console.error(e);
  }
}

// Utility: escapeHtml
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

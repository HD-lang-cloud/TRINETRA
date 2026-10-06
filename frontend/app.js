/**
 * TRINETRA — Operational Workstation Client Script
 * Handles real-time telemetry, asynchronous CRUD operations, movement ledger,
 * Operational Intelligence, Inventory DNA, and 8D Risk Scoring.
 */

const API_BASE = window.location.origin.includes("5000") || window.location.origin.includes("127.0.0.1")
  ? window.location.origin
  : "http://localhost:5000";

// Global State
let productsCache = [];
let categoriesSet = new Set();
let showLowStockOnly = false;

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// DOM Elements
const connectionBadge = document.getElementById("connection-badge");
const systemStatusText = document.getElementById("system-status-text");
const apiLatencyEl = document.getElementById("api-latency");
const navButtons = document.querySelectorAll(".nav-item");
const viewSections = document.querySelectorAll(".view-section");

const pulseSkusEl = document.getElementById("pulse-skus");
const pulseUnitsEl = document.getElementById("pulse-units");
const pulseCapitalEl = document.getElementById("pulse-capital");
const pulseAlertsEl = document.getElementById("pulse-alerts");

const inventoryTableBody = document.getElementById("inventory-table-body");
const searchInput = document.getElementById("inventory-search");
const categoryFilter = document.getElementById("category-filter");
const btnToggleLowStock = document.getElementById("btn-toggle-low-stock");

// Modals
const productModal = document.getElementById("product-modal");
const btnAddProduct = document.getElementById("btn-add-product");
const btnCloseModal = document.getElementById("btn-close-modal");
const btnCancelModal = document.getElementById("btn-cancel-modal");
const productForm = document.getElementById("product-form");

const movementModal = document.getElementById("movement-modal");
const btnCloseMovementModal = document.getElementById("btn-close-movement-modal");
const btnCancelMovementModal = document.getElementById("btn-cancel-movement-modal");
const movementForm = document.getElementById("movement-form");

const detailModal = document.getElementById("detail-modal");
const btnCloseDetailModal = document.getElementById("btn-close-detail-modal");

const supplierModal = document.getElementById("supplier-modal");
const btnAddSupplier = document.getElementById("btn-add-supplier");
const btnCloseSupplierModal = document.getElementById("btn-close-supplier-modal");
const btnCancelSupplierModal = document.getElementById("btn-cancel-supplier-modal");
const supplierForm = document.getElementById("supplier-form");

// --- 1. Notification Toasts ---
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 200);
  }, 4000);
}

// --- 2. Navigation Routing ---
function initNavigation() {
  navButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetView = btn.getAttribute("data-view");

      navButtons.forEach(b => b.classList.remove("active"));
      viewSections.forEach(v => v.classList.remove("active"));

      btn.classList.add("active");
      const activeSection = document.getElementById(`view-${targetView}`);
      if (activeSection) {
        activeSection.classList.add("active");
      }

      if (targetView === "inventory") {
        fetchProducts();
      } else if (targetView === "replenishment") {
        fetchReplenishmentRecommendations();
        fetchPurchaseOrders();
      } else if (targetView === "command-center") {
        fetchPulse();
        fetchResilienceIndex();
        fetchAttentionQueue();
      } else if (targetView === "audit-ledger") {
        fetchAuditLedger();
      } else if (targetView === "suppliers") {
        fetchSuppliers();
      } else if (targetView === "intelligence") {
        fetchAnomalies();
        fetchRisks();
      } else if (targetView === "resilience-lab") {
        fetchSimulationPresets();
      } else if (targetView === "supply-network") {
        fetchSupplyNetworkView();
      } else if (targetView === "capital") {
        fetchCapitalView();
      } else if (targetView === "decision-ledger") {
        fetchDecisionStudioView();
      } else if (targetView === "system-health") {
        checkHealth();
      }
    });
  });
}

// --- 3. System Observability & Health Polling ---
async function checkHealth() {
  const start = performance.now();
  try {
    const res = await fetch(`${API_BASE}/api/system/health`);
    const latency = Math.round(performance.now() - start);
    apiLatencyEl.textContent = `${latency} ms`;

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const result = await res.json();
    const data = result.data;

    systemStatusText.textContent = data.status.toUpperCase();
    connectionBadge.style.color = "var(--accent-emerald)";
    connectionBadge.style.borderColor = "rgba(16, 185, 129, 0.3)";

    const dbStatus = document.getElementById("health-db-status");
    const dbEngine = document.getElementById("health-db-engine");
    const uptimeEl = document.getElementById("health-uptime");
    const llmMode = document.getElementById("health-llm-mode");

    if (dbStatus) dbStatus.textContent = data.database.connected ? "CONNECTED (OK)" : "ERROR";
    if (dbEngine) dbEngine.textContent = `${data.database.engine} v${data.database.version}`;
    if (uptimeEl) uptimeEl.textContent = `${data.uptime_seconds} seconds`;
    if (llmMode) llmMode.textContent = data.llm_provider.toUpperCase();

    // Trigger detailed observability fetches in parallel
    fetchModelHealth();
    fetchSystemTelemetry();
    fetchCircuitBreaker();
    fetchDemandDrift();

  } catch (err) {
    systemStatusText.textContent = "OFFLINE";
    connectionBadge.style.color = "var(--accent-rose)";
    connectionBadge.style.borderColor = "rgba(244, 63, 94, 0.3)";
    apiLatencyEl.textContent = "Timeout";
  }
}

async function fetchSystemTelemetry() {
  try {
    const res = await fetch(`${API_BASE}/api/system/telemetry`);
    if (!res.ok) return;

    const result = await res.json();
    const d = result.data;

    const elSize = document.getElementById("obs-db-size");
    if (elSize) elSize.textContent = `${d.database.file_size_kb.toFixed(1)} KB`;

    const elRecords = document.getElementById("obs-db-records");
    if (elRecords) elRecords.textContent = `${d.database.total_records.toLocaleString()} total records across tables`;

    const elInteg = document.getElementById("health-db-integrity");
    if (elInteg) elInteg.textContent = d.database.integrity.toUpperCase();

    // Render table distribution grid
    const distGrid = document.getElementById("table-distribution-grid");
    if (distGrid && d.database.table_counts) {
      distGrid.innerHTML = Object.entries(d.database.table_counts).map(([tbl, cnt]) => `
        <div style="background: var(--bg-base); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-color);">
          <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">${tbl}</div>
          <div style="font-size: 0.95rem; font-weight: 700; color: var(--accent-blue);">${cnt.toLocaleString()}</div>
        </div>
      `).join("");
    }
  } catch (err) {
    console.warn("Unable to fetch telemetry:", err);
  }
}

async function fetchCircuitBreaker() {
  try {
    const res = await fetch(`${API_BASE}/api/system/circuit-breaker`);
    if (!res.ok) return;

    const result = await res.json();
    const cb = result.data;

    const elStatus = document.getElementById("obs-circuit-status");
    if (elStatus) {
      elStatus.textContent = cb.circuit_breaker_state;
      elStatus.style.color = cb.is_tripped ? "var(--accent-rose)" : "var(--accent-emerald)";
    }

    const elMode = document.getElementById("obs-circuit-mode");
    if (elMode) elMode.textContent = `Operating Mode: ${cb.mode} (Crisis ratio: ${cb.crisis_ratio})`;
  } catch (err) {
    console.warn("Unable to fetch circuit breaker status:", err);
  }
}

async function fetchDemandDrift() {
  const tbody = document.getElementById("drift-tbody");
  const winSelect = document.getElementById("drift-window-select");
  const windowDays = winSelect ? parseInt(winSelect.value) : 30;

  try {
    const res = await fetch(`${API_BASE}/api/system/drift?window_days=${windowDays}`);
    if (!res.ok) return;

    const result = await res.json();
    const d = result.data;

    const elDriftStatus = document.getElementById("obs-drift-status");
    if (elDriftStatus) {
      elDriftStatus.textContent = d.status;
      elDriftStatus.style.color = d.status === "STABLE" ? "var(--accent-emerald)" : (d.status === "WARNING" ? "var(--accent-amber)" : "var(--accent-rose)");
    }

    const elDriftCount = document.getElementById("obs-drift-count");
    if (elDriftCount) elDriftCount.textContent = `${d.drifted_skus_count} of ${d.monitored_skus_count} SKUs requiring retrain`;

    if (!tbody) return;
    const items = d.drift_details || [];
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">No historical demand streams available for drift tracking.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map(item => {
      let sevBadge = "badge-normal";
      if (item.drift_severity === "CRITICAL") sevBadge = "badge-critical";
      else if (item.drift_severity === "MODERATE") sevBadge = "badge-warning";

      return `
        <tr>
          <td class="num-cell" style="font-weight: 600; color: var(--accent-blue);">${item.sku}</td>
          <td style="font-weight: 500;">${item.product_name}</td>
          <td class="num-cell" style="text-align: right;">${item.baseline_mean.toFixed(1)}</td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">${item.recent_mean.toFixed(1)}</td>
          <td class="num-cell" style="text-align: right; color: ${item.mean_shift_pct > 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'}; font-weight: 600;">
            ${item.mean_shift_pct > 0 ? '+' : ''}${item.mean_shift_pct}%
          </td>
          <td class="num-cell" style="text-align: right; color: var(--text-secondary);">${item.volatility_shift_pct > 0 ? '+' : ''}${item.volatility_shift_pct}%</td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: ${item.drift_score_z >= 2.58 ? 'var(--accent-rose)' : 'var(--text-primary)'};">${item.drift_score_z.toFixed(2)}</td>
          <td><span class="badge ${sevBadge}">${item.drift_severity}</span></td>
          <td>
            ${item.requires_retraining 
              ? `<span style="color: var(--accent-rose); font-weight: 600;">● Retrain Recommended</span>` 
              : `<span style="color: var(--accent-emerald); font-weight: 600;">✓ Calibrated</span>`}
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error: ${err.message}</td></tr>`;
  }
}

async function runSelfHealingReconciliation() {
  const resultsBox = document.getElementById("heal-results-box");
  const elHealStatus = document.getElementById("obs-heal-status");
  const elHealRepairs = document.getElementById("obs-heal-repairs");

  if (resultsBox) {
    resultsBox.innerHTML = `<div style="color: var(--accent-blue);">Auditing stock movements, ledger invariants, PO sums, and database constraints...</div>`;
  }

  try {
    const res = await fetch(`${API_BASE}/api/system/reconcile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_repair: true })
    });
    if (!res.ok) throw new Error("Reconciliation failed");

    const result = await res.json();
    const d = result.data;

    if (elHealStatus) {
      elHealStatus.textContent = d.status === "HEALTHY" ? "HEALTHY (0 ERR)" : "REPAIRED (AUTO-HEALED)";
      elHealStatus.style.color = d.status === "HEALTHY" ? "var(--accent-emerald)" : "var(--accent-amber)";
    }

    if (elHealRepairs) {
      elHealRepairs.textContent = `${d.repairs_applied_count} automated repairs applied`;
    }

    if (!resultsBox) return;

    if (d.discrepancies_detected_count === 0) {
      resultsBox.innerHTML = `
        <div style="color: var(--accent-emerald); font-weight: 600; margin-bottom: 0.25rem;">
          ✓ All 4 Core Database Invariants Verified 100% Invariant Compliant
        </div>
        <div style="color: var(--text-secondary); font-size: 0.8rem;">
          1. Stock movement ledger balances exactly match product on-hand quantities.<br>
          2. Zero negative stock balances found.<br>
          3. Purchase order total values strictly equal item subtotal sums.<br>
          4. All catalogue products map to active warehouse locations.
        </div>
      `;
    } else {
      resultsBox.innerHTML = `
        <div style="color: var(--accent-amber); font-weight: 600; margin-bottom: 0.5rem;">
          ⚠️ Detected ${d.discrepancies_detected_count} Invariant Violations — ${d.repairs_applied_count} Autonomous Repairs Applied
        </div>
        <ul style="margin: 0; padding-left: 1.2rem; color: var(--text-primary);">
          ${d.repairs.map(rep => `<li style="margin-bottom: 0.25rem;">${escapeHtml(rep)}</li>`).join("")}
        </ul>
      `;
    }
  } catch (err) {
    if (resultsBox) resultsBox.innerHTML = `<div style="color: var(--accent-rose);">Reconciliation error: ${err.message}</div>`;
  }
}

async function fetchModelHealth() {
  const modelStatus = document.getElementById("model-health-status");
  const modelPipeline = document.getElementById("model-pipeline-name");
  const modelVersion = document.getElementById("model-version-tag");
  const modelDrift = document.getElementById("model-drift-status");
  const modelPoints = document.getElementById("model-cached-points");
  const championsTbody = document.getElementById("model-champions-tbody");

  if (!championsTbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/forecasts/models/health`);
    if (!res.ok) return;

    const result = await res.json();
    const data = result.data;

    if (modelStatus) {
      modelStatus.textContent = `STATUS: ${data.status}`;
      modelStatus.className = "badge badge-normal";
    }
    if (modelPipeline) modelPipeline.textContent = data.model_pipeline;
    if (modelVersion) modelVersion.textContent = data.model_version;
    if (modelDrift) modelDrift.textContent = `${data.data_drift_status} (CALIBRATED)`;
    if (modelPoints) modelPoints.textContent = `${data.total_cached_forecast_points} points`;

    if (data.active_champions && data.active_champions.length > 0) {
      championsTbody.innerHTML = data.active_champions.map(c => `
        <tr>
          <td style="font-weight: 600;">${c.model_name}</td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: var(--accent-blue);">${c.sku_count} SKUs</td>
          <td class="num-cell" style="text-align: right;">${Number(c.avg_mae).toFixed(2)}</td>
          <td class="num-cell" style="text-align: right;">${Number(c.avg_smape).toFixed(1)}%</td>
        </tr>
      `).join("");
    } else {
      championsTbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No benchmarked models recorded yet. Inspect a SKU drawer to run benchmarks.</td></tr>`;
    }
  } catch (err) {
    console.warn("Unable to fetch model health:", err);
  }
}

// --- 4. Inventory Pulse & Resilience Index ---
async function fetchPulse() {
  try {
    const res = await fetch(`${API_BASE}/api/system/pulse`);
    if (!res.ok) return;

    const result = await res.json();
    const pulse = result.data;

    pulseSkusEl.textContent = pulse.total_skus.toLocaleString();
    pulseUnitsEl.textContent = pulse.total_units.toLocaleString();
    pulseCapitalEl.textContent = `₹${pulse.total_capital_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    pulseAlertsEl.textContent = pulse.low_stock_count;

    if (pulse.low_stock_count > 0) {
      pulseAlertsEl.style.color = "var(--accent-rose)";
    } else {
      pulseAlertsEl.style.color = "var(--accent-emerald)";
    }
  } catch (err) {
    console.warn("Unable to fetch pulse metrics:", err);
  }
}

async function fetchResilienceIndex() {
  try {
    const res = await fetch(`${API_BASE}/api/capital`);
    if (!res.ok) return;

    const result = await res.json();
    const resData = result.data.resilience;

    const scoreEl = document.getElementById("resilience-score-num");
    const badgeEl = document.getElementById("resilience-rating-badge");

    if (scoreEl) scoreEl.textContent = resData.resilience_score;
    if (badgeEl) {
      badgeEl.textContent = resData.rating;
      badgeEl.className = resData.resilience_score >= 70 ? "badge badge-normal" : (resData.resilience_score >= 50 ? "badge badge-warning" : "badge badge-critical");
    }

    const subs = resData.sub_scores;
    if (subs) {
      const dStab = document.getElementById("sub-demand-stability");
      const cSafe = document.getElementById("sub-coverage-safety");
      const sDiv = document.getElementById("sub-supplier-diversification");
      const lRel = document.getElementById("sub-lead-reliability");
      const cFlex = document.getElementById("sub-capital-flexibility");

      if (dStab) dStab.textContent = `${subs.demand_stability}%`;
      if (cSafe) cSafe.textContent = `${subs.coverage_safety}%`;
      if (sDiv) sDiv.textContent = `${subs.supplier_diversification}%`;
      if (lRel) lRel.textContent = `${subs.lead_time_reliability}%`;
      if (cFlex) cFlex.textContent = `${subs.capital_flexibility}%`;
    }
  } catch (err) {
    console.warn("Unable to fetch resilience index:", err);
  }
}

async function fetchAttentionQueue() {
  const tbody = document.getElementById("attention-queue-tbody");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/risks`);
    if (!res.ok) return;

    const result = await res.json();
    const risks = result.data.risks || [];

    // Filter to items needing immediate operator attention (CRITICAL or HIGH)
    const urgentItems = risks.filter(r => r.composite_rating === "CRITICAL" || r.composite_rating === "HIGH");

    if (urgentItems.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--accent-emerald); padding: 1.5rem;">✓ No immediate high-risk exposures detected across monitored catalogue.</td></tr>`;
      return;
    }

    tbody.innerHTML = urgentItems.map(item => {
      const isCritical = item.composite_rating === "CRITICAL";
      const badgeClass = isCritical ? "badge badge-critical" : "badge badge-warning";
      
      // Determine primary vulnerability reason
      let vulnType = "Stockout Exposure";
      if (item.dimensions.dead_stock_risk_pct >= 80) vulnType = "Dead Stagnant Stock";
      else if (item.dimensions.supplier_risk_pct >= 50) vulnType = "Supplier SPOF Collapse";
      else if (item.dimensions.demand_spike_risk_pct >= 60) vulnType = "Severe Demand Surge";

      return `
        <tr>
          <td style="font-weight: 600;">
            <span style="color: var(--accent-blue); font-family: var(--font-mono); font-size: 0.8rem;">${item.sku}</span> ${item.name}
          </td>
          <td><span class="badge" style="background: var(--bg-hover);">${vulnType}</span></td>
          <td><span class="${badgeClass}">${item.composite_rating}</span></td>
          <td class="num-cell" style="text-align: right;">${item.evidence?.stockout?.score >= 70 ? '< 7 days' : '15+ days'}</td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: var(--accent-rose);">₹${item.dimensions.capital_at_risk_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          <td style="text-align: right;">
            <button class="btn btn-sm" onclick="openDetailDrawer(${item.product_id})">Inspect DNA</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Failed to load attention queue: ${err.message}</td></tr>`;
  }
}

// --- 5. Inventory Operations ---
async function fetchProducts(query = "", category = "") {
  try {
    let url = `${API_BASE}/api/products`;
    const params = new URLSearchParams();
    if (query) params.append("q", query);
    if (category) params.append("category", category);
    if (showLowStockOnly) params.append("low_stock", "true");
    if (params.toString()) url += `?${params.toString()}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load products");

    const result = await res.json();
    productsCache = result.data.products || [];

    renderProductsTable(productsCache);
    updateCategoryDropdown(productsCache);
  } catch (err) {
    inventoryTableBody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; color: var(--accent-rose); padding: 2rem;">
          Failed to load inventory: ${err.message}. Is backend running on ${API_BASE}?
        </td>
      </tr>
    `;
  }
}

function renderProductsTable(products) {
  if (!products || products.length === 0) {
    inventoryTableBody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">
          No matching products found in catalogue.
        </td>
      </tr>
    `;
    return;
  }

  inventoryTableBody.innerHTML = products.map(prod => {
    const isLowStock = prod.quantity <= prod.reorder_threshold;
    const totalVal = (prod.quantity * prod.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const statusBadge = isLowStock
      ? `<span class="badge badge-critical">LOW (${prod.quantity}/${prod.reorder_threshold})</span>`
      : `<span class="badge badge-normal">OPTIMAL</span>`;

    return `
      <tr>
        <td class="num-cell" style="font-weight: 600; color: var(--accent-blue);">${prod.sku || `SKU-${prod.id}`}</td>
        <td style="font-weight: 500;">${prod.name}</td>
        <td><span class="badge" style="background: var(--bg-hover); color: var(--text-secondary);">${prod.category}</span></td>
        <td class="num-cell" style="text-align: right; font-weight: 600;">${prod.quantity}</td>
        <td class="num-cell" style="text-align: right;">₹${Number(prod.price).toFixed(2)}</td>
        <td class="num-cell" style="text-align: right;">₹${totalVal}</td>
        <td style="text-align: center;">${statusBadge}</td>
        <td style="text-align: right; white-space: nowrap;">
          <button class="btn btn-sm" onclick="openMovementModal(${prod.id}, '${escapeHtml(prod.name)}', '${escapeHtml(prod.sku)}')">Movement</button>
          <button class="btn btn-sm" onclick="openDetailDrawer(${prod.id})">Details</button>
        </td>
      </tr>
    `;
  }).join("");
}

function updateCategoryDropdown(products) {
  products.forEach(p => {
    if (p.category) categoriesSet.add(p.category);
  });

  const currentSelection = categoryFilter.value;
  categoryFilter.innerHTML = '<option value="">All Categories</option>' + 
    Array.from(categoriesSet).map(cat => 
      `<option value="${cat}" ${cat === currentSelection ? "selected" : ""}>${cat}</option>`
    ).join("");
}

// --- 6. Stock Movement Operations ---
window.openMovementModal = function(productId, productName, sku) {
  document.getElementById("mov-product-id").value = productId;
  document.getElementById("mov-product-display").textContent = `${productName} (${sku})`;
  document.getElementById("mov-qty").value = 1;
  document.getElementById("mov-reason").value = "";
  document.getElementById("mov-ref").value = "";
  movementModal.classList.add("active");
};

function initMovementModal() {
  const close = () => movementModal.classList.remove("active");
  btnCloseMovementModal.addEventListener("click", close);
  btnCancelMovementModal.addEventListener("click", close);

  movementForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const productId = parseInt(document.getElementById("mov-product-id").value, 10);
    const movementType = document.getElementById("mov-type").value;
    const quantity = parseInt(document.getElementById("mov-qty").value, 10);
    const reason = document.getElementById("mov-reason").value.trim();
    const reference = document.getElementById("mov-ref").value.trim();

    if (quantity <= 0) {
      showToast("Movement quantity must be greater than zero.", "error");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/movements`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: productId,
          movement_type: movementType,
          quantity: quantity,
          reason: reason,
          reference_id: reference || undefined
        })
      });

      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.error?.message || result.message || "Movement failed");
      }

      showToast(`Stock updated: new balance is ${result.data.product.quantity} units.`, "success");
      close();
      fetchProducts();
      fetchPulse();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

// --- 7. Product Detail & DNA Drawer ---
window.openDetailDrawer = async function(productId) {
  try {
    const [detailRes, dnaRes, riskRes] = await Promise.all([
      fetch(`${API_BASE}/api/products/${productId}`),
      fetch(`${API_BASE}/api/dna/${productId}`),
      fetch(`${API_BASE}/api/risks/${productId}`)
    ]);

    if (!detailRes.ok) throw new Error("Failed to fetch product details");

    const detailData = (await detailRes.json()).data;
    const dnaData = dnaRes.ok ? (await dnaRes.json()).data : null;
    const riskData = riskRes.ok ? (await riskRes.json()).data : null;

    const prod = detailData.product;

    document.getElementById("detail-product-name").textContent = prod.name;
    document.getElementById("detail-product-sku").textContent = prod.sku;
    document.getElementById("detail-qty").textContent = prod.quantity;
    document.getElementById("detail-price").textContent = `₹${Number(prod.price).toFixed(2)}`;
    
    // Fetch Replenishment Parameters (ROP, SS, EOQ)
    const elRop = document.getElementById("detail-rop");
    const elSs = document.getElementById("detail-ss");
    const elEoq = document.getElementById("detail-eoq");
    if (elRop) elRop.textContent = "...";
    if (elSs) elSs.textContent = "...";
    if (elEoq) elEoq.textContent = "...";

    fetch(`${API_BASE}/api/replenishment/rop/${productId}`)
      .then(r => r.json())
      .then(res => {
        if (res.data) {
          if (elRop) elRop.textContent = `${res.data.reorder_point}`;
          if (elSs) elSs.textContent = `${res.data.safety_stock}`;
        }
      })
      .catch(() => {});

    fetch(`${API_BASE}/api/replenishment/eoq/${productId}`)
      .then(r => r.json())
      .then(res => {
        if (res.data) {
          if (elEoq) elEoq.textContent = `${res.data.optimized_order_quantity}`;
        }
      })
      .catch(() => {});

    const isLow = prod.quantity <= prod.reorder_threshold;
    document.getElementById("detail-status").innerHTML = isLow
      ? `<span class="badge badge-critical">LOW STOCK</span>`
      : `<span class="badge badge-normal">OPTIMAL</span>`;

    // Stock bar ratio
    const target = prod.target_stock_level || 50;
    const pct = Math.min(Math.round((prod.quantity / target) * 100), 100);
    document.getElementById("detail-stock-ratio").textContent = `${prod.quantity} / ${target} units (${pct}%)`;
    const bar = document.getElementById("detail-stock-bar");
    bar.style.width = `${pct}%`;
    bar.style.backgroundColor = isLow ? "var(--accent-rose)" : "var(--accent-emerald)";

    // Suppliers table
    const suppContainer = document.getElementById("detail-suppliers-container");
    if (detailData.suppliers && detailData.suppliers.length > 0) {
      suppContainer.innerHTML = `
        <table>
          <thead>
            <tr><th>Supplier</th><th>Unit Cost</th><th>MOQ</th><th>Lead Time</th><th>Reliability</th></tr>
          </thead>
          <tbody>
            ${detailData.suppliers.map(s => `
              <tr>
                <td>${s.supplier_name} ${s.is_primary ? '<span class="badge badge-normal">PRIMARY</span>' : ''}</td>
                <td class="num-cell">₹${s.unit_cost.toFixed(2)}</td>
                <td class="num-cell">${s.moq}</td>
                <td class="num-cell">${s.supplier_lead_time_days} days</td>
                <td class="num-cell">${Math.round(s.reliability_score * 100)}%</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    } else {
      suppContainer.innerHTML = `<p style="color: var(--text-muted);">No suppliers mapped to this SKU yet.</p>`;
    }

    // Movements table
    const movTbody = document.getElementById("detail-movements-tbody");
    if (detailData.recent_movements && detailData.recent_movements.length > 0) {
      movTbody.innerHTML = detailData.recent_movements.map(m => `
        <tr>
          <td class="num-cell" style="font-size: 0.75rem; color: var(--text-secondary);">${m.created_at}</td>
          <td><span class="badge" style="background: var(--bg-hover);">${m.movement_type}</span></td>
          <td class="num-cell" style="text-align: right; color: ${m.quantity_change >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">
            ${m.quantity_change > 0 ? `+${m.quantity_change}` : m.quantity_change}
          </td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">${m.balance_after}</td>
          <td style="font-size: 0.8rem; color: var(--text-secondary);">${m.reason}</td>
        </tr>
      `).join("");
    } else {
      movTbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No recorded movements.</td></tr>`;
    }

    // Load Phase 4 Multi-Model Demand Forecast
    activeDetailProductId = productId;
    loadSkuForecast(productId);

    detailModal.classList.add("active");
  } catch (err) {
    showToast(err.message, "error");
  }
};

let activeDetailProductId = null;

async function loadSkuForecast(productId, forceRefresh = false) {
  const champBadge = document.getElementById("detail-champion-badge");
  const suffDiv = document.getElementById("detail-forecast-sufficiency");
  const fcTbody = document.getElementById("detail-forecast-tbody");
  const bmTbody = document.getElementById("detail-benchmark-tbody");

  if (!fcTbody || !bmTbody) return;

  if (champBadge) champBadge.textContent = "BENCHMARKING...";
  if (suffDiv) suffDiv.textContent = "Evaluating data sufficiency and candidate models...";
  fcTbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Computing 14-day forecasts...</td></tr>`;
  bmTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Benchmarking candidate models...</td></tr>`;

  try {
    const url = `${API_BASE}/api/forecasts/${productId}${forceRefresh ? '?refresh=true' : ''}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load forecast");

    const result = await res.json();
    const data = result.data;

    // Champion Badge & Sufficiency
    if (champBadge) {
      champBadge.textContent = `CHAMPION: ${data.champion_model || 'MOVING AVERAGE'}`;
      champBadge.className = "badge badge-primary";
    }

    if (suffDiv && data.data_sufficiency) {
      const suff = data.data_sufficiency;
      const isSuff = suff.status === "SUFFICIENT_DATA";
      suffDiv.innerHTML = `
        <span style="color: ${isSuff ? 'var(--accent-emerald)' : 'var(--accent-amber)'}; font-weight: 600;">
          ${suff.status} (${suff.observations} days recorded, ${suff.confidence_pct}% confidence)
        </span>
        — <span>${suff.explanation}</span>
      `;
    }

    // Render 14-Day Forecast Predictions
    if (data.predictions && data.predictions.length > 0) {
      fcTbody.innerHTML = data.predictions.map(p => {
        const int80 = p.interval_80 ? `[${p.interval_80.lower} – ${p.interval_80.upper}]` : '—';
        const int95 = p.interval_95 ? `[${p.interval_95.lower} – ${p.interval_95.upper}]` : (int80 || '—');

        return `
          <tr>
            <td class="num-cell" style="font-weight: 500;">${p.date}</td>
            <td class="num-cell" style="text-align: right; font-weight: 700; color: var(--accent-blue);">
              ${Number(p.predicted_demand).toFixed(1)} units
            </td>
            <td class="num-cell" style="text-align: right; color: var(--text-secondary); font-size: 0.8rem;">
              ${int80}
            </td>
            <td class="num-cell" style="text-align: right; color: var(--text-muted); font-size: 0.8rem;">
              ${int95}
            </td>
          </tr>
        `;
      }).join("");
    } else {
      fcTbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No predictions generated.</td></tr>`;
    }

    // Render Benchmark Comparison Table
    if (data.benchmark_results && data.benchmark_results.length > 0) {
      bmTbody.innerHTML = data.benchmark_results.map(b => {
        const isSelected = b.selected || b.status === "CHAMPION" || b.status === "FALLBACK_CHAMPION";
        const badgeClass = isSelected ? "badge badge-primary" : "badge badge-normal";

        return `
          <tr style="${isSelected ? 'background: rgba(37, 99, 235, 0.08); font-weight: 500;' : ''}">
            <td style="font-weight: 600;">
              ${b.model_name} ${isSelected ? '🏆' : ''}
            </td>
            <td><span class="badge" style="background: var(--bg-hover); font-size: 0.7rem;">${b.model_type || 'MODEL'}</span></td>
            <td class="num-cell" style="text-align: right; font-weight: 600;">${b.mae !== undefined ? b.mae.toFixed(2) : '—'}</td>
            <td class="num-cell" style="text-align: right;">${b.rmse !== undefined ? b.rmse.toFixed(2) : '—'}</td>
            <td class="num-cell" style="text-align: right;">${b.smape !== undefined ? `${b.smape.toFixed(1)}%` : '—'}</td>
            <td class="num-cell" style="text-align: right; color: ${b.bias > 0 ? 'var(--accent-amber)' : 'inherit'};">
              ${b.bias !== undefined ? (b.bias > 0 ? `+${b.bias.toFixed(2)}` : b.bias.toFixed(2)) : '—'}
            </td>
            <td style="text-align: center;">
              <span class="${badgeClass}">${b.status || (isSelected ? 'CHAMPION' : 'VALIDATED')}</span>
            </td>
          </tr>
        `;
      }).join("");
    } else {
      bmTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No benchmark metrics available.</td></tr>`;
    }

  } catch (err) {
    if (fcTbody) fcTbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--accent-rose);">Forecast error: ${err.message}</td></tr>`;
    if (bmTbody) bmTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--accent-rose);">Benchmark error: ${err.message}</td></tr>`;
  }
}

function initDetailModal() {
  btnCloseDetailModal.addEventListener("click", () => detailModal.classList.remove("active"));
  const btnRetrain = document.getElementById("btn-retrain-forecast");
  if (btnRetrain) {
    btnRetrain.addEventListener("click", () => {
      if (activeDetailProductId) {
        showToast("Triggering on-demand multi-model re-benchmark...", "info");
        loadSkuForecast(activeDetailProductId, true);
      }
    });
  }
}

// --- 7b. Replenishment Policy & Order Optimization (Phase 5) ---
let cachedRecommendations = [];

async function fetchReplenishmentRecommendations() {
  const tbody = document.getElementById("replenishment-recs-tbody");
  const slSelect = document.getElementById("replenish-service-level");
  const serviceLevel = slSelect ? parseFloat(slSelect.value) : 0.95;

  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 2rem;">Evaluating stochastic ROP & EOQ across catalogue...</td></tr>`;

  try {
    const res = await fetch(`${API_BASE}/api/replenishment/recommendations?service_level=${serviceLevel}`);
    if (!res.ok) throw new Error("Failed to load replenishment recommendations");

    const result = await res.json();
    cachedRecommendations = result.data.recommendations || [];

    if (cachedRecommendations.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--accent-emerald); padding: 2rem;">✓ All catalogue inventory positions are currently above their Reorder Points (ROP). No replenishment required.</td></tr>`;
      return;
    }

    tbody.innerHTML = cachedRecommendations.map(r => {
      const isCrit = r.urgency === "CRITICAL";
      const isHigh = r.urgency === "HIGH";
      const badgeClass = isCrit ? "badge badge-critical" : (isHigh ? "badge badge-warning" : "badge badge-normal");
      const ev = r.evidence;

      return `
        <tr>
          <td><input type="checkbox" class="rec-checkbox" data-rec-id="${r.id}" checked></td>
          <td style="font-weight: 600;">
            <span style="color: var(--accent-blue); font-family: var(--font-mono); font-size: 0.8rem;">${r.sku}</span> ${r.name}
          </td>
          <td style="text-align: center;"><span class="${badgeClass}">${r.urgency}</span></td>
          <td class="num-cell" style="text-align: right; font-weight: 600; color: ${isCrit ? 'var(--accent-rose)' : 'inherit'};">
            ${ev.current_stock}
          </td>
          <td class="num-cell" style="text-align: right;">${ev.rop} <span style="font-size: 0.75rem; color: var(--text-muted);">(${ev.safety_stock})</span></td>
          <td class="num-cell" style="text-align: right;">${ev.eoq} <span style="font-size: 0.75rem; color: var(--text-muted);">(${ev.moq})</span></td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: var(--accent-emerald);">
            ${r.recommended_quantity}
          </td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">
            ₹${r.total_investment_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </td>
          <td style="font-size: 0.85rem;">${r.supplier_name || 'Unassigned'}</td>
          <td>
            <button class="btn btn-sm" onclick="openDetailDrawer(${r.product_id})">Inspect SKU</button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--accent-rose); padding: 2rem;">Error: ${err.message}</td></tr>`;
  }
}

async function fetchPurchaseOrders() {
  const tbody = document.getElementById("pos-table-body");
  const statusFilter = document.getElementById("po-status-filter")?.value || "";

  if (!tbody) return;
  try {
    let url = `${API_BASE}/api/replenishment/purchase-orders`;
    if (statusFilter) url += `?status=${statusFilter}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load purchase orders");

    const result = await res.json();
    const pos = result.data.purchase_orders || [];

    if (pos.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2rem;">No purchase orders match current filter.</td></tr>`;
      return;
    }

    tbody.innerHTML = pos.map(po => {
      let badgeClass = "badge badge-normal";
      if (po.status === "APPROVED") badgeClass = "badge badge-primary";
      else if (po.status === "SENT") badgeClass = "badge badge-warning";
      else if (po.status === "RECEIVED") badgeClass = "badge badge-emerald";

      // Contextual Action Buttons based on lifecycle status
      let actionHtml = "";
      if (po.status === "DRAFT") {
        actionHtml = `<button class="btn btn-sm btn-primary" onclick="changePOStatus(${po.id}, 'APPROVED')">Approve PO</button>`;
      } else if (po.status === "APPROVED") {
        actionHtml = `<button class="btn btn-sm btn-primary" onclick="changePOStatus(${po.id}, 'SENT')">Mark Sent to Supplier</button>`;
      } else if (po.status === "SENT") {
        actionHtml = `<button class="btn btn-sm btn-emerald" onclick="changePOStatus(${po.id}, 'RECEIVED')">📥 Book Stock Receipt</button>`;
      } else if (po.status === "RECEIVED") {
        actionHtml = `<span style="color: var(--accent-emerald); font-size: 0.8rem; font-weight: 600;">✓ Inbound Stock Booked</span>`;
      }

      return `
        <tr>
          <td style="font-family: var(--font-mono); font-weight: 700; color: var(--accent-blue); font-size: 0.85rem;">
            ${po.po_number}
          </td>
          <td style="font-weight: 600;">${po.supplier_name || 'Vendor'}</td>
          <td class="num-cell" style="font-size: 0.75rem; color: var(--text-secondary);">${po.created_at}</td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">${po.item_count || 1} SKUs</td>
          <td class="num-cell" style="text-align: right; font-weight: 700;">₹${Number(po.total_amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          <td style="text-align: center;"><span class="${badgeClass}">${po.status}</span></td>
          <td style="text-align: right;">${actionHtml}</td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--accent-rose); padding: 2rem;">Error: ${err.message}</td></tr>`;
  }
}

async function consolidateSelectedRecommendations() {
  const checkboxes = document.querySelectorAll(".rec-checkbox:checked");
  const selectedIds = Array.from(checkboxes).map(cb => parseInt(cb.getAttribute("data-rec-id"), 10));

  if (selectedIds.length === 0) {
    showToast("Please select at least one recommendation to consolidate into a Purchase Order.", "warning");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/replenishment/purchase-orders/consolidate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recommendation_ids: selectedIds,
        notes: "Automated multi-SKU replenishment order"
      })
    });

    const result = await res.json();
    if (!res.ok) throw new Error(result.error?.message || result.message || "Failed to consolidate POs");

    showToast(`Generated ${result.data.created_purchase_orders_count} consolidated Purchase Order(s) across suppliers!`, "success");
    fetchReplenishmentRecommendations();
    fetchPurchaseOrders();
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.changePOStatus = async function(poId, newStatus) {
  try {
    const res = await fetch(`${API_BASE}/api/replenishment/purchase-orders/${poId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus })
    });

    const result = await res.json();
    if (!res.ok) throw new Error(result.error?.message || result.message || "Failed to update PO status");

    if (newStatus === "RECEIVED") {
      showToast(`Inbound stock movement booked! Inventory levels updated automatically.`, "success");
      fetchProducts();
      fetchPulse();
    } else {
      showToast(`Purchase order status updated to ${newStatus}.`, "success");
    }

    fetchPurchaseOrders();
  } catch (err) {
    showToast(err.message, "error");
  }
};

// --- 7c. Digital Twin Simulator & Resilience Lab (Phase 6) ---
let canonicalPresetsCache = [];

async function fetchSimulationPresets() {
  const select = document.getElementById("sim-preset-select");
  if (!select || select.options.length > 1) return;

  try {
    const res = await fetch(`${API_BASE}/api/simulation/presets`);
    if (!res.ok) return;

    const result = await res.json();
    canonicalPresetsCache = result.data.presets || [];

    select.innerHTML = `<option value="">Select Predefined Disruption...</option>` +
      canonicalPresetsCache.map(p => `
        <option value="${p.id}">${p.name}</option>
      `).join("");

    select.addEventListener("change", () => {
      const selectedId = select.value;
      const preset = canonicalPresetsCache.find(p => p.id === selectedId);
      if (preset) {
        document.getElementById("sim-shock-type").value = preset.shock_type;
        document.getElementById("sim-duration").value = preset.duration_days;
        document.getElementById("sim-magnitude").value = preset.magnitude || 1.0;
        document.getElementById("sim-target-category").value = preset.target_category || "";
      }
    });

  } catch (err) {
    console.warn("Unable to load simulation presets:", err);
  }
}

async function runDigitalTwinSimulation() {
  const btnRun = document.getElementById("btn-run-simulation");
  const shockType = document.getElementById("sim-shock-type").value;
  const duration = parseInt(document.getElementById("sim-duration").value, 10) || 30;
  const magnitude = parseFloat(document.getElementById("sim-magnitude").value) || 1.0;
  const targetCategory = document.getElementById("sim-target-category").value.trim() || undefined;

  const stockoutEl = document.getElementById("sim-stockout-incidents");
  const revEl = document.getElementById("sim-revenue-exposure");
  const resEl = document.getElementById("sim-resilience-delta");
  const ttrEl = document.getElementById("sim-ttr-days");
  const mitigationsContainer = document.getElementById("sim-mitigations-container");
  const trajectoryTbody = document.getElementById("sim-trajectory-tbody");

  if (btnRun) {
    btnRun.disabled = true;
    btnRun.textContent = "Simulating Network Shocks...";
  }

  if (trajectoryTbody) {
    trajectoryTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2rem;">Executing 45-day discrete-event simulation across nodes...</td></tr>`;
  }

  try {
    const res = await fetch(`${API_BASE}/api/simulation/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        shock_type: shockType,
        name: `Stress Test: ${shockType}`,
        duration_days: duration,
        magnitude: magnitude,
        target_category: targetCategory,
        horizon_days: 45
      })
    });

    if (!res.ok) throw new Error("Simulation execution failed");
    const result = await res.json();
    const data = result.data;
    const summary = data.impact_summary;

    // Update KPI Scorecards
    if (stockoutEl) stockoutEl.textContent = `+${summary.projected_stockout_incidents}`;
    if (revEl) revEl.textContent = `₹${summary.revenue_exposure_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    if (resEl) resEl.textContent = `${summary.resilience_score_delta} pts`;
    if (ttrEl) ttrEl.textContent = `${summary.time_to_recovery_days} Days`;

    // Render Mitigation Strategies
    if (mitigationsContainer && data.mitigation_options) {
      mitigationsContainer.innerHTML = data.mitigation_options.map(m => `
        <div class="card" style="border: 1px solid var(--border-subtle); padding: 1rem;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
            <div style="font-weight: 600; font-size: 0.9rem; color: var(--accent-blue);">${m.title}</div>
            <span class="badge ${m.recommendation.includes('HIGHLY') ? 'badge-primary' : 'badge-normal'}">${m.recommendation}</span>
          </div>
          <p style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 0.75rem;">${m.action}</p>
          <div style="display: flex; justify-content: space-between; font-size: 0.75rem;">
            <div>Cost: <strong style="color: var(--accent-rose);">₹${m.implementation_cost_inr.toLocaleString()}</strong></div>
            <div>Risk Mitigated: <strong>${m.risk_mitigation_pct}%</strong></div>
            <div>Net Capital Saved: <strong style="color: var(--accent-emerald);">₹${m.net_capital_saved_inr.toLocaleString()}</strong></div>
          </div>
        </div>
      `).join("");
    }

    // Render Trajectory Table
    if (trajectoryTbody && data.trajectory) {
      trajectoryTbody.innerHTML = data.trajectory.map(t => {
        const isDisrupted = t.is_shock_active;
        const statusBadge = isDisrupted 
          ? `<span class="badge badge-critical">DISRUPTED</span>`
          : `<span class="badge badge-normal">NORMAL</span>`;

        return `
          <tr style="${isDisrupted ? 'background: rgba(244, 63, 94, 0.05);' : ''}">
            <td class="num-cell" style="font-weight: 600;">Day ${t.day}</td>
            <td class="num-cell" style="font-size: 0.8rem; color: var(--text-secondary);">${t.date}</td>
            <td class="num-cell" style="text-align: right;">${t.baseline_stock} units</td>
            <td class="num-cell" style="text-align: right; font-weight: 700; color: ${t.shocked_stock < t.baseline_stock ? 'var(--accent-rose)' : 'inherit'};">
              ${t.shocked_stock} units
            </td>
            <td class="num-cell" style="text-align: right; color: ${t.shocked_stockouts > 0 ? 'var(--accent-rose)' : 'inherit'};">
              ${t.shocked_stockouts}
            </td>
            <td class="num-cell" style="text-align: right; font-weight: 600;">
              ₹${Number(t.revenue_lost_inr).toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </td>
            <td style="text-align: center;">${statusBadge}</td>
          </tr>
        `;
      }).join("");
    }

    showToast("Stress test completed across 45 discrete event days!", "success");

  } catch (err) {
    showToast(err.message, "error");
    if (trajectoryTbody) {
      trajectoryTbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--accent-rose); padding: 2rem;">Simulation failed: ${err.message}</td></tr>`;
    }
  } finally {
    if (btnRun) {
      btnRun.disabled = false;
      btnRun.textContent = "⚡ Run Stress Test";
    }
  }
}

// --- 8. Audit Ledger View ---
async function fetchAuditLedger() {
  const tbody = document.getElementById("ledger-table-body");
  const typeFilter = document.getElementById("ledger-type-filter").value;
  try {
    let url = `${API_BASE}/api/movements?limit=100`;
    if (typeFilter) url += `&type=${typeFilter}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load audit ledger");

    const result = await res.json();
    const movements = result.data.movements || [];

    if (movements.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2rem;">No movement records found.</td></tr>`;
      return;
    }

    tbody.innerHTML = movements.map(m => `
      <tr>
        <td class="num-cell" style="font-size: 0.75rem; color: var(--text-secondary);">${m.created_at}</td>
        <td style="font-weight: 500;">
          <span style="color: var(--accent-blue); font-family: var(--font-mono); font-size: 0.8rem;">${m.sku}</span> ${m.product_name}
        </td>
        <td><span class="badge" style="background: var(--bg-hover);">${m.movement_type}</span></td>
        <td class="num-cell" style="text-align: right; font-weight: 600; color: ${m.quantity_change >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">
          ${m.quantity_change > 0 ? `+${m.quantity_change}` : m.quantity_change}
        </td>
        <td class="num-cell" style="text-align: right; font-weight: 700;">${m.balance_after}</td>
        <td class="num-cell" style="color: var(--text-muted); font-size: 0.8rem;">${m.reference_id || '—'}</td>
        <td style="font-size: 0.8rem; color: var(--text-secondary);">${m.reason}</td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--accent-rose); padding: 2rem;">Error: ${err.message}</td></tr>`;
  }
}

// --- 9. Operational Intelligence & 8D Risk Matrix ---
async function fetchRisks() {
  const tbody = document.getElementById("risks-table-body");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/risks`);
    if (!res.ok) throw new Error("Failed to load risks");

    const result = await res.json();
    const risks = result.data.risks || [];

    tbody.innerHTML = risks.map(r => {
      const dims = r.dimensions;
      const isCrit = r.composite_rating === "CRITICAL";
      const isHigh = r.composite_rating === "HIGH";
      const ratingClass = isCrit ? "badge badge-critical" : (isHigh ? "badge badge-warning" : "badge badge-normal");

      return `
        <tr>
          <td style="font-weight: 600;">
            <span style="color: var(--accent-blue); font-family: var(--font-mono); font-size: 0.8rem;">${r.sku}</span> ${r.name}
          </td>
          <td class="num-cell" style="text-align: right; color: ${dims.stockout_risk_pct >= 70 ? 'var(--accent-rose)' : 'inherit'};">
            ${dims.stockout_risk_pct}%
          </td>
          <td class="num-cell" style="text-align: right;">${dims.overstock_risk_pct}%</td>
          <td class="num-cell" style="text-align: right; color: ${dims.dead_stock_risk_pct >= 80 ? 'var(--accent-rose)' : 'inherit'};">
            ${dims.dead_stock_risk_pct}%
          </td>
          <td class="num-cell" style="text-align: right;">${dims.supplier_risk_pct}%</td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">₹${dims.capital_at_risk_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          <td style="text-align: center;"><span class="${ratingClass}">${r.composite_rating}</span></td>
          <td style="text-align: right;">
            <button class="btn btn-sm" onclick="openDetailDrawer(${r.product_id})">Evidence & DNA</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--accent-rose); padding: 2rem;">Error: ${err.message}</td></tr>`;
  }
}

async function fetchAnomalies() {
  const tbody = document.getElementById("anomalies-table-body");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/anomalies`);
    if (!res.ok) throw new Error("Failed to scan anomalies");

    const result = await res.json();
    const anomalies = result.data.anomalies || [];

    if (anomalies.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--accent-emerald); padding: 1.5rem;">✓ No statistical demand outliers or bulk order shocks detected.</td></tr>`;
      return;
    }

    tbody.innerHTML = anomalies.map(a => {
      const sevClass = a.severity === "CRITICAL" ? "badge badge-critical" : (a.severity === "HIGH" ? "badge badge-warning" : "badge badge-normal");
      return `
        <tr>
          <td class="num-cell" style="font-weight: 600; color: var(--accent-blue);">${a.entity_type} #${a.entity_id}</td>
          <td><span class="badge" style="background: var(--bg-hover);">${a.anomaly_type}</span></td>
          <td><span class="${sevClass}">${a.severity}</span></td>
          <td style="color: var(--text-secondary);">${a.description}</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error: ${err.message}</td></tr>`;
  }
}

// --- 10. Capital Optimization & Working Capital Allocation View (Phase 9) ---
async function fetchCapitalView() {
  await Promise.allSettled([
    fetchCapitalOverviewMetrics(),
    fetchCapitalParetoAnalytics(),
    fetchDeadStockReclamation(),
    fetchHoldingCostSensitivity(),
    runCapitalRebalance()
  ]);
}

async function fetchCapitalOverviewMetrics() {
  try {
    const res = await fetch(`${API_BASE}/api/capital`);
    if (!res.ok) throw new Error("Failed to fetch capital intelligence");

    const result = await res.json();
    const cap = result.data.capital;

    const elTotal = document.getElementById("cap-total");
    if (elTotal) elTotal.textContent = `₹${cap.total_working_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

    const elDead = document.getElementById("cap-dead");
    if (elDead) elDead.textContent = `₹${cap.dead_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

    const elDeadPct = document.getElementById("cap-dead-pct");
    if (elDeadPct) elDeadPct.textContent = `${cap.dead_capital_pct}% of total capital`;

    const elOverstock = document.getElementById("cap-overstock");
    if (elOverstock) elOverstock.textContent = `₹${cap.overstock_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

    const elConc = document.getElementById("cap-concentration");
    if (elConc) elConc.textContent = `Concentration top 3: ${cap.capital_concentration_top3_pct}%`;
  } catch (err) {
    console.warn("Capital overview error:", err);
  }
}

async function fetchCapitalParetoAnalytics() {
  const tbody = document.getElementById("capital-skus-tbody");
  try {
    const res = await fetch(`${API_BASE}/api/capital/analytics`);
    if (!res.ok) throw new Error("Failed to load capital analytics");

    const result = await res.json();
    const data = result.data;

    // Update Scorecard metrics
    const elItr = document.getElementById("cap-velocity-itr");
    if (elItr) elItr.textContent = `${data.portfolio_itr}x`;

    const elDsi = document.getElementById("cap-velocity-dsi");
    if (elDsi) elDsi.textContent = `DSI: ${data.portfolio_dsi} days`;

    const elGini = document.getElementById("cap-gini");
    if (elGini) elGini.textContent = `${data.gini_coefficient.toFixed(3)}`;

    const elGiniBadge = document.getElementById("pareto-gini-badge");
    if (elGiniBadge) elGiniBadge.textContent = `${data.gini_coefficient.toFixed(3)}`;

    if (!tbody) return;
    const items = data.items || [];
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">No inventory valuation records found.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map(item => {
      let badgeClass = "badge-normal";
      if (item.abc_class === "A") badgeClass = "badge-critical";
      else if (item.abc_class === "B") badgeClass = "badge-warning";

      let quadColor = "var(--text-secondary)";
      if (item.capital_productivity_quadrant === "Star Cash Generator") quadColor = "var(--accent-emerald)";
      else if (item.capital_productivity_quadrant === "Balanced Workhorse") quadColor = "var(--accent-blue)";
      else if (item.capital_productivity_quadrant === "Slow-Turning Buffer") quadColor = "var(--accent-amber)";
      else if (item.capital_productivity_quadrant === "Capital Trap") quadColor = "var(--accent-rose)";

      return `
        <tr>
          <td class="num-cell" style="font-weight: 600; color: var(--accent-blue);">${item.sku}</td>
          <td style="font-weight: 500;">${item.product_name}</td>
          <td><span class="badge ${badgeClass}">${item.abc_class} (${item.abc_category})</span></td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">₹${item.valuation_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          <td class="num-cell" style="text-align: right; color: var(--text-secondary);">${item.cumulative_capital_share_pct.toFixed(1)}%</td>
          <td class="num-cell" style="text-align: right;">₹${item.annual_cogs_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
          <td class="num-cell" style="text-align: right; font-weight: 600; color: ${item.inventory_turnover_ratio >= 10 ? 'var(--accent-emerald)' : 'var(--text-primary)'};">${item.inventory_turnover_ratio.toFixed(1)}x</td>
          <td class="num-cell" style="text-align: right;">${item.days_sales_of_inventory.toFixed(1)} d</td>
          <td><span style="font-weight: 600; font-size: 0.8rem; color: ${quadColor};">● ${item.capital_productivity_quadrant}</span></td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error: ${err.message}</td></tr>`;
  }
}

async function runCapitalRebalance() {
  const serviceLevelSelect = document.getElementById("rebalance-service-level");
  const budgetCeilingInput = document.getElementById("rebalance-budget-ceiling");
  const tbody = document.getElementById("rebalance-skus-tbody");

  const serviceLevel = serviceLevelSelect ? parseFloat(serviceLevelSelect.value) : 0.95;
  const budgetCeiling = (budgetCeilingInput && budgetCeilingInput.value) ? parseFloat(budgetCeilingInput.value) : null;

  try {
    const res = await fetch(`${API_BASE}/api/capital/rebalance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        service_level: serviceLevel,
        budget_ceiling_inr: budgetCeiling
      })
    });
    if (!res.ok) throw new Error("Buffer rebalancing calculation failed");

    const result = await res.json();
    const data = result.data;

    // Update Rebalancing Scorecard Cards
    const elRebPot = document.getElementById("cap-rebalance-potential");
    if (elRebPot) elRebPot.textContent = `₹${data.capital_released_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

    const elRebHint = document.getElementById("cap-rebalance-hint");
    if (elRebHint) elRebHint.textContent = `${data.overstocked_skus_count} SKUs with harvestable buffer`;

    const elRel = document.getElementById("reb-cap-release");
    if (elRel) elRel.textContent = `₹${data.capital_released_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    const elRelSkus = document.getElementById("reb-skus-release");
    if (elRelSkus) elRelSkus.textContent = `${data.overstocked_skus_count} SKUs overstocked`;

    const elInj = document.getElementById("reb-cap-inject");
    if (elInj) elInj.textContent = `₹${data.capital_injected_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    const elInjSkus = document.getElementById("reb-skus-inject");
    if (elInjSkus) elInjSkus.textContent = `${data.understocked_skus_count} SKUs understocked`;

    const elNet = document.getElementById("reb-net-delta");
    if (elNet) {
      const isPositive = data.net_capital_delta_inr >= 0;
      elNet.textContent = `${isPositive ? '+' : ''}₹${data.net_capital_delta_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
      elNet.style.color = isPositive ? 'var(--accent-rose)' : 'var(--accent-emerald)';
    }

    const elNetStatus = document.getElementById("reb-net-status");
    if (elNetStatus) elNetStatus.textContent = data.net_capital_delta_inr <= 0 ? "Self-funding surplus (Capital Free)" : "Capital expansion required";

    const elEff = document.getElementById("reb-efficiency");
    if (elEff) elEff.textContent = data.budget_constrained ? "Budget Constrained" : "Unconstrained Optimum";

    if (!tbody) return;
    const actions = data.rebalancing_actions || [];
    if (actions.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">All buffers currently aligned to target service level.</td></tr>`;
      return;
    }

    tbody.innerHTML = actions.map(act => {
      const isRelease = act.action === "RELEASE_CAPITAL";
      const isInject = act.action === "INJECT_CAPITAL";
      const badgeStyle = isRelease ? "background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald);" : (isInject ? "background: rgba(244, 63, 94, 0.15); color: var(--accent-rose);" : "background: var(--bg-hover); color: var(--text-muted);");

      return `
        <tr>
          <td class="num-cell" style="font-weight: 600; color: var(--accent-blue);">${act.sku}</td>
          <td style="font-weight: 500;">${act.product_name}</td>
          <td class="num-cell" style="text-align: right;">${act.current_stock}</td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">${act.target_buffer}</td>
          <td class="num-cell" style="text-align: right; color: ${act.quantity_delta > 0 ? 'var(--accent-rose)' : (act.quantity_delta < 0 ? 'var(--accent-emerald)' : 'var(--text-muted)')}; font-weight: 600;">
            ${act.quantity_delta > 0 ? `+${act.quantity_delta}` : act.quantity_delta}
          </td>
          <td><span class="badge" style="${badgeStyle}">${act.action.replace("_", " ")}</span></td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: ${isRelease ? 'var(--accent-emerald)' : (isInject ? 'var(--accent-rose)' : 'var(--text-primary)')};">
            ${isRelease ? '-' : (isInject ? '+' : '')}₹${act.capital_impact_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error: ${err.message}</td></tr>`;
  }
}

async function fetchDeadStockReclamation() {
  const container = document.getElementById("dead-stock-container");
  const badgeSkus = document.getElementById("dead-skus-badge");
  const badgeRec = document.getElementById("dead-recoverable-badge");

  try {
    const res = await fetch(`${API_BASE}/api/capital/dead-stock-reclamation`);
    if (!res.ok) throw new Error("Failed to load dead stock playbook");

    const result = await res.json();
    const data = result.data;

    if (badgeSkus) badgeSkus.textContent = `${data.total_dead_skus} Stagnant SKUs`;
    if (badgeRec) badgeRec.textContent = `₹${data.total_recoverable_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })} Potential Recovery`;

    if (!container) return;
    const playbooks = data.reclamation_playbooks || [];
    if (playbooks.length === 0) {
      container.innerHTML = `<div style="text-align: center; color: var(--accent-emerald); padding: 2rem; background: var(--bg-surface); border-radius: 8px;">✓ Zero dead stock detected across active catalogue. Capital is fully productive.</div>`;
      return;
    }

    container.innerHTML = playbooks.map(pb => `
      <div style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 8px; padding: 1rem;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem;">
          <div>
            <div style="font-weight: 700; font-size: 0.95rem; color: var(--text-primary);">
              <span style="color: var(--accent-blue); font-family: var(--font-mono);">${pb.sku}</span> ${pb.product_name}
            </div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem;">
              Current Stock: <strong>${pb.current_stock} units</strong> | Book Valuation: <strong>₹${pb.valuation_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong> | Annual Carrying Bleed: <span style="color: var(--accent-rose);">₹${pb.annual_holding_cost_bleed_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}/yr</span>
            </div>
          </div>
          <div>
            <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); font-weight: 700;">
              Recommended: ${pb.recommended_strategy.replace(/_/g, " ")}
            </span>
          </div>
        </div>

        <!-- 4 Structured Reclamation Strategies Grid -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.75rem;">
          <!-- Strategy 1: Discount Markdown -->
          <div style="background: var(--bg-base); padding: 0.75rem; border-radius: 6px; border-left: 3px solid ${pb.recommended_strategy === 'DISCOUNT_MARKDOWN' ? 'var(--accent-emerald)' : 'var(--border-color)'};">
            <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">1. Promotional Markdown (30%)</div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem;">Immediate price concession to liquidate dormant stock.</div>
            <div style="font-size: 0.85rem; font-weight: 700; color: var(--accent-emerald);">₹${pb.strategies.discount_markdown.recoverable_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">Recovery: ${pb.strategies.discount_markdown.recovery_rate_pct}% | Speed: ${pb.strategies.discount_markdown.liquidation_speed}</div>
          </div>

          <!-- Strategy 2: Supplier Buyback -->
          <div style="background: var(--bg-base); padding: 0.75rem; border-radius: 6px; border-left: 3px solid ${pb.recommended_strategy === 'SUPPLIER_BUYBACK' ? 'var(--accent-emerald)' : 'var(--border-color)'};">
            <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">2. Supplier Buyback (75%)</div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem;">Return to Tier-1 vendor under contractual credit rebate.</div>
            <div style="font-size: 0.85rem; font-weight: 700; color: var(--accent-emerald);">₹${pb.strategies.supplier_buyback.recoverable_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">Recovery: ${pb.strategies.supplier_buyback.recovery_rate_pct}% | Speed: ${pb.strategies.supplier_buyback.liquidation_speed}</div>
          </div>

          <!-- Strategy 3: Bundle Liquidation -->
          <div style="background: var(--bg-base); padding: 0.75rem; border-radius: 6px; border-left: 3px solid ${pb.recommended_strategy === 'STRATEGIC_BUNDLE' ? 'var(--accent-emerald)' : 'var(--border-color)'};">
            <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">3. Strategic Cross-Bundle</div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem;">Pair with high-velocity Class A products to accelerate sell-off.</div>
            <div style="font-size: 0.85rem; font-weight: 700; color: var(--accent-emerald);">₹${pb.strategies.strategic_bundle.recoverable_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">Recovery: ${pb.strategies.strategic_bundle.recovery_rate_pct}% | Speed: ${pb.strategies.strategic_bundle.liquidation_speed}</div>
          </div>

          <!-- Strategy 4: Scrap / Tax Shield -->
          <div style="background: var(--bg-base); padding: 0.75rem; border-radius: 6px; border-left: 3px solid ${pb.recommended_strategy === 'SCRAP_TAX_SHIELD' ? 'var(--accent-emerald)' : 'var(--border-color)'};">
            <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.25rem;">4. Scrap & Tax Shield (30%)</div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem;">Decommission obsolete inventory and claim corporate tax shield.</div>
            <div style="font-size: 0.85rem; font-weight: 700; color: var(--accent-emerald);">₹${pb.strategies.scrap_tax_shield.recoverable_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">Recovery: ${pb.strategies.scrap_tax_shield.recovery_rate_pct}% | Speed: ${pb.strategies.scrap_tax_shield.liquidation_speed}</div>
          </div>
        </div>
      </div>
    `).join("");
  } catch (err) {
    if (container) container.innerHTML = `<div style="text-align: center; color: var(--accent-rose); padding: 2rem;">Error: ${err.message}</div>`;
  }
}

async function fetchHoldingCostSensitivity() {
  const tbody = document.getElementById("sensitivity-tbody");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/capital/sensitivity`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rates: [0.15, 0.18, 0.20, 0.25, 0.30] })
    });
    if (!res.ok) throw new Error("Failed to load holding cost sensitivity");

    const result = await res.json();
    const rows = result.data.sensitivity_curve || [];

    tbody.innerHTML = rows.map(r => `
      <tr>
        <td style="font-weight: 600; color: ${r.holding_cost_rate_pct === 20 ? 'var(--accent-blue)' : 'var(--text-primary)'};">
          ${r.holding_cost_rate_pct.toFixed(1)}% ${r.holding_cost_rate_pct === 20 ? '(Baseline)' : ''}
        </td>
        <td class="num-cell" style="text-align: right;">₹${r.total_working_capital_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
        <td class="num-cell" style="text-align: right; font-weight: 600; color: var(--accent-rose);">₹${r.annual_carrying_cost_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
        <td class="num-cell" style="text-align: right; color: var(--text-secondary);">₹${r.daily_carrying_cost_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}/day</td>
        <td class="num-cell" style="text-align: right; color: var(--accent-amber);">₹${r.overstock_carrying_burden_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
        <td class="num-cell" style="text-align: right; color: var(--accent-rose);">₹${r.dead_stock_carrying_bleed_inr.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error: ${err.message}</td></tr>`;
  }
}

// --- 11. Supplier Operations ---
async function fetchSuppliers() {
  const tbody = document.getElementById("suppliers-table-body");
  try {
    const res = await fetch(`${API_BASE}/api/suppliers`);
    if (!res.ok) throw new Error("Failed to fetch suppliers");

    const result = await res.json();
    const suppliers = result.data.suppliers || [];

    if (suppliers.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">No suppliers registered yet. Click '+ Register Supplier' to add one.</td></tr>`;
      return;
    }

    tbody.innerHTML = suppliers.map(s => {
      const relScore = Math.round(s.reliability_score * 100);
      const relColor = relScore >= 90 ? 'var(--accent-emerald)' : (relScore >= 75 ? 'var(--accent-amber)' : 'var(--accent-rose)');
      return `
        <tr>
          <td style="font-weight: 600;">${s.name}</td>
          <td style="color: var(--text-secondary);">${s.contact_email || '—'}</td>
          <td class="num-cell" style="text-align: right;">${s.lead_time_days} days</td>
          <td class="num-cell" style="text-align: right;">±${s.lead_time_variance} days</td>
          <td class="num-cell" style="text-align: right; font-weight: 600; color: ${relColor};">${relScore}%</td>
          <td style="text-align: center;"><span class="badge badge-normal">${s.status}</span></td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--accent-rose); padding: 2rem;">Error: ${err.message}</td></tr>`;
  }
}

function initSupplierModal() {
  const open = () => supplierModal.classList.add("active");
  const close = () => {
    supplierModal.classList.remove("active");
    supplierForm.reset();
  };

  btnAddSupplier.addEventListener("click", open);
  btnCloseSupplierModal.addEventListener("click", close);
  btnCancelSupplierModal.addEventListener("click", close);

  supplierForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("supp-name").value.trim();
    const email = document.getElementById("supp-email").value.trim();
    const lead = parseInt(document.getElementById("supp-lead").value, 10);
    const reliability = parseFloat(document.getElementById("supp-reliability").value);

    try {
      const res = await fetch(`${API_BASE}/api/suppliers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          contact_email: email || undefined,
          lead_time_days: lead,
          reliability_score: reliability
        })
      });

      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.error?.message || result.message || "Failed to register supplier");
      }

      showToast(`Supplier '${result.data.name}' registered.`, "success");
      close();
      fetchSuppliers();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

// --- 12. Add Product Modal & Search Setup ---
function initProductModal() {
  const openModal = () => productModal.classList.add("active");
  const closeModal = () => {
    productModal.classList.remove("active");
    productForm.reset();
  };

  btnAddProduct.addEventListener("click", openModal);
  btnCloseModal.addEventListener("click", closeModal);
  btnCancelModal.addEventListener("click", closeModal);

  productForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const name = document.getElementById("prod-name").value.trim();
    const category = document.getElementById("prod-category").value.trim();
    const quantity = parseInt(document.getElementById("prod-qty").value, 10);
    const price = parseFloat(document.getElementById("prod-price").value);
    const reorder_threshold = parseInt(document.getElementById("prod-threshold").value, 10);
    const sku = document.getElementById("prod-sku").value.trim();
    const description = document.getElementById("prod-desc").value.trim();

    if (quantity < 0 || price < 0 || reorder_threshold < 0) {
      showToast("Quantity, price, and reorder threshold cannot be negative.", "error");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          category,
          quantity,
          price,
          reorder_threshold,
          sku: sku || undefined,
          description: description || undefined
        })
      });

      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.error?.message || result.message || "Failed to create product");
      }

      showToast(`SKU '${result.data.sku}' created successfully.`, "success");
      closeModal();
      fetchProducts();
      fetchPulse();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function initSearchAndFilters() {
  let debounceTimeout = null;
  searchInput.addEventListener("input", (e) => {
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      fetchProducts(e.target.value.trim(), categoryFilter.value);
    }, 250);
  });

  categoryFilter.addEventListener("change", (e) => {
    fetchProducts(searchInput.value.trim(), e.target.value);
  });

  btnToggleLowStock.addEventListener("click", () => {
    showLowStockOnly = !showLowStockOnly;
    if (showLowStockOnly) {
      btnToggleLowStock.textContent = "Show All Products";
      btnToggleLowStock.classList.add("btn-danger");
    } else {
      btnToggleLowStock.textContent = "Show Low Stock Only";
      btnToggleLowStock.classList.remove("btn-danger");
    }
    fetchProducts(searchInput.value.trim(), categoryFilter.value);
  });

  // Ctrl+K Shortcut to focus search
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      const inventoryBtn = document.querySelector('[data-view="inventory"]');
      if (inventoryBtn) inventoryBtn.click();
      setTimeout(() => searchInput.focus(), 100);
    }
  });

  // Demo Seeder Button
  const btnSeed = document.getElementById("btn-seed-data");
  if (btnSeed) {
    btnSeed.addEventListener("click", async () => {
      btnSeed.disabled = true;
      btnSeed.textContent = "Seeding Scenarios...";
      try {
        const res = await fetch(`${API_BASE}/api/system/seed`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ seed: 42 })
        });
        if (!res.ok) throw new Error("Seeding failed");
        showToast("7 Operational Scenarios loaded with 90-day demand histories!", "success");
        fetchPulse();
        fetchResilienceIndex();
        fetchAttentionQueue();
        fetchProducts();
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnSeed.disabled = false;
        btnSeed.textContent = "⚡ Load Demo Scenarios";
      }
    });
  }

  // Refresh buttons
  const btnRefreshLedger = document.getElementById("btn-refresh-ledger");
  if (btnRefreshLedger) btnRefreshLedger.addEventListener("click", fetchAuditLedger);

  const btnLedgerType = document.getElementById("ledger-type-filter");
  if (btnLedgerType) btnLedgerType.addEventListener("change", fetchAuditLedger);

  const btnRescanAnom = document.getElementById("btn-rescan-anomalies");
  if (btnRescanAnom) btnRescanAnom.addEventListener("click", fetchAnomalies);

  const btnRefreshRisks = document.getElementById("btn-refresh-risks");
  if (btnRefreshRisks) btnRefreshRisks.addEventListener("click", fetchRisks);

  // Replenishment Controls (Phase 5)
  const btnScanReplenish = document.getElementById("btn-scan-replenish");
  if (btnScanReplenish) btnScanReplenish.addEventListener("click", fetchReplenishmentRecommendations);

  const selServiceLevel = document.getElementById("replenish-service-level");
  if (selServiceLevel) selServiceLevel.addEventListener("change", fetchReplenishmentRecommendations);

  const btnConsolidate = document.getElementById("btn-consolidate-pos");
  if (btnConsolidate) btnConsolidate.addEventListener("click", consolidateSelectedRecommendations);

  const chkSelectAll = document.getElementById("chk-select-all-recs");
  if (chkSelectAll) {
    chkSelectAll.addEventListener("change", (e) => {
      document.querySelectorAll(".rec-checkbox").forEach(cb => cb.checked = e.target.checked);
    });
  }

  const btnRefreshPOs = document.getElementById("btn-refresh-pos");
  if (btnRefreshPOs) btnRefreshPOs.addEventListener("click", fetchPurchaseOrders);

  const selPOStatus = document.getElementById("po-status-filter");
  if (selPOStatus) selPOStatus.addEventListener("change", fetchPurchaseOrders);

  // Digital Twin Simulator Controls (Phase 6)
  const btnRunSim = document.getElementById("btn-run-simulation");
  if (btnRunSim) btnRunSim.addEventListener("click", runDigitalTwinSimulation);
}

// ==========================================
// --- Phase 7: Decision Ledger & Action Studio ---
// ==========================================

async function fetchDecisionStudioView() {
  await Promise.all([
    fetchGovernanceMetrics(),
    fetchDecisionRecommendations(),
    fetchDecisionLedger()
  ]);
}

async function fetchGovernanceMetrics() {
  try {
    const res = await fetch(`${API_BASE}/api/decisions/governance`);
    if (!res.ok) return;
    const json = await res.json();
    const metrics = json.data;

    const elTotal = document.getElementById("gov-total-decisions");
    const elApprove = document.getElementById("gov-approval-rate");
    const elMod = document.getElementById("gov-mod-rate");
    const elRej = document.getElementById("gov-rejection-rate");
    const elAvoided = document.getElementById("gov-stockouts-avoided");
    const elCapital = document.getElementById("gov-preserved-capital");

    if (elTotal) elTotal.textContent = metrics.total_decisions;
    if (elApprove) elApprove.textContent = `${metrics.approval_rate_pct}%`;
    if (elMod) elMod.textContent = `${metrics.modification_rate_pct}%`;
    if (elRej) elRej.textContent = `${metrics.rejection_rate_pct}%`;
    if (elAvoided) elAvoided.textContent = metrics.total_stockouts_avoided;
    if (elCapital) elCapital.textContent = `₹${Number(metrics.total_savings_inr).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  } catch (err) {
    console.warn("Unable to fetch governance metrics:", err);
  }
}

async function fetchDecisionRecommendations() {
  const container = document.getElementById("decision-cards-container");
  if (!container) return;

  const statusFilter = document.getElementById("decision-filter-status");
  const status = statusFilter ? statusFilter.value : "PENDING";
  const url = status ? `${API_BASE}/api/decisions/recommendations?status=${encodeURIComponent(status)}` : `${API_BASE}/api/decisions/recommendations`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const recommendations = json.data.recommendations || [];

    if (recommendations.length === 0) {
      container.innerHTML = `
        <div style="color: var(--text-muted); font-size: 0.85rem; padding: 2rem; text-align: center; grid-column: 1 / -1;">
          No recommendations found with status "${status || 'ALL'}". Use the Replenishment view to scan the catalogue if needed.
        </div>
      `;
      return;
    }

    container.innerHTML = recommendations.map(rec => {
      const ev = rec.evidence || {};
      const alts = rec.alternative_options || [];
      const isPending = rec.status === "PENDING";

      const confidenceBadge = rec.confidence_pct >= 85
        ? `<span class="badge badge-normal">${rec.confidence_pct}% CONFIDENCE</span>`
        : `<span class="badge badge-warning">${rec.confidence_pct}% CONFIDENCE</span>`;

      const typeBadge = `<span class="badge" style="background: rgba(56, 189, 248, 0.15); color: var(--accent-blue);">${rec.recommendation_type}</span>`;
      
      const statusBadge = rec.status === "APPROVED"
        ? `<span class="badge badge-normal">APPROVED</span>`
        : rec.status === "MODIFIED"
        ? `<span class="badge badge-warning">MODIFIED</span>`
        : rec.status === "REJECTED"
        ? `<span class="badge badge-critical">REJECTED</span>`
        : `<span class="badge badge-warning">ACTION REQUIRED</span>`;

      return `
        <div class="card" style="display: flex; flex-direction: column; justify-content: space-between; border-left: 3px solid ${isPending ? 'var(--accent-blue)' : (rec.status === 'APPROVED' ? 'var(--accent-emerald)' : 'var(--text-muted)')};">
          <div>
            <!-- Card Header -->
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem; gap: 0.5rem;">
              <div>
                <span style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--accent-blue); font-weight: 600;">${rec.sku}</span>
                <h4 style="font-size: 0.95rem; font-weight: 600; margin-top: 0.1rem;">${rec.product_name}</h4>
                <span style="font-size: 0.7rem; color: var(--text-muted);">${rec.category} • ${rec.primary_supplier || 'Supplier Unassigned'}</span>
              </div>
              <div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem;">
                ${statusBadge}
                ${confidenceBadge}
              </div>
            </div>

            <!-- Operational Directive (WHAT) -->
            <div style="background: rgba(15, 23, 42, 0.6); padding: 0.6rem 0.75rem; border-radius: 4px; border-left: 2px solid var(--accent-emerald); margin-bottom: 0.75rem;">
              <div style="font-size: 0.7rem; text-transform: uppercase; font-weight: 700; color: var(--accent-emerald); letter-spacing: 0.05em; margin-bottom: 0.15rem;">
                🎯 DIRECTIVE (WHAT)
              </div>
              <div style="font-size: 0.85rem; font-weight: 600; color: var(--text-primary); line-height: 1.4;">
                ${rec.what}
              </div>
            </div>

            <!-- Root Cause Explanatory Rationale (WHY) -->
            <div style="margin-bottom: 0.75rem;">
              <div style="font-size: 0.7rem; text-transform: uppercase; font-weight: 700; color: var(--text-muted); letter-spacing: 0.05em; margin-bottom: 0.2rem;">
                🔍 EXPLANATION (WHY)
              </div>
              <p style="font-size: 0.8rem; color: var(--text-secondary); line-height: 1.45;">
                ${rec.why}
              </p>
            </div>

            <!-- Key Quantitative Evidence -->
            <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 6px; padding: 0.6rem; margin-bottom: 0.75rem;">
              <div style="font-size: 0.7rem; text-transform: uppercase; font-weight: 700; color: var(--text-muted); letter-spacing: 0.05em; margin-bottom: 0.35rem;">
                📊 EVIDENCE TELEMETRY
              </div>
              <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; text-align: center;">
                <div style="background: var(--bg-hover); padding: 0.3rem; border-radius: 4px;">
                  <div style="font-size: 0.65rem; color: var(--text-muted);">On-Hand</div>
                  <div style="font-size: 0.85rem; font-weight: 700; color: ${ev.on_hand <= ev.rop ? 'var(--accent-rose)' : 'var(--text-primary)'};">${ev.on_hand ?? '--'}</div>
                </div>
                <div style="background: var(--bg-hover); padding: 0.3rem; border-radius: 4px;">
                  <div style="font-size: 0.65rem; color: var(--text-muted);">Reorder Pt (SS)</div>
                  <div style="font-size: 0.85rem; font-weight: 700; color: var(--accent-amber);">${ev.rop ?? '--'} (${ev.safety_stock ?? '--'})</div>
                </div>
                <div style="background: var(--bg-hover); padding: 0.3rem; border-radius: 4px;">
                  <div style="font-size: 0.65rem; color: var(--text-muted);">EOQ (MOQ)</div>
                  <div style="font-size: 0.85rem; font-weight: 700; color: var(--accent-emerald);">${ev.eoq ?? '--'} (${ev.moq ?? '--'})</div>
                </div>
              </div>
            </div>

            <!-- Evaluated Alternatives -->
            ${alts.length > 0 ? `
              <div style="margin-bottom: 1rem;">
                <div style="font-size: 0.7rem; text-transform: uppercase; font-weight: 700; color: var(--text-muted); letter-spacing: 0.05em; margin-bottom: 0.25rem;">
                  ⚖️ ALTERNATIVES CONSIDERED
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.25rem;">
                  ${alts.map(a => `
                    <div style="font-size: 0.75rem; color: var(--text-secondary); background: rgba(30, 41, 59, 0.4); padding: 0.25rem 0.5rem; border-radius: 3px;">
                      <span style="font-weight: 600; color: var(--text-primary);">${a.option}:</span> ${a.implication}
                    </div>
                  `).join("")}
                </div>
              </div>
            ` : ''}
          </div>

          <!-- Interactive Action Buttons -->
          ${isPending ? `
            <div style="display: flex; gap: 0.5rem; padding-top: 0.75rem; border-top: 1px solid var(--border-subtle);">
              <button class="btn btn-sm btn-primary" style="flex: 1;" onclick="quickApproveRecommendation(${rec.id})">
                ✔ Approve
              </button>
              <button class="btn btn-sm" style="flex: 1; border-color: var(--accent-amber); color: var(--accent-amber);" onclick="openOverrideModal(${rec.id}, 'MODIFIED', '${escapeHtml(rec.sku)}', '${escapeHtml(rec.product_name)}', ${ev.eoq || 10})">
                ✏ Modify
              </button>
              <button class="btn btn-sm btn-danger" style="flex: 1;" onclick="openOverrideModal(${rec.id}, 'REJECTED', '${escapeHtml(rec.sku)}', '${escapeHtml(rec.product_name)}', 0)">
                ✖ Reject
              </button>
            </div>
          ` : `
            <div style="font-size: 0.75rem; color: var(--text-muted); padding-top: 0.5rem; border-top: 1px solid var(--border-subtle); text-align: center;">
              Resolved as ${rec.status}
            </div>
          `}
        </div>
      `;
    }).join("");
  } catch (err) {
    container.innerHTML = `<div style="color: var(--accent-rose); font-size: 0.85rem; padding: 1.5rem; grid-column: 1 / -1;">Error loading recommendations: ${err.message}</div>`;
  }
}

async function fetchDecisionLedger() {
  const tbody = document.getElementById("decision-ledger-tbody");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/decisions/ledger?limit=100`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const rows = json.data.ledger || [];

    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No decisions recorded yet. Take an action above to log an immutable audit entry.</td></tr>`;
      return;
    }

    tbody.innerHTML = rows.map(r => {
      const typeBadge = r.decision_type === "APPROVED"
        ? `<span class="badge badge-normal">APPROVED</span>`
        : r.decision_type === "MODIFIED"
        ? `<span class="badge badge-warning">MODIFIED</span>`
        : `<span class="badge badge-critical">REJECTED</span>`;

      const outcomeHtml = r.observed_result
        ? `<div>
             <span style="font-weight: 600; color: ${r.stockout_avoided ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">
               ${r.stockout_avoided ? '✔ Stockout Avoided' : '✖ Stockout Occurred'}
             </span>
             <div style="font-size: 0.75rem; color: var(--text-muted);">${r.observed_result} (Saved ₹${Number(r.savings_amount || 0).toLocaleString()})</div>
           </div>`
        : `<span style="color: var(--text-muted); font-size: 0.75rem;">Initial Projection</span>`;

      return `
        <tr>
          <td style="font-family: var(--font-mono); font-size: 0.8rem; white-space: nowrap;">
            ${r.decided_at ? new Date(r.decided_at).toLocaleString() : '--'}
          </td>
          <td>
            <div style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-blue);">${r.sku}</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">${r.product_name}</div>
          </td>
          <td style="text-align: center;">${typeBadge}</td>
          <td style="font-size: 0.8rem; font-weight: 500;">${r.operator_name || 'lead_operator'}</td>
          <td style="font-size: 0.8rem; max-width: 250px;">
            ${r.override_reason ? `<span style="color: var(--text-primary); font-style: italic;">"${r.override_reason}"</span>` : '<span style="color: var(--text-muted);">Standard policy execution</span>'}
          </td>
          <td style="text-align: center;">
            <span class="badge badge-normal">${r.execution_status}</span>
          </td>
          <td>${outcomeHtml}</td>
          <td style="text-align: right;">
            <button class="btn btn-sm" onclick="openOutcomeModal(${r.decision_id}, '${escapeHtml(r.sku)}', '${escapeHtml(r.product_name)}')">
              Verify Outcome
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error loading decision ledger: ${err.message}</td></tr>`;
  }
}

async function quickApproveRecommendation(recId) {
  try {
    const res = await fetch(`${API_BASE}/api/decisions/act`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recommendation_id: recId,
        decision_type: "APPROVED",
        override_reason: "Approved per standard replenishment policy",
        user_id: 1
      })
    });

    const json = await res.json();
    if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);

    showToast("Recommendation approved! Purchase order created automatically.", "success");
    fetchDecisionStudioView();
  } catch (err) {
    showToast(`Approval failed: ${err.message}`, "error");
  }
}

function openOverrideModal(recId, type, sku, productName, eoq) {
  const modal = document.getElementById("decision-override-modal");
  const title = document.getElementById("override-modal-title");
  const recIdInput = document.getElementById("override-rec-id");
  const typeInput = document.getElementById("override-decision-type");
  const summaryBox = document.getElementById("override-summary-box");
  const qtyGroup = document.getElementById("override-qty-group");
  const qtyInput = document.getElementById("override-qty");
  const reasonInput = document.getElementById("override-reason");

  if (!modal) return;

  recIdInput.value = recId;
  typeInput.value = type;
  title.textContent = type === "MODIFIED" ? `✏ Modify Recommendation Parameters: ${sku}` : `✖ Reject Recommendation: ${sku}`;
  
  summaryBox.innerHTML = `
    <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.2rem;">${sku} — ${productName}</div>
    <div style="color: var(--text-secondary); font-size: 0.75rem;">Action: <strong>${type}</strong></div>
  `;

  if (type === "MODIFIED") {
    qtyGroup.style.display = "block";
    qtyInput.value = eoq || 10;
  } else {
    qtyGroup.style.display = "none";
  }

  reasonInput.value = "";
  modal.classList.add("active");
}

function openOutcomeModal(decisionId, sku, productName) {
  const modal = document.getElementById("outcome-verify-modal");
  const idInput = document.getElementById("outcome-decision-id");
  const summaryBox = document.getElementById("outcome-summary-box");
  const resultInput = document.getElementById("outcome-observed-result");
  const avoidedSelect = document.getElementById("outcome-stockout-avoided");
  const savingsInput = document.getElementById("outcome-savings-amount");

  if (!modal) return;

  idInput.value = decisionId;
  summaryBox.innerHTML = `
    <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.2rem;">Decision #${decisionId} — ${sku} (${productName})</div>
    <div style="color: var(--text-muted); font-size: 0.75rem;">Verifying closed-loop execution outcome</div>
  `;

  resultInput.value = "Stock arrived on schedule, successfully averted operational downtime.";
  avoidedSelect.value = "1";
  savingsInput.value = "5000";

  modal.classList.add("active");
}

function initDecisionStudioModals() {
  // Override Modal Close
  const overrideModal = document.getElementById("decision-override-modal");
  const btnCloseOverride = document.getElementById("btn-close-override-modal");
  const btnCancelOverride = document.getElementById("btn-cancel-override-modal");
  const overrideForm = document.getElementById("decision-override-form");

  if (btnCloseOverride) btnCloseOverride.addEventListener("click", () => overrideModal.classList.remove("active"));
  if (btnCancelOverride) btnCancelOverride.addEventListener("click", () => overrideModal.classList.remove("active"));

  if (overrideForm) {
    overrideForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const recId = parseInt(document.getElementById("override-rec-id").value, 10);
      const dType = document.getElementById("override-decision-type").value;
      const reason = document.getElementById("override-reason").value.trim();
      const qty = parseInt(document.getElementById("override-qty").value, 10);

      if (reason.length < 5) {
        showToast("Mandatory operational reason must be at least 5 characters.", "error");
        return;
      }

      const payload = {
        recommendation_id: recId,
        decision_type: dType,
        override_reason: reason,
        user_id: 1
      };

      if (dType === "MODIFIED") {
        payload.modified_params = { quantity: qty };
      }

      try {
        const res = await fetch(`${API_BASE}/api/decisions/act`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const json = await res.json();
        if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);

        overrideModal.classList.remove("active");
        showToast(`Decision successfully logged as ${dType}!`, "success");
        fetchDecisionStudioView();
      } catch (err) {
        showToast(`Failed to record decision: ${err.message}`, "error");
      }
    });
  }

  // Outcome Modal Close
  const outcomeModal = document.getElementById("outcome-verify-modal");
  const btnCloseOutcome = document.getElementById("btn-close-outcome-modal");
  const btnCancelOutcome = document.getElementById("btn-cancel-outcome-modal");
  const outcomeForm = document.getElementById("outcome-verify-form");

  if (btnCloseOutcome) btnCloseOutcome.addEventListener("click", () => outcomeModal.classList.remove("active"));
  if (btnCancelOutcome) btnCancelOutcome.addEventListener("click", () => outcomeModal.classList.remove("active"));

  if (outcomeForm) {
    outcomeForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const decisionId = parseInt(document.getElementById("outcome-decision-id").value, 10);
      const observedResult = document.getElementById("outcome-observed-result").value.trim();
      const stockoutAvoided = document.getElementById("outcome-stockout-avoided").value === "1";
      const savingsAmount = parseFloat(document.getElementById("outcome-savings-amount").value) || 0.0;

      try {
        const res = await fetch(`${API_BASE}/api/decisions/${decisionId}/outcome`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            observed_result: observedResult,
            stockout_avoided: stockoutAvoided,
            savings_amount: savingsAmount
          })
        });

        const json = await res.json();
        if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);

        outcomeModal.classList.remove("active");
        showToast("Closed-loop outcome successfully verified!", "success");
        fetchDecisionStudioView();
      } catch (err) {
        showToast(`Failed to record outcome: ${err.message}`, "error");
      }
    });
  }

  // Filter and refresh triggers
  const filterStatus = document.getElementById("decision-filter-status");
  if (filterStatus) filterStatus.addEventListener("change", fetchDecisionRecommendations);

  const btnRefreshRecs = document.getElementById("btn-refresh-decision-recs");
  if (btnRefreshRecs) btnRefreshRecs.addEventListener("click", fetchDecisionRecommendations);

  const btnRefreshLedger = document.getElementById("btn-refresh-decision-ledger");
  if (btnRefreshLedger) btnRefreshLedger.addEventListener("click", fetchDecisionLedger);
}

// ==========================================
// --- Phase 8: Supply Network Graph & Topology ---
// ==========================================

let networkNodesCache = [];
let networkEdgesCache = [];
let highlightSpofsOnly = false;
let currentlyInspectedNodeId = null;

async function fetchSupplyNetworkView() {
  await Promise.all([
    fetchNetworkTopology(),
    fetchNetworkBottlenecks()
  ]);
}

async function fetchNetworkTopology() {
  try {
    const res = await fetch(`${API_BASE}/api/network/topology`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data;

    networkNodesCache = data.nodes || [];
    networkEdgesCache = data.edges || [];

    const summary = data.summary || {};
    const elNodes = document.getElementById("net-total-nodes");
    const elEdges = document.getElementById("net-total-edges");
    const elSpofs = document.getElementById("net-spofs-count");
    const elBlast = document.getElementById("net-max-blast");
    const elFragility = document.getElementById("net-mean-fragility");

    if (elNodes) elNodes.textContent = summary.total_nodes || 0;
    if (elEdges) elEdges.textContent = summary.total_edges || 0;
    if (elSpofs) elSpofs.textContent = summary.spof_nodes_count || 0;
    if (elBlast) elBlast.textContent = `${summary.max_blast_radius_skus || 0} SKUs`;
    if (elFragility) elFragility.textContent = summary.mean_network_fragility || "0.0";

    renderNetworkTopologyGraph();
  } catch (err) {
    console.warn("Unable to fetch network topology:", err);
    showToast(`Failed to load network topology: ${err.message}`, "error");
  }
}

function renderNetworkTopologyGraph() {
  const svg = document.getElementById("network-svg-canvas");
  if (!svg) return;

  const filterSelect = document.getElementById("net-filter-type");
  const selectedType = filterSelect ? filterSelect.value : "";

  // Filter nodes if user chose specific type
  let displayNodes = networkNodesCache;
  if (selectedType) {
    displayNodes = displayNodes.filter(n => n.node_type === selectedType);
  }
  if (highlightSpofsOnly) {
    displayNodes = displayNodes.filter(n => n.is_spof);
  }

  const displayNodeIds = new Set(displayNodes.map(n => n.id));
  const displayEdges = networkEdgesCache.filter(e => displayNodeIds.has(e.source) && displayNodeIds.has(e.target));

  // Layer nodes by tiers
  const tier2Nodes = displayNodes.filter(n => n.node_type === "TIER_2_SUPPLIER");
  const tier1Nodes = displayNodes.filter(n => n.node_type === "TIER_1_SUPPLIER");
  const productNodes = displayNodes.filter(n => n.node_type === "PRODUCT");
  const locationNodes = displayNodes.filter(n => n.node_type === "LOCATION");

  const width = Math.max(760, svg.parentElement ? svg.parentElement.clientWidth : 800);
  const height = 520;
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);

  // Position nodes across 4 vertical bands
  const nodePositions = {};
  const assignPositions = (layerNodes, y) => {
    const count = layerNodes.length;
    const spacing = width / (count + 1);
    layerNodes.forEach((node, idx) => {
      nodePositions[node.id] = {
        x: Math.round(spacing * (idx + 1)),
        y: y,
        node: node
      };
    });
  };

  assignPositions(tier2Nodes, 60);
  assignPositions(tier1Nodes, 190);
  assignPositions(productNodes, 330);
  assignPositions(locationNodes, 460);

  // Clear previous SVG contents
  svg.innerHTML = `
    <defs>
      <marker id="arrow-normal" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
      </marker>
      <marker id="arrow-spof" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#f43f5e" />
      </marker>
    </defs>
  `;

  // Draw Edges (curves with arrows)
  displayEdges.forEach(edge => {
    const p1 = nodePositions[edge.source];
    const p2 = nodePositions[edge.target];
    if (!p1 || !p2) return;

    const isSingle = edge.is_single_source || (p1.node && p1.node.is_spof);
    const strokeColor = isSingle ? "#f43f5e" : "#334155";
    const strokeWidth = isSingle ? "2" : "1.2";
    const strokeDash = isSingle ? "4,3" : "none";
    const marker = isSingle ? "url(#arrow-spof)" : "url(#arrow-normal)";

    // Smooth cubic bezier from bottom of source to top of target
    const pathD = `M ${p1.x} ${p1.y + 14} C ${p1.x} ${p1.y + 60}, ${p2.x} ${p2.y - 60}, ${p2.x} ${p2.y - 14}`;

    const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
    pathEl.setAttribute("d", pathD);
    pathEl.setAttribute("stroke", strokeColor);
    pathEl.setAttribute("stroke-width", strokeWidth);
    pathEl.setAttribute("stroke-dasharray", strokeDash);
    pathEl.setAttribute("fill", "none");
    pathEl.setAttribute("marker-end", marker);
    pathEl.style.opacity = isSingle ? "0.9" : "0.6";

    svg.appendChild(pathEl);
  });

  // Draw Nodes
  Object.values(nodePositions).forEach(({ x, y, node }) => {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("transform", `translate(${x}, ${y})`);
    g.style.cursor = "pointer";
    g.addEventListener("click", () => inspectNetworkNode(node.id));

    const isSelected = currentlyInspectedNodeId === node.id;
    let borderColor = "#38bdf8";
    if (node.node_type === "TIER_2_SUPPLIER") borderColor = "#a855f7";
    else if (node.node_type === "PRODUCT") borderColor = "#10b981";
    else if (node.node_type === "LOCATION") borderColor = "#f59e0b";

    if (node.is_spof) borderColor = "#f43f5e";

    const boxWidth = 130;
    const boxHeight = 32;

    // Outer rect box
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", -boxWidth / 2);
    rect.setAttribute("y", -boxHeight / 2);
    rect.setAttribute("width", boxWidth);
    rect.setAttribute("height", boxHeight);
    rect.setAttribute("rx", "6");
    rect.setAttribute("fill", isSelected ? "#1e293b" : "#0f172a");
    rect.setAttribute("stroke", isSelected ? "#ffffff" : borderColor);
    rect.setAttribute("stroke-width", isSelected ? "2.5" : (node.is_spof ? "2" : "1.2"));

    // Label text
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", 0);
    text.setAttribute("y", 1);
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("dominant-baseline", "middle");
    text.setAttribute("fill", "#f8fafc");
    text.setAttribute("font-size", "10px");
    text.setAttribute("font-family", "var(--font-sans)");
    text.setAttribute("font-weight", "600");

    // Compact truncate
    const labelStr = node.label || node.id;
    const truncated = labelStr.length > 17 ? labelStr.substring(0, 15) + "…" : labelStr;
    text.textContent = truncated;

    // Small status indicator dot
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", -boxWidth / 2 + 8);
    dot.setAttribute("cy", 0);
    dot.setAttribute("r", "3.5");
    dot.setAttribute("fill", node.is_spof ? "#f43f5e" : (node.status === "WARNING" ? "#f59e0b" : "#10b981"));

    g.appendChild(rect);
    g.appendChild(dot);
    g.appendChild(text);

    // Title for SVG tooltip
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${node.label}\nType: ${node.node_type}\nFragility: ${node.fragility_index}/100\nSPOF: ${node.is_spof ? 'YES' : 'NO'}\nBlast Radius: ${node.blast_radius_skus} SKUs`;
    g.appendChild(title);

    svg.appendChild(g);
  });
}

async function inspectNetworkNode(nodeId) {
  currentlyInspectedNodeId = nodeId;
  renderNetworkTopologyGraph();

  const badgeType = document.getElementById("inspect-node-type-badge");
  const labelEl = document.getElementById("inspect-node-label");
  const spofBadge = document.getElementById("inspect-node-spof-badge");
  const fragilityEl = document.getElementById("inspect-node-fragility");
  const betweennessEl = document.getElementById("inspect-node-betweenness");
  const blastEl = document.getElementById("inspect-node-blast");
  const exposureEl = document.getElementById("inspect-node-exposure");
  const cascadeEl = document.getElementById("inspect-node-cascade");
  const btnSimulate = document.getElementById("btn-simulate-node-outage");
  const reportBox = document.getElementById("inspect-outage-report");

  if (reportBox) reportBox.style.display = "none";

  try {
    const res = await fetch(`${API_BASE}/api/network/subgraph/${encodeURIComponent(nodeId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data;

    const node = data.nodes.find(n => n.id === nodeId);
    if (!node) return;

    if (badgeType) {
      badgeType.textContent = node.node_type.replace(/_/g, " ");
      badgeType.className = node.is_spof ? "badge badge-critical" : "badge badge-normal";
    }
    if (labelEl) labelEl.textContent = node.label;
    if (spofBadge) spofBadge.style.display = node.is_spof ? "inline-block" : "none";

    if (fragilityEl) fragilityEl.textContent = `${node.fragility_index} / 100`;
    if (betweennessEl) betweennessEl.textContent = node.betweenness_centrality;
    if (blastEl) blastEl.textContent = `${node.blast_radius_skus} SKUs`;
    if (exposureEl) exposureEl.textContent = `₹${Number(node.revenue_exposure_inr || 0).toLocaleString()}`;

    // Cascade Breakdown
    const upstreamNodes = data.nodes.filter(n => n.id !== nodeId && data.edges.some(e => e.source === n.id));
    const downstreamNodes = data.nodes.filter(n => n.id !== nodeId && data.edges.some(e => e.target === n.id));

    let cascadeHtml = "";
    if (upstreamNodes.length > 0) {
      cascadeHtml += `<div style="margin-bottom: 0.5rem;"><strong style="color: var(--accent-blue);">Upstream Feeds (${upstreamNodes.length}):</strong><br>${upstreamNodes.map(u => `• ${u.label}`).join("<br>")}</div>`;
    }
    if (downstreamNodes.length > 0) {
      cascadeHtml += `<div><strong style="color: var(--accent-emerald);">Downstream Consumers (${downstreamNodes.length}):</strong><br>${downstreamNodes.map(d => `• ${d.label}`).join("<br>")}</div>`;
    }
    if (!cascadeHtml) {
      cascadeHtml = `<span style="color: var(--text-muted);">Independent edge node with no transitive connections.</span>`;
    }

    if (cascadeEl) cascadeEl.innerHTML = cascadeHtml;

    if (btnSimulate) {
      btnSimulate.style.display = "block";
      btnSimulate.onclick = () => simulateNodeOutage(nodeId);
    }
  } catch (err) {
    console.warn("Unable to inspect node:", err);
    showToast(`Error inspecting node: ${err.message}`, "error");
  }
}

async function simulateNodeOutage(nodeId) {
  const reportBox = document.getElementById("inspect-outage-report");
  if (!reportBox) return;

  reportBox.style.display = "block";
  reportBox.innerHTML = `<div style="color: var(--text-muted); font-size: 0.8rem;">Simulating disruption cascade...</div>`;

  try {
    const res = await fetch(`${API_BASE}/api/network/simulate-outage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: nodeId })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data;
    const summary = data.impact_summary;

    reportBox.innerHTML = `
      <div style="background: rgba(244, 63, 94, 0.1); border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 6px; padding: 0.75rem;">
        <div style="font-weight: 700; color: var(--accent-rose); margin-bottom: 0.25rem;">
          ⚡ OUTAGE CASCADE: ${summary.severity} SEVERITY
        </div>
        <div style="font-size: 0.75rem; color: var(--text-primary); margin-bottom: 0.5rem;">
          Severed SKUs (0 Suppliers Remaining): <strong>${summary.severed_skus_count}</strong><br>
          Revenue Exposure at Risk: <strong>₹${Number(summary.total_revenue_exposure_inr).toLocaleString()}</strong>
        </div>
        <div style="font-size: 0.7rem; color: var(--text-secondary); line-height: 1.4;">
          <strong>Recommendation:</strong> ${data.recommended_mitigation}
        </div>
      </div>
    `;

    showToast(`Outage simulated for ${data.failed_node.label}: ${summary.severed_skus_count} SKUs severed!`, "info");
  } catch (err) {
    reportBox.innerHTML = `<div style="color: var(--accent-rose); font-size: 0.8rem;">Simulation failed: ${err.message}</div>`;
  }
}

async function fetchNetworkBottlenecks() {
  const tbody = document.getElementById("network-bottlenecks-tbody");
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/api/network/bottlenecks`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const bottlenecks = json.data.bottlenecks || [];

    if (bottlenecks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No critical bottlenecks detected. Network has resilient multi-sourcing.</td></tr>`;
      return;
    }

    tbody.innerHTML = bottlenecks.map(b => {
      const spofBadge = b.is_spof
        ? `<span class="badge badge-critical">SPOF CRITICAL</span>`
        : `<span class="badge badge-warning">REDUNDANCY AT RISK</span>`;

      return `
        <tr>
          <td>
            <div style="font-weight: 600; color: var(--text-primary);">${b.label}</div>
            <span style="font-size: 0.7rem; color: var(--text-muted); font-family: var(--font-mono);">${b.id}</span>
          </td>
          <td>
            <span class="badge badge-normal" style="font-size: 0.65rem;">${b.node_type.replace(/_/g, " ")}</span>
          </td>
          <td style="text-align: center;">${spofBadge}</td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: ${b.fragility_index > 50 ? 'var(--accent-rose)' : 'var(--accent-amber)'};">
            ${b.fragility_index}
          </td>
          <td class="num-cell" style="text-align: right;">${b.betweenness_centrality}</td>
          <td class="num-cell" style="text-align: right; font-weight: 600;">${b.blast_radius_skus} SKUs</td>
          <td class="num-cell" style="text-align: right; font-weight: 700; color: var(--accent-emerald);">
            ₹${Number(b.revenue_exposure_inr || 0).toLocaleString()}
          </td>
          <td style="text-align: right;">
            <button class="btn btn-sm btn-primary" onclick="inspectNetworkNode('${b.id}')">
              Inspect Node
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--accent-rose); padding: 1.5rem;">Error loading bottlenecks: ${err.message}</td></tr>`;
  }
}

function initNetworkControls() {
  const filterSelect = document.getElementById("net-filter-type");
  if (filterSelect) filterSelect.addEventListener("change", renderNetworkTopologyGraph);

  const btnToggleSpof = document.getElementById("btn-toggle-spof-highlight");
  if (btnToggleSpof) {
    btnToggleSpof.addEventListener("click", () => {
      highlightSpofsOnly = !highlightSpofsOnly;
      btnToggleSpof.textContent = highlightSpofsOnly ? "Show All Nodes" : "Highlight SPOFs";
      btnToggleSpof.className = highlightSpofsOnly ? "btn btn-sm btn-danger" : "btn btn-sm";
      renderNetworkTopologyGraph();
    });
  }

  const btnRefresh = document.getElementById("btn-refresh-topology");
  if (btnRefresh) btnRefresh.addEventListener("click", fetchSupplyNetworkView);
}

function initCapitalControls() {
  const btnReb = document.getElementById("btn-run-rebalance");
  if (btnReb) {
    btnReb.addEventListener("click", () => {
      runCapitalRebalance();
    });
  }
}

function initObservabilityControls() {
  const btnReconcile = document.getElementById("btn-run-reconciliation");
  if (btnReconcile) {
    btnReconcile.addEventListener("click", () => {
      runSelfHealingReconciliation();
    });
  }

  const btnRefreshDrift = document.getElementById("btn-refresh-drift");
  if (btnRefreshDrift) {
    btnRefreshDrift.addEventListener("click", () => {
      fetchDemandDrift();
    });
  }

  const winSelect = document.getElementById("drift-window-select");
  if (winSelect) {
    winSelect.addEventListener("change", () => {
      fetchDemandDrift();
    });
  }
}

function initCommandPalette() {
  const overlay = document.getElementById("palette-overlay");
  const input = document.getElementById("palette-input");
  const results = document.getElementById("palette-results");
  const btnTrigger = document.getElementById("btn-open-palette");

  if (!overlay || !input || !results) return;

  const defaultCommands = [
    { title: "Command Center", subtitle: "Switch to executive operational command center", action: () => switchView("command-center"), tag: "NAV" },
    { title: "Inventory Workstation", subtitle: "Explore complete catalogue and stock buffers", action: () => switchView("inventory"), tag: "NAV" },
    { title: "Replenishment & POs", subtitle: "Review automated replenishment and purchase orders", action: () => switchView("replenishment"), tag: "NAV" },
    { title: "Audit Ledger", subtitle: "Inspect immutable stock movement ledger", action: () => switchView("audit-ledger"), tag: "NAV" },
    { title: "Suppliers Registry", subtitle: "Inspect Tier-1 and Tier-2 supplier directory", action: () => switchView("suppliers"), tag: "NAV" },
    { title: "Intelligence & 8D Risk", subtitle: "Evaluate multi-dimensional risk matrix and anomalies", action: () => switchView("intelligence"), tag: "NAV" },
    { title: "Resilience Lab", subtitle: "Run digital twin discrete-event shock simulations", action: () => switchView("resilience-lab"), tag: "NAV" },
    { title: "Supply Network Graph", subtitle: "Inspect 4-tier network graph and simulate outages", action: () => switchView("supply-network"), tag: "NAV" },
    { title: "Capital & Buffer Allocation", subtitle: "Run multi-echelon buffer rebalancing optimization", action: () => switchView("capital"), tag: "NAV" },
    { title: "Decision Ledger & Action Studio", subtitle: "Human-in-the-loop approvals and overrides", action: () => switchView("decision-ledger"), tag: "NAV" },
    { title: "System Observability & Health", subtitle: "Run self-healing reconciler and check drift", action: () => switchView("system-health"), tag: "NAV" },
    { title: "Run Self-Healing Integrity Audit", subtitle: "Execute automated database invariant reconciliation", action: () => { switchView("system-health"); runSelfHealingReconciliation(); }, tag: "ACTION" },
    { title: "Load Demo Scenarios", subtitle: "Seed 7 product personas with 90-day demand histories", action: () => { document.getElementById("btn-seed-data")?.click(); }, tag: "ACTION" },
    { title: "Run Replenishment Scan", subtitle: "Compute ROP and EOQ recommendations across catalogue", action: () => { switchView("replenishment"); document.getElementById("btn-scan-replenish")?.click(); }, tag: "ACTION" },
    { title: "Run Buffer Rebalancing", subtitle: "Optimize working capital allocation under target service level", action: () => { switchView("capital"); runCapitalRebalance(); }, tag: "ACTION" }
  ];

  function openPalette() {
    overlay.classList.add("active");
    input.value = "";
    renderPaletteItems(defaultCommands);
    setTimeout(() => input.focus(), 50);
  }

  function closePalette() {
    overlay.classList.remove("active");
  }

  function renderPaletteItems(items) {
    if (items.length === 0) {
      results.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted); font-size: 0.82rem;">No matching commands or products found.</div>`;
      return;
    }

    results.innerHTML = items.map((it, idx) => `
      <div class="palette-item" data-idx="${idx}">
        <div>
          <div style="font-weight: 600; color: var(--text-primary);">${it.title}</div>
          <div style="font-size: 0.72rem; color: var(--text-secondary);">${it.subtitle}</div>
        </div>
        <span class="palette-item-action">${it.tag} ↵</span>
      </div>
    `).join("");

    results.querySelectorAll(".palette-item").forEach((el, i) => {
      el.addEventListener("click", () => {
        items[i].action();
        closePalette();
      });
    });
  }

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    if (!q) {
      renderPaletteItems(defaultCommands);
      return;
    }

    // Filter built-in commands
    const matchedCommands = defaultCommands.filter(c => 
      c.title.toLowerCase().includes(q) || c.subtitle.toLowerCase().includes(q)
    );

    // Search cached products
    const matchedProducts = (productsCache || []).filter(p => 
      p.sku.toLowerCase().includes(q) || p.name.toLowerCase().includes(q)
    ).slice(0, 8).map(p => ({
      title: `${p.sku} — ${p.name}`,
      subtitle: `Qty: ${p.quantity} | ₹${p.price.toLocaleString()} | Category: ${p.category}`,
      action: () => { switchView("inventory"); openDetailDrawer(p.id); },
      tag: "SKU"
    }));

    renderPaletteItems([...matchedCommands, ...matchedProducts]);
  });

  // Keyboard Navigation: Ctrl+K / Cmd+K and Escape
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (overlay.classList.contains("active")) {
        closePalette();
      } else {
        openPalette();
      }
    } else if (e.key === "Escape" && overlay.classList.contains("active")) {
      closePalette();
    } else if (e.key === "Enter" && overlay.classList.contains("active")) {
      const firstItem = results.querySelector(".palette-item");
      if (firstItem) firstItem.click();
    }
  });

  if (btnTrigger) btnTrigger.addEventListener("click", openPalette);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closePalette();
  });
}

function initFutureHorizonTimeline() {
  const briefingText = document.getElementById("daily-briefing-text");
  const btnNow = document.getElementById("btn-horizon-now");
  const btn24h = document.getElementById("btn-horizon-24h");
  const btn7d = document.getElementById("btn-horizon-7d");
  const btn30d = document.getElementById("btn-horizon-30d");

  const horizonBriefings = {
    now: "REAL-TIME TRAJECTORY: System operating within calibrated tolerances. All 4 core database invariants actively verified. Movement balance synchronization active across active warehouses.",
    "24h": "T+24H PREDICTIVE HORIZON: 3 supplier purchase orders pending authorization in Action Studio. Expedited lead time requested for semiconductor microcontrollers.",
    "7d": "T+7D BUFFER VULNERABILITY: 2 critical SKUs approaching safety stock depletion. Automated ROP triggers scheduled to dispatch replenishments before assembly line interruption.",
    "30d": "T+30D STRATEGIC ALLOCATION: Projected ₹42,500 working capital harvestable from overstocked buffers via Multi-Echelon Buffer Rebalancing without compromising target 95% service level."
  };

  function setHorizon(key, btn) {
    [btnNow, btn24h, btn7d, btn30d].forEach(b => b && b.classList.remove("btn-primary"));
    if (btn) btn.classList.add("btn-primary");
    if (briefingText && horizonBriefings[key]) {
      briefingText.textContent = horizonBriefings[key];
    }
  }

  if (btnNow) btnNow.addEventListener("click", () => setHorizon("now", btnNow));
  if (btn24h) btn24h.addEventListener("click", () => setHorizon("24h", btn24h));
  if (btn7d) btn7d.addEventListener("click", () => setHorizon("7d", btn7d));
  if (btn30d) btn30d.addEventListener("click", () => setHorizon("30d", btn30d));

  setHorizon("now", btnNow);
}

// Helper to switch view programmatically
function switchView(viewId) {
  const navItems = document.querySelectorAll(".nav-item");
  const sections = document.querySelectorAll(".view-section");

  navItems.forEach(n => {
    if (n.getAttribute("data-view") === viewId) {
      n.classList.add("active");
    } else {
      n.classList.remove("active");
    }
  });

  sections.forEach(s => {
    if (s.id === `view-${viewId}`) {
      s.classList.add("active");
    } else {
      s.classList.remove("active");
    }
  });

  // Trigger data loader for view
  if (viewId === "command-center") {
    fetchPulse();
    fetchResilienceIndex();
    fetchAttentionQueue();
  } else if (viewId === "inventory") {
    fetchProducts();
  } else if (viewId === "replenishment") {
    fetchReplenishmentRecommendations();
    fetchPurchaseOrders();
  } else if (viewId === "audit-ledger") {
    fetchAuditLedger();
  } else if (viewId === "suppliers") {
    fetchSuppliers();
  } else if (viewId === "intelligence") {
    fetchAnomalies();
    fetchRisks();
  } else if (viewId === "resilience-lab") {
    fetchSimulationPresets();
  } else if (viewId === "supply-network") {
    fetchSupplyNetworkView();
  } else if (viewId === "capital") {
    fetchCapitalView();
  } else if (viewId === "decision-ledger") {
    fetchDecisionStudioView();
  } else if (viewId === "system-health") {
    checkHealth();
  }
}

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initCommandPalette();
  initFutureHorizonTimeline();
  initProductModal();
  initMovementModal();
  initDetailModal();
  initSupplierModal();
  initDecisionStudioModals();
  initCapitalControls();
  initObservabilityControls();
  initNetworkControls();
  initSearchAndFilters();

  // Initial Data Fetch
  checkHealth();
  fetchPulse();
  fetchResilienceIndex();
  fetchAttentionQueue();
  fetchProducts();

  // Periodic Telemetry Poll (every 10s)
  setInterval(checkHealth, 10000);
});

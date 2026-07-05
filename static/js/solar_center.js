const SOLAR_REFRESH_INTERVAL_MS = 30000;

async function refreshSolarCenter() {
  try {
    const [overview, history] = await Promise.all([
      fetchJSON("/api/solar/overview"),
      fetchSolarHistory(),
    ]);

    const solar = overview.status || {};
    const points = history.points || [];

    updateModuleBadge(solar);
    updateTopCards(solar);
    updateEnergySummary(solar);
    updateSystemDetails(solar);
    updateInverterSummary(solar);
    updateInverterTable(solar);
    renderProductionChart(points);
  } catch (error) {
    console.error("Solar Center refresh failed:", error);
    setElementText("solar-inverter-note", "Unable to load inverter data from Envoy at this time.");
  }
}

async function fetchSolarHistory() {
  const chart = document.getElementById("solar-production-chart");
  const range = window.HomePulseHistory?.selectedRange(chart) || "1d";
  return fetchJSON(`/api/history/metrics?module=solar&metric=current_production_kw&range=${encodeURIComponent(range)}`);
}

function renderProductionChart(points) {
  const chart = document.getElementById("solar-production-chart");
  const range = window.HomePulseHistory?.selectedRange(chart) || "1d";

  renderCenterChart(chart, points || [], {
    digits: 2,
    yLabel: "kW",
    unit: "kW",
    xLabel: "Time",
    range,
    emptyMessage: "No solar production history for this range.",
    onRangeChange: refreshSolarCenter,
  });
}

function updateModuleBadge(solar) {
  const status = solar.enabled ? (solar.status || "Unknown") : "Disabled";
  setElementText("solar-module-status-badge", status);

  const badge = document.getElementById("solar-module-status-badge");
  if (!badge) return;

  badge.className = "energy-status-badge";
  if (status === "Producing") badge.classList.add("charging");
  else if (status === "Standby / Night") badge.classList.add("idle");
  else if (status === "Disabled") badge.classList.add("disabled");
  else badge.classList.add("offline");
}

function updateTopCards(solar) {
  const status = solar.enabled ? (solar.status || "Unknown") : "Disabled";
  const envoyConnection = inferEnvoyConnection(solar);

  setElementText("solar-kpi-current", solar.enabled ? formatMetric(solar.current_production_kw, "kW", 2) : "Disabled");
  setElementText("solar-kpi-source", solar.source || "Enphase Envoy");

  setElementText("solar-kpi-today", formatMetric(solar.production_today_kwh, "kWh", 2));
  setElementText("solar-kpi-value", formatCurrency(solar.estimated_value_today));

  setElementText("solar-kpi-lifetime", formatMetric(solar.lifetime_production_mwh, "MWh", 3));
  setElementText("solar-kpi-updated", `Updated ${formatTimestamp(solar.last_updated)}`);

  setElementText("solar-kpi-status", status);
  setElementText("solar-kpi-envoy", envoyConnection);
}

function updateEnergySummary(solar) {
  setElementText("solar-summary-current", formatMetric(solar.current_production_kw, "kW", 2));
  setElementText("solar-summary-today", formatMetric(solar.production_today_kwh, "kWh", 2));
  setElementText("solar-summary-week", formatMetric(solar.production_last_7_days_kwh, "kWh", 2));
  setElementText("solar-summary-lifetime", formatMetric(solar.lifetime_production_mwh, "MWh", 3));
  setElementText("solar-summary-value", formatCurrency(solar.estimated_value_today));
  setElementText("solar-summary-rate", formatCurrency(solar.electricity_rate));
}

function updateSystemDetails(solar) {
  const status = solar.enabled ? (solar.status || "Unknown") : "Disabled";

  setElementText("solar-system-status", status);
  setElementText("solar-system-envoy", inferEnvoyConnection(solar));
  setElementText("solar-system-configured", solar.configured ? "Yes" : "No");
  setElementText("solar-system-source", solar.source || "Enphase Envoy");
  setElementText("solar-system-updated", formatTimestamp(solar.last_updated));
  setElementText("solar-system-message", solar.error || solar.message || "-");

  applyStatusClass("solar-system-status", status);
  applyStatusClass("solar-system-envoy", inferEnvoyConnection(solar));
}

function updateInverterSummary(solar) {
  const inverterDataAvailable = Boolean(solar.inverter_data_available);

  const installed = toNumberOrNull(solar.microinverters_installed);
  const online = toNumberOrNull(solar.microinverters_online);
  const offline = installed !== null && online !== null ? Math.max(installed - online, 0) : null;

  setElementText("solar-inverter-panels", inverterCountText(solar.panel_count, inverterDataAvailable));
  setElementText("solar-inverter-count", inverterCountText(solar.inverter_count, inverterDataAvailable));
  setElementText("solar-inverter-installed", inverterCountText(solar.microinverters_installed, inverterDataAvailable));
  setElementText("solar-inverter-online", inverterCountText(online, inverterDataAvailable));
  setElementText("solar-inverter-offline", inverterCountText(offline, inverterDataAvailable));

  const onlineText = inverterCountText(online, inverterDataAvailable);
  applyStatusClass("solar-inverter-online", onlineText);
  applyStatusClass("solar-inverter-offline", offline === 0 ? "ok" : offline > 0 ? "warning" : "unknown");

  const note = solar.inverter_data_message || (inverterDataAvailable
    ? "Inverter-level data is available from Envoy telemetry."
    : "Inverter-level data is not reported by Envoy.");
  setElementText("solar-inverter-note", note);
}

function updateInverterTable(solar) {
  const tbody = document.getElementById("solar-inverter-tbody");
  if (!tbody) return;

  const rows = Array.isArray(solar.inverters) ? solar.inverters : [];
  const inverterDataAvailable = Boolean(solar.inverter_data_available);

  if (!inverterDataAvailable) {
    tbody.innerHTML = '<tr><td colspan="3" class="table-empty">Not reported by Envoy</td></tr>';
    return;
  }

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="table-empty">Envoy did not provide per-inverter detail rows.</td></tr>';
    return;
  }

  tbody.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");

    const idCell = document.createElement("td");
    idCell.textContent = row.id || "Unknown";

    const statusCell = document.createElement("td");
    const statusSpan = document.createElement("span");
    const statusText = row.status || "Unknown";
    statusSpan.textContent = statusText;
    statusSpan.className = mapStatusClass(statusText);
    statusCell.appendChild(statusSpan);

    const lifetimeCell = document.createElement("td");
    lifetimeCell.textContent = formatMetric(row.lifetime_kwh, "kWh", 2);

    tr.appendChild(idCell);
    tr.appendChild(statusCell);
    tr.appendChild(lifetimeCell);
    tbody.appendChild(tr);
  }
}

function inferEnvoyConnection(solar) {
  if (!solar.enabled) return "Disabled";
  if (!solar.configured) return "Not configured";
  if (solar.error) return "Unavailable";
  if (solar.status === "Producing" || solar.status === "Standby / Night") return "Connected";
  return "Unknown";
}

function inverterCountText(value, isAvailable) {
  if (!isAvailable) return "Not reported by Envoy";
  const number = toNumberOrNull(value);
  return number === null ? "Not reported by Envoy" : String(number);
}

function toNumberOrNull(value) {
  const number = parseNumber(value);
  return number === null ? null : Math.round(number);
}

function applyStatusClass(id, status) {
  const element = document.getElementById(id);
  if (!element) return;
  element.classList.remove("status-ok", "status-warning", "status-error");
  const cssClass = mapStatusClass(status || "");
  if (cssClass) element.classList.add(cssClass);
}

document.addEventListener("DOMContentLoaded", () => {
  refreshSolarCenter();
  setInterval(refreshSolarCenter, SOLAR_REFRESH_INTERVAL_MS);
});

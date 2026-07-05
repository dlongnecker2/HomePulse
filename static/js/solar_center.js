const SOLAR_REFRESH_INTERVAL_MS = 30000;
const SOLAR_STATE = {
  perfView: "overlay",
  perfRange: "today",
  perfMetric: "power",
  chart: null,
};

async function fetchOverview() {
  return fetchJSON("/api/solar/overview");
}

async function fetchSolarHistory(targetId) {
  const chart = document.getElementById(targetId);
  const range = window.HomePulseHistory?.selectedRange(chart) || "1d";
  return fetchJSON(`/api/history/metrics?module=solar&metric=current_production_kw&range=${encodeURIComponent(range)}`);
}

async function refreshOverview() {
  const [overview, history] = await Promise.all([fetchOverview(), fetchSolarHistory("solar-overview-chart")]);
  const solar = overview.status || {};
  updateModuleBadge(solar);
  updateTopCards(solar);
  updateSystemDetails(solar);
  renderSolarChart("solar-overview-chart", history.points || []);
}

async function refreshProduction() {
  const [overview, history] = await Promise.all([fetchOverview(), fetchSolarHistory("solar-production-chart")]);
  const solar = overview.status || {};
  updateEnergySummary(solar);
  updateAnalytics(solar);
  renderSolarChart("solar-production-chart", history.points || []);
}

async function refreshInverterList() {
  const overview = await fetchOverview();
  const solar = overview.status || {};
  updateInverterSummary(solar);
  updateInverterTable(solar);
  updateInverterComparison(solar);
}

async function refreshWeather() {
  try {
    const weather = await fetchJSON("/api/weather/status");
    setElementText("solar-weather-condition", weather.condition || "-");
    setElementText("solar-weather-temp", weather.temperature_f !== undefined && weather.temperature_f !== null ? `${Number(weather.temperature_f).toFixed(1)}°F` : "-");
    setElementText("solar-weather-clouds", weather.cloud_cover_percent !== undefined && weather.cloud_cover_percent !== null ? `${Number(weather.cloud_cover_percent).toFixed(0)}%` : "-");
    setElementText("solar-weather-wind", weather.wind_mph !== undefined && weather.wind_mph !== null ? `${Number(weather.wind_mph).toFixed(1)} mph` : "-");
    setElementText("solar-weather-sunrise", weather.sunrise || "-");
    setElementText("solar-weather-sunset", weather.sunset || "-");
  } catch (error) {
    console.error("Solar weather refresh failed:", error);
  }
}

async function refreshInverterPerformance() {
  try {
    const response = await fetchJSON(`/api/solar/inverters/performance?range=${encodeURIComponent(SOLAR_STATE.perfRange)}&metric=${encodeURIComponent(SOLAR_STATE.perfMetric)}`);
    renderPerformancePayload(response || {});
  } catch (error) {
    console.error("Inverter performance refresh failed:", error);
    setElementText("solar-inverter-performance-message", "Unable to load inverter performance telemetry.");
  }
}

function renderSolarChart(targetId, points) {
  const chart = document.getElementById(targetId);
  const range = window.HomePulseHistory?.selectedRange(chart) || "1d";
  renderCenterChart(chart, points || [], {
    digits: 2,
    yLabel: "kW",
    unit: "kW",
    xLabel: "Time",
    range,
    emptyMessage: "No solar production history for this range.",
    onRangeChange: () => {
      if (targetId === "solar-overview-chart") refreshOverview();
      else refreshProduction();
    },
  });
}

function renderPerformancePayload(payload) {
  const message = payload.chart_message || payload.message || payload.reason || "Inverter performance data loaded.";
  setElementText("solar-inverter-performance-title", payload.chart_title || "Current Inverter Performance");
  setElementText("solar-inverter-performance-message", message);
  updatePerformanceModeControls(payload.chart_type || "none");
  updateSnapshotNote(payload.chart_type || "none");
  const waiting = Boolean(payload.waiting_for_more_samples);
  if (waiting) {
    const note = document.getElementById("solar-inverter-snapshot-note");
    if (note) {
      note.hidden = false;
      note.textContent = "Waiting for more samples.";
    }
  }
  updatePerformanceLegend(payload);
  updatePerformanceSummary(payload.summary || []);
  updatePerformanceInsights(payload.insights || []);
  renderPerformanceChart(payload);
}

function renderPerformanceChart(payload) {
  const canvas = document.getElementById("solar-inverter-performance-canvas");
  if (!canvas || !window.Chart) return;

  const chartType = payload.chart_type || "none";
  if (chartType === "none") {
    if (SOLAR_STATE.chart) {
      SOLAR_STATE.chart.destroy();
      SOLAR_STATE.chart = null;
    }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const ctx = canvas.getContext("2d");
  if (SOLAR_STATE.chart) SOLAR_STATE.chart.destroy();

  if (chartType === "line") {
    const visibleSeries = (payload.series || []).slice(0, 6);
    const labels = (visibleSeries[0]?.points || []).map((point) => point.timestamp || point.label || "");
    const datasets = visibleSeries.map((series, idx) => ({
      label: series.inverter_id,
      data: (series.points || []).map((point) => point.value),
      borderColor: paletteColor(idx),
      backgroundColor: `${paletteColor(idx)}55`,
      borderWidth: 2,
      tension: 0.2,
      fill: SOLAR_STATE.perfView === "stacked",
      stack: SOLAR_STATE.perfView === "stacked" ? "inverters" : undefined,
    }));

    SOLAR_STATE.chart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: "#c7d4e5" } },
          y: {
            stacked: SOLAR_STATE.perfView === "stacked",
            ticks: { color: "#c7d4e5" },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
    return;
  }

  const values = (payload.values || []).slice(0, 12);
  const labels = values.map((item) => item.label || item.inverter_id || "Unknown");
  const data = values.map((item) => item.value ?? null);
  const colors = values.map((_, idx) => `${paletteColor(idx)}aa`);

  SOLAR_STATE.chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: payload.metric || "value",
        data,
        backgroundColor: colors,
        borderColor: colors.map((color) => color.replace("aa", "ff")),
        borderWidth: 1,
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#c7d4e5" } },
        y: { ticks: { color: "#c7d4e5" } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

function updatePerformanceLegend(payload) {
  const element = document.getElementById("solar-inverter-legend");
  if (!element) return;
  const chartType = payload.chart_type || "none";
  let ids = [];

  if (chartType === "line") {
    ids = (payload.series || []).map((item) => item.inverter_id).filter(Boolean);
  } else if (chartType === "bar") {
    ids = (payload.values || []).map((item) => item.inverter_id || item.label).filter(Boolean);
  }

  const inverters = ids.length > 0 ? ids : (payload.inverters || []);
  if (!inverters || inverters.length === 0) {
    element.textContent = "Legend: No inverter IDs reported.";
    return;
  }

  const visible = inverters.slice(0, 6);
  const more = inverters.length - visible.length;
  let text = `Legend: ${visible.join(", ")}`;
  if (more > 0) text += ` + ${more} more`;
  element.textContent = text;
}

function updateSnapshotNote(chartType) {
  const note = document.getElementById("solar-inverter-snapshot-note");
  if (!note) return;
  if (chartType === "none") {
    note.hidden = false;
    note.textContent = "HomePulse is now building inverter history. The graph will become more useful as samples are collected.";
  } else if (chartType === "bar") {
    note.hidden = false;
    note.textContent = "Envoy is reporting current inverter telemetry, but not historical per-inverter series. Showing current inverter comparison instead.";
  } else {
    note.hidden = true;
    note.textContent = "";
  }
}

function updatePerformanceModeControls(chartType) {
  const overlay = document.getElementById("perf-view-overlay");
  const stacked = document.getElementById("perf-view-stacked");
  const lineMode = chartType === "line";
  if (overlay) {
    overlay.disabled = !lineMode;
    overlay.classList.toggle("active", lineMode && SOLAR_STATE.perfView === "overlay");
  }
  if (stacked) {
    stacked.disabled = !lineMode;
    stacked.classList.toggle("active", lineMode && SOLAR_STATE.perfView === "stacked");
  }
  if (!lineMode) {
    SOLAR_STATE.perfView = "overlay";
  }
}

function updatePerformanceSummary(rows) {
  const tbody = document.getElementById("solar-inverter-performance-summary");
  if (!tbody) return;

  if (!rows || rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="table-empty">No inverter performance summary available.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((row) => {
    return `<tr>
      <td>${row.inverter_id || "Unknown"}</td>
      <td><span class="${mapStatusClass(row.status || "Unknown")}">${row.status || "Unknown"}</span></td>
      <td>${formatMaybeMetric(row.peak_power, "W")}</td>
      <td>${formatMaybeMetric(row.energy, "kWh")}</td>
      <td>${row.performance_percent !== null && row.performance_percent !== undefined ? `${row.performance_percent.toFixed(1)}%` : "-"}</td>
    </tr>`;
  }).join("");
}

function updatePerformanceInsights(insights) {
  const container = document.getElementById("solar-inverter-insights");
  if (!container) return;

  if (!insights || insights.length === 0) {
    container.innerHTML = '<div><span>Unknown</span><strong>No insights available.</strong></div>';
    return;
  }

  container.innerHTML = insights.map((insight) => {
    const title = insight.title || "Insight";
    const message = insight.message || "-";
    return `<div><span>${title}</span><strong>${message}</strong></div>`;
  }).join("");
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
}

function updateAnalytics(solar) {
  setElementText("solar-analytics-value", formatCurrency(solar.estimated_value_today));
  setElementText("solar-analytics-week-value", formatCurrency(solar.estimated_value_last_7_days));
  setElementText("solar-analytics-lifetime-value", formatCurrency(solar.estimated_lifetime_value));

  const week = parseNumber(solar.production_last_7_days_kwh);
  const avg = week !== null ? week / 7 : null;
  setElementText("solar-analytics-avg", avg !== null ? formatMetric(avg, "kWh", 2) : "-");
}

function updateInverterSummary(solar) {
  const inverterDataAvailable = Boolean(solar.inverter_data_available);
  const rows = Array.isArray(solar.inverters) ? solar.inverters : [];
  const online = rows.filter((row) => row.status === "Online").length;
  const offline = rows.filter((row) => row.status === "Offline").length;

  setElementText("solar-inverter-panels", inverterCountText(solar.panel_count, inverterDataAvailable));
  setElementText("solar-inverter-count", inverterCountText(solar.inverter_count, inverterDataAvailable));
  setElementText("solar-inverter-installed", inverterCountText(solar.microinverters_installed, inverterDataAvailable));
  setElementText("solar-inverter-online", inverterCountText(online > 0 ? online : solar.microinverters_online, inverterDataAvailable));
  setElementText("solar-inverter-offline", inverterCountText(offline > 0 ? offline : null, inverterDataAvailable));

  const note = solar.inverter_data_message || (
    inverterDataAvailable
      ? "Per-inverter availability is reported by Envoy telemetry and may not match panel-level health in the Enphase app."
      : "Inverter-level data is not reported by Envoy."
  );
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

  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.id || "Unknown"}</td>
      <td><span class="${mapStatusClass(row.status || "Unknown")}">${row.status || "Unknown"}</span></td>
      <td>${formatMaybeMetric(row.lifetime_kwh, "kWh")}</td>
    </tr>
  `).join("");
}

function updateInverterComparison(solar) {
  const tbody = document.getElementById("solar-inverter-comparison-table");
  if (!tbody) return;
  const rows = Array.isArray(solar.inverters) ? solar.inverters : [];

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="table-empty">No inverter comparison data available.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.id || "Unknown"}</td>
      <td><span class="${mapStatusClass(row.status || "Unknown")}">${row.status || "Unknown"}</span></td>
      <td>${row.reported_state !== undefined && row.reported_state !== null ? String(row.reported_state) : "-"}</td>
      <td>${formatMaybeMetric(row.lifetime_kwh, "kWh")}</td>
    </tr>
  `).join("");
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
  const number = parseNumber(value);
  return number === null ? "Not reported by Envoy" : String(Math.round(number));
}

function formatMaybeMetric(value, unit) {
  const number = parseNumber(value);
  if (number === null) return "-";
  return `${number.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 0 })} ${unit}`;
}

function paletteColor(index) {
  const colors = ["#58b5ef", "#7ead4d", "#f7c76b", "#f97316", "#c084fc", "#22d3ee", "#ef4444", "#14b8a6"];
  return colors[index % colors.length];
}

function setupInverterSubtabs() {
  const buttons = Array.from(document.querySelectorAll("[data-inverter-subtab]"));
  const panels = Array.from(document.querySelectorAll("[data-inverter-panel]"));

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.inverterSubtab;
      buttons.forEach((candidate) => candidate.classList.toggle("active", candidate === button));
      panels.forEach((panel) => {
        const active = panel.dataset.inverterPanel === tab;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
      if (tab === "performance") refreshInverterPerformance();
    });
  });
}

function setupPerformanceControls() {
  const overlay = document.getElementById("perf-view-overlay");
  const stacked = document.getElementById("perf-view-stacked");
  const refresh = document.getElementById("perf-refresh");

  if (overlay && stacked) {
    overlay.addEventListener("click", () => {
      SOLAR_STATE.perfView = "overlay";
      overlay.classList.add("active");
      stacked.classList.remove("active");
      refreshInverterPerformance();
    });
    stacked.addEventListener("click", () => {
      SOLAR_STATE.perfView = "stacked";
      stacked.classList.add("active");
      overlay.classList.remove("active");
      refreshInverterPerformance();
    });
  }

  document.querySelectorAll("[data-perf-range]").forEach((button) => {
    button.addEventListener("click", () => {
      SOLAR_STATE.perfRange = button.dataset.perfRange;
      document.querySelectorAll("[data-perf-range]").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
      refreshInverterPerformance();
    });
  });

  document.querySelectorAll("[data-perf-metric]").forEach((button) => {
    button.addEventListener("click", () => {
      SOLAR_STATE.perfMetric = button.dataset.perfMetric;
      document.querySelectorAll("[data-perf-metric]").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
      refreshInverterPerformance();
    });
  });

  if (refresh) {
    refresh.addEventListener("click", () => {
      refreshInverterPerformance();
    });
  }
}

async function loadCenterPanel(tab) {
  try {
    if (tab === "overview") await refreshOverview();
    else if (tab === "production") await refreshProduction();
    else if (tab === "inverters") {
      await refreshInverterList();
      await refreshInverterPerformance();
    } else if (tab === "weather") await refreshWeather();
    else if (tab === "analytics") {
      const overview = await fetchOverview();
      updateAnalytics(overview.status || {});
    } else if (tab === "system_health") {
      const overview = await fetchOverview();
      updateSystemDetails(overview.status || {});
    }
  } catch (error) {
    console.error(`Solar Center tab ${tab} failed:`, error);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  setupCenterTabs((tab) => {
    loadCenterPanel(tab);
  });
  setupInverterSubtabs();
  setupPerformanceControls();

  await refreshOverview();
  setInterval(() => {
    refreshOverview();
  }, SOLAR_REFRESH_INTERVAL_MS);
});

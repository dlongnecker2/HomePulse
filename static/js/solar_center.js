// ============================================================================
// SOLAR CENTER - Gold Standard Implementation
// ============================================================================
// Reusable modular JS for Solar Center with 5 functional tabs
// Serves as template for Vehicle, Internet, Energy, Weather Centers
// ============================================================================

const SOLAR_STATE = {
  data: {},
  history: {},
  lastUpdate: null,
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function solarSetText(id, value, fallback = "-") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}

function solarNumber(value) {
  if (value === null || value === undefined) return null;
  const number = Number(String(value).replace(/[$,%]/g, "").trim());
  return Number.isFinite(number) ? number : null;
}

function solarMetric(value, unit, digits = 2) {
  const number = solarNumber(value);
  if (number === null) return "-";
  return `${number.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${unit}`;
}

function solarCurrency(value) {
  const number = solarNumber(value);
  if (number === null) return "-";
  return `$${number.toFixed(2)}`;
}

function solarPercent(value) {
  const number = solarNumber(value);
  if (number === null) return "-";
  return `${number.toFixed(0)}%`;
}

function solarTimestamp(value) {
  if (!value) return "-";
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleTimeString();
}

function solarTrend(current, previous) {
  if (current === null || previous === null || previous === 0) return "→";
  const pct = ((current - previous) / previous) * 100;
  if (pct > 5) return "↑";
  if (pct < -5) return "↓";
  return "→";
}

function statusClass(status) {
  if (!status) return "";
  const normalized = String(status).toLowerCase();
  if (normalized.includes("online") || normalized.includes("ok") || normalized.includes("producing")) return "status-ok";
  if (normalized.includes("offline") || normalized.includes("error") || normalized.includes("unavailable")) return "status-error";
  return "status-warning";
}

// ============================================================================
// TAB MANAGEMENT
// ============================================================================

function setupSolarTabs() {
  document.querySelectorAll("[data-solar-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.solarTab;
      document.querySelectorAll("[data-solar-tab]").forEach((b) => b.classList.toggle("active", b === button));
      document.querySelectorAll("[data-solar-panel]").forEach((panel) => {
        const active = panel.dataset.solarPanel === tab;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
      // Load tab-specific data on demand
      loadTabData(tab);
    });
  });
}

async function loadTabData(tab) {
  switch (tab) {
    case "overview":
      refreshOverviewTab();
      break;
    case "health":
      refreshHealthTab();
      break;
    case "production":
      refreshProductionTab();
      break;
    case "weather":
      refreshWeatherTab();
      break;
    case "analytics":
      refreshAnalyticsTab();
      break;
  }
}

// ============================================================================
// TAB 1: OVERVIEW
// ============================================================================

async function refreshOverviewTab() {
  try {
    const [overview, history, weather] = await Promise.all([
      fetch("/api/solar/overview", { cache: "no-store" }),
      fetch("/api/history/metrics?module=solar&metric=current_production_kw&range=1d", { cache: "no-store" }),
      fetch("/api/weather/status", { cache: "no-store" }),
    ]);

    const overviewData = overview.ok ? await overview.json() : {};
    const historyData = history.ok ? await history.json() : {};
    const weatherData = weather.ok ? await weather.json() : {};

    const solar = overviewData.status || {};
    SOLAR_STATE.data = solar;
    SOLAR_STATE.history = historyData.points || [];

    updateOverviewUI(solar);
    renderOverviewChart(historyData.points || []);
  } catch (error) {
    console.error("Overview tab error:", error);
  }
}

function updateOverviewUI(solar) {
  const status = solar.enabled ? solar.status || "Unknown" : "Disabled";
  const updated = solarTimestamp(solar.last_updated);

  solarSetText("solar-overview-name", solar.name || "Solar Center");
  solarSetText("solar-overview-badge", status);
  solarSetText("solar-overview-current", solar.enabled ? solarMetric(solar.current_production_kw, "kW", 2) : "Disabled");
  solarSetText("solar-overview-today", solarMetric(solar.production_today_kwh, "kWh", 2));
  solarSetText("solar-overview-week", solarMetric(solar.production_last_7_days_kwh, "kWh", 2));
  solarSetText("solar-overview-lifetime", solarMetric(solar.lifetime_production_mwh, "MWh", 3));
  solarSetText("solar-overview-value", solarCurrency(solar.estimated_value_today));
  solarSetText("solar-overview-source", solar.source || "Enphase Envoy");
  solarSetText("solar-overview-updated", updated);

  // Trend indicator
  const prev = solar.production_yesterday_kwh || 0;
  const curr = solar.production_today_kwh || 0;
  const trend = solarTrend(curr, prev);
  solarSetText("solar-overview-trend", trend);

  // Update badge color
  const badge = document.getElementById("solar-overview-badge");
  if (badge) {
    badge.className = "energy-status-badge";
    if (status === "Producing") badge.classList.add("charging");
    else if (status === "Standby" || status === "Night") badge.classList.add("idle");
    else if (status === "Disabled") badge.classList.add("disabled");
    else badge.classList.add("offline");
  }
}

function renderOverviewChart(points) {
  const chart = document.getElementById("solar-overview-chart");
  if (!chart || !window.HomePulseHistory) return;
  
  window.HomePulseHistory.renderLineChart(chart, normalizeHistoryPoints(points), {
    digits: 2,
    yLabel: "kW",
    unit: "kW",
    xLabel: "Time",
    range: "1d",
    emptyMessage: "No production data available yet.",
  });
}

// ============================================================================
// TAB 2: SYSTEM HEALTH
// ============================================================================

async function refreshHealthTab() {
  try {
    const response = await fetch("/api/solar/overview", { cache: "no-store" });
    const data = response.ok ? await response.json() : {};
    const solar = data.status || {};

    updateHealthUI(solar);
  } catch (error) {
    console.error("Health tab error:", error);
  }
}

function updateHealthUI(solar) {
  // Gateway & Envoy Status
  solarSetText("solar-health-gateway", solar.gateway_status || "Unknown");
  solarSetText("solar-health-firmware", solar.firmware_version || "-");
  solarSetText("solar-health-envoy", solar.envoy_status || "Unknown");
  solarSetText("solar-health-cloud", solar.cloud_status || "Connected");

  // Inverter counts
  const installed = solar.microinverters_installed || 0;
  const online = solar.microinverters_online || 0;
  const offline = installed - online;

  solarSetText("solar-health-installed", String(installed));
  solarSetText("solar-health-online", String(online));
  solarSetText("solar-health-offline", String(offline));

  // Performance
  solarSetText("solar-health-power", solarMetric(solar.current_production_kw, "kW", 2));
  solarSetText("solar-health-peak-today", solarMetric(solar.peak_power_today_kw, "kW", 2));
  solarSetText("solar-health-peak-month", solarMetric(solar.peak_power_month_kw, "kW", 2));
  solarSetText("solar-health-lifetime", solarMetric(solar.lifetime_production_mwh, "MWh", 3));

  // Inverter table (if available)
  updateInverterTable(solar.inverters || []);
}

function updateInverterTable(inverters) {
  const tbody = document.getElementById("solar-health-inverter-tbody");
  if (!tbody) return;

  if (!inverters || inverters.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="table-empty">No inverter data available</td></tr>';
    return;
  }

  tbody.innerHTML = inverters
    .map(
      (inv) =>
        `<tr>
        <td>${inv.id || "Unknown"}</td>
        <td><span class="${statusClass(inv.status)}">${inv.status || "Unknown"}</span></td>
        <td>${solarMetric(inv.lifetime_kwh, "kWh", 2)}</td>
      </tr>`
    )
    .join("");
}

// ============================================================================
// TAB 3: PRODUCTION
// ============================================================================

async function refreshProductionTab() {
  const chart = document.getElementById("solar-production-chart");
  const range = window.HomePulseHistory?.selectedRange(chart) || "1d";

  try {
    const [overview, history] = await Promise.all([
      fetch("/api/solar/overview", { cache: "no-store" }),
      fetch(`/api/history/metrics?module=solar&metric=current_production_kw&range=${encodeURIComponent(range)}`, {
        cache: "no-store",
      }),
    ]);

    const overviewData = overview.ok ? await overview.json() : {};
    const historyData = history.ok ? await history.json() : {};
    const solar = overviewData.status || {};

    updateProductionUI(solar, historyData.points || [], range);
    renderProductionChart(historyData.points || [], range);
  } catch (error) {
    console.error("Production tab error:", error);
  }
}

function updateProductionUI(solar, points, range) {
  const stats = calculateProductionStats(points);

  solarSetText("solar-prod-peak", solarMetric(stats.peak, "kW", 2));
  solarSetText("solar-prod-avg", solarMetric(stats.avg, "kW", 2));
  solarSetText("solar-prod-total", solarMetric(stats.total, "kWh", 2));

  solarSetText("solar-prod-today", solarMetric(solar.production_today_kwh, "kWh", 2));
  solarSetText("solar-prod-yesterday", solarMetric(solar.production_yesterday_kwh, "kWh", 2));
  solarSetText("solar-prod-week", solarMetric(solar.production_last_7_days_kwh, "kWh", 2));
  solarSetText("solar-prod-month", solarMetric(solar.production_last_30_days_kwh, "kWh", 2));

  // Estimate annual
  const dailyAvg = stats.total || 0;
  const annualEst = dailyAvg * 365;
  solarSetText("solar-prod-annual", solarMetric(annualEst, "MWh", 2));
}

function calculateProductionStats(points) {
  if (!points || points.length === 0) return { peak: 0, avg: 0, total: 0 };

  const values = points.map((p) => solarNumber(p.value || p.kwh) || 0).filter((v) => v >= 0);
  if (values.length === 0) return { peak: 0, avg: 0, total: 0 };

  const peak = Math.max(...values);
  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  const total = values.reduce((a, b) => a + b, 0);

  return { peak, avg, total };
}

function renderProductionChart(points, range) {
  const chart = document.getElementById("solar-production-chart");
  if (!chart || !window.HomePulseHistory) return;

  window.HomePulseHistory.renderLineChart(chart, normalizeHistoryPoints(points), {
    digits: 2,
    yLabel: "kW",
    unit: "kW",
    xLabel: "Time",
    range,
    emptyMessage: "No production history for this range.",
    onRangeChange: refreshProductionTab,
  });
}

// ============================================================================
// TAB 4: WEATHER
// ============================================================================

async function refreshWeatherTab() {
  try {
    const [weather, history] = await Promise.all([
      fetch("/api/weather/status", { cache: "no-store" }),
      fetch("/api/history/metrics?module=solar&metric=current_production_kw&range=1d", { cache: "no-store" }),
    ]);

    const weatherData = weather.ok ? await weather.json() : {};
    const historyData = history.ok ? await history.json() : {};

    updateWeatherUI(weatherData);
    renderWeatherCorrelationChart(historyData.points || []);
    updateWeatherImpact(weatherData, historyData.points || []);
  } catch (error) {
    console.error("Weather tab error:", error);
  }
}

function updateWeatherUI(weather) {
  solarSetText("solar-weather-condition", weather.condition || "-");
  solarSetText("solar-weather-temp", weather.temperature_f ? `${weather.temperature_f.toFixed(1)}°F` : "-");
  solarSetText("solar-weather-feels", weather.feels_like_f ? `${weather.feels_like_f.toFixed(1)}°F` : "-");
  solarSetText("solar-weather-humidity", solarPercent(weather.humidity_percent));
  solarSetText("solar-weather-wind", weather.wind_mph ? `${weather.wind_mph.toFixed(1)} mph` : "-");
  solarSetText("solar-weather-clouds", solarPercent(weather.cloud_cover_percent));
  solarSetText("solar-weather-pressure", weather.pressure_mb ? `${weather.pressure_mb.toFixed(1)} mb` : "-");
  solarSetText("solar-weather-visibility", weather.visibility_miles ? `${weather.visibility_miles.toFixed(1)} mi` : "-");
  solarSetText("solar-weather-uv", weather.uv_index !== undefined ? String(weather.uv_index) : "-");
  solarSetText("solar-weather-sunrise", weather.sunrise || "-");
  solarSetText("solar-weather-sunset", weather.sunset || "-");

  if (weather.sunrise && weather.sunset) {
    const start = new Date(`2000-01-01 ${weather.sunrise}`);
    const end = new Date(`2000-01-01 ${weather.sunset}`);
    const hours = (end - start) / 3600000;
    solarSetText("solar-weather-daylight", `${hours.toFixed(1)} hrs`);
  }
}

function renderWeatherCorrelationChart(points) {
  const chart = document.getElementById("solar-weather-chart");
  if (!chart || !window.HomePulseHistory) return;

  window.HomePulseHistory.renderLineChart(chart, normalizeHistoryPoints(points), {
    digits: 2,
    yLabel: "kW",
    unit: "kW",
    xLabel: "Time",
    range: "1d",
    emptyMessage: "Collecting correlation data...",
  });
}

function updateWeatherImpact(weather, points) {
  const element = document.getElementById("solar-weather-impact");
  if (!element) return;

  const cloudCover = weather.cloud_cover_percent || 0;
  const impact = calculateWeatherImpact(cloudCover, points);
  element.textContent = impact;
}

function calculateWeatherImpact(cloudCover, points) {
  if (cloudCover === null || cloudCover === undefined) {
    return "Insufficient historical data.";
  }

  if (cloudCover > 80) {
    return `Cloud cover reduced estimated production by approximately ${(cloudCover - 20).toFixed(0)}%.`;
  } else if (cloudCover > 50) {
    return `Cloud cover reduced estimated production by approximately ${(cloudCover / 3).toFixed(0)}%.`;
  } else if (cloudCover > 20) {
    return `Light cloud cover has minimal impact on production (approximately ${(cloudCover / 5).toFixed(0)}% reduction).`;
  } else {
    return "Excellent conditions with minimal cloud cover. Full production potential expected.";
  }
}

// ============================================================================
// TAB 5: ANALYTICS
// ============================================================================

async function refreshAnalyticsTab() {
  try {
    const response = await fetch("/api/solar/overview", { cache: "no-store" });
    const data = response.ok ? await response.json() : {};
    const solar = data.status || {};

    updateAnalyticsUI(solar);
  } catch (error) {
    console.error("Analytics tab error:", error);
  }
}

function updateAnalyticsUI(solar) {
  const rates = {
    kwh_to_co2_lbs: 0.92, // Average CO2 per kWh
    trees_per_year_lbs: 48, // Lbs per tree per year
    ev_miles_per_kwh: 4, // Miles per kWh for EV
  };

  // KPI Cards
  updateAnalyticsKPI("today", solar.production_today_kwh, solar.estimated_value_today);
  updateAnalyticsKPI("yesterday", solar.production_yesterday_kwh, null);
  updateAnalyticsKPI("week", solar.production_last_7_days_kwh, null);
  updateAnalyticsKPI("month", solar.production_last_30_days_kwh, null);
  updateAnalyticsKPI("lifetime", solar.lifetime_production_mwh, null);

  // Performance Details
  solarSetText("solar-analytics-best-day", solarMetric(solar.best_production_day_kwh, "kWh", 2));
  solarSetText("solar-analytics-avg-daily", solarMetric(solar.average_daily_production_kwh, "kWh", 2));
  solarSetText("solar-analytics-best-hour", solarMetric(solar.peak_power_today_kw, "kW", 2));
  solarSetText("solar-analytics-peak", solarMetric(solar.current_production_kw, "kW", 2));

  // Environmental Impact
  const lifetimeKwh = (solar.lifetime_production_mwh || 0) * 1000;
  const co2Lbs = lifetimeKwh * rates.kwh_to_co2_lbs;
  const trees = co2Lbs / rates.trees_per_year_lbs;
  const evMiles = lifetimeKwh * rates.ev_miles_per_kwh;

  solarSetText("solar-analytics-co2", `${(co2Lbs / 1000).toFixed(1)}K lbs`);
  solarSetText("solar-analytics-trees", `${trees.toFixed(0)} trees`);
  solarSetText("solar-analytics-ev-miles", `${(evMiles / 1000).toFixed(0)}K miles`);
}

function updateAnalyticsKPI(prefix, kwh, value) {
  const kwhValue = solarMetric(kwh, "kWh", 2);
  const dollarValue = value ? solarCurrency(value) : solarCurrency((kwh || 0) * 0.13);

  solarSetText(`solar-analytics-${prefix}`, kwhValue);
  solarSetText(`solar-analytics-${prefix}-value`, dollarValue);
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function normalizeHistoryPoints(points) {
  if (!Array.isArray(points)) return [];
  return points
    .map((point) => ({
      label: point.label || shortTime(point.timestamp),
      value: point.value ?? point.kwh,
      unit: point.unit || "kW",
    }))
    .filter((point) => solarNumber(point.value) !== null);
}

function shortTime(timestamp) {
  if (!timestamp || String(timestamp).length < 16) return "";
  return String(timestamp).slice(11, 16);
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  setupSolarTabs();
  refreshOverviewTab();
  setInterval(refreshOverviewTab, 30000);
});

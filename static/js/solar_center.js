const SOLAR_EMPTY = "-";

function solarSetText(id, value, fallback = SOLAR_EMPTY) {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}

function solarNumber(value) {
  if (value === null || value === undefined) return null;
  const number = Number(String(value).replace("$", "").replace(",", "").trim());
  return Number.isFinite(number) ? number : null;
}

function solarMetric(value, unit, digits = 2) {
  const number = solarNumber(value);
  if (number === null) return SOLAR_EMPTY;
  return `${number.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${unit}`;
}

function solarCurrency(value) {
  const number = solarNumber(value);
  if (number === null) return SOLAR_EMPTY;
  return `$${number.toFixed(2)}`;
}

function solarTimestamp(value) {
  if (!value) return SOLAR_EMPTY;
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? SOLAR_EMPTY : parsed.toLocaleString();
}

function setupSolarTabs() {
  document.querySelectorAll("[data-solar-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.solarTab;
      document.querySelectorAll("[data-solar-tab]").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll("[data-solar-panel]").forEach((panel) => {
        const active = panel.dataset.solarPanel === tab;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
    });
  });
}

async function refreshSolarCenterOverview() {
  try {
    const [overviewResponse, historyResponse, weatherResponse] = await Promise.all([
      fetch("/api/solar/overview", { cache: "no-store" }),
      fetch("/api/history/metrics?module=solar&metric=current_production_kw&hours=24", { cache: "no-store" }),
      fetch("/api/weather/status", { cache: "no-store" }),
    ]);
    const overview = overviewResponse.ok ? await overviewResponse.json() : {};
    const history = historyResponse.ok ? await historyResponse.json() : {};
    const weather = weatherResponse.ok ? await weatherResponse.json() : {};
    const solar = overview.status || {};
    updateSolarOverview(solar);
    renderSolarProductionChart(history.points || overview.production_chart || []);
    updateWeatherPanel(weather, solar);
    updateForecastPlaceholder(weather);
  } catch (error) {
    solarSetText("solar-overview-message", "Solar Center data is taking longer than expected. The page will keep trying.");
    renderSolarProductionChart([]);
  }
}

function updateSolarOverview(data) {
  const status = data.enabled ? data.status || "Unknown" : "Disabled";
  const updated = solarTimestamp(data.last_updated);
  solarSetText("solar-module-name", data.name || "Solar Center");
  solarSetText("solar-module-status-badge", status);
  solarSetText("solar-overview-status", status);
  solarSetText("solar-summary-status", status);
  solarSetText("solar-overview-current", data.enabled ? solarMetric(data.current_production_kw, "kW", 2) : "Disabled");
  solarSetText("solar-overview-today", solarMetric(data.production_today_kwh, "kWh", 2));
  solarSetText("solar-overview-week", solarMetric(data.production_last_7_days_kwh, "kWh", 2));
  solarSetText("solar-overview-lifetime", solarMetric(data.lifetime_production_mwh, "MWh", 3));
  solarSetText("solar-overview-value", solarCurrency(data.estimated_value_today));
  solarSetText("solar-overview-message", data.message || "Solar Center is waiting for data.");
  solarSetText("solar-overview-source", data.source || "Enphase Envoy");
  solarSetText("solar-overview-updated", updated);
  solarSetText("solar-health-status", status);
  solarSetText("solar-health-source", data.source || "Enphase Envoy");
  solarSetText("solar-health-updated", updated);
  solarSetText("solar-health-power", solarMetric(data.current_production_kw, "kW", 2));
  solarSetText("solar-health-ct", solarMetric(data.production_ct_power_kw, "kW", 2));
  solarSetText("solar-health-entity", data.error ? "Partial data" : data.configured ? "Entities responding" : "Not configured");
  updateSolarBadges(status);
}

function updateSolarBadges(status) {
  ["solar-module-status-badge", "solar-overview-status"].forEach((id) => {
    const badge = document.getElementById(id);
    if (!badge) return;
    badge.className = "energy-status-badge";
    if (status === "Producing") badge.classList.add("charging");
    else if (status === "Standby / Night") badge.classList.add("idle");
    else if (status === "Disabled") badge.classList.add("disabled");
    else badge.classList.add("offline");
  });
}

function renderSolarProductionChart(points) {
  const chart = document.getElementById("solar-production-chart");
  if (!chart) return;
  if (window.HomePulseHistory?.renderLineChart) {
    window.HomePulseHistory.renderLineChart(chart, normalizeHistoryPoints(points), {
      digits: 2,
      yLabel: "kW",
      unit: "kW",
      xLabel: "Time",
      emptyMessage: "Collecting solar history...",
    });
    return;
  }
  chart.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "chart-empty-state";
  empty.textContent = "Collecting solar history...";
  chart.appendChild(empty);
}

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

// Placeholder-ready. Replace these fields when a live weather provider is wired in.
function updateWeatherPanel(weather, solar) {
  const source = weather?.source || "Placeholder";
  const placeholder = String(source).toLowerCase().includes("placeholder");
  solarSetText("solar-weather-production", solarMetric(solar?.current_production_kw, "kW", 2));
  solarSetText("solar-weather-sunshine", formatWeatherPercent(weather?.sunshine_percent, placeholder));
  solarSetText("solar-weather-clouds", formatWeatherPercent(weather?.cloud_cover_percent, placeholder));
  solarSetText("solar-weather-temperature", formatWeatherTemperature(weather?.temperature_f, placeholder));
  solarSetText("solar-weather-uv", weatherValue(weather?.uv_index, placeholder));
  solarSetText("solar-weather-source", source);
}

// Placeholder-ready. Replace these fields when forecast data is wired to Solar Center.
function updateForecastPlaceholder(weather) {
  const sunrise = weatherValue(weather?.sunrise, true);
  const sunset = weatherValue(weather?.sunset, true);
  solarSetText("solar-forecast-sun", sunrise === "Pending" && sunset === "Pending" ? "Awaiting weather service" : `${sunrise} / ${sunset}`);
  solarSetText("solar-forecast-production", "Pending");
  solarSetText("solar-forecast-cloud", "Pending");
}

function weatherValue(value, placeholder) {
  if (value === null || value === undefined || value === "") return placeholder ? "Pending" : SOLAR_EMPTY;
  return String(value);
}

function formatWeatherPercent(value, placeholder) {
  const number = solarNumber(value);
  if (number === null) return placeholder ? "Pending" : SOLAR_EMPTY;
  return `${number.toFixed(0)}%`;
}

function formatWeatherTemperature(value, placeholder) {
  const number = solarNumber(value);
  if (number === null) return placeholder ? "Pending" : SOLAR_EMPTY;
  return `${number.toFixed(0)} F`;
}

document.addEventListener("DOMContentLoaded", () => {
  setupSolarTabs();
  refreshSolarCenterOverview();
  setInterval(refreshSolarCenterOverview, 10000);
});

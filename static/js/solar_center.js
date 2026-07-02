// ============================================================================
// SOLAR CENTER
// ============================================================================
// Uses Center Framework for tab management and utilities
// ============================================================================

const SOLAR_STATE = {
  data: {},
  history: {},
  lastUpdate: null,
};

// ============================================================================
// TAB SETUP (Using Framework)
// ============================================================================

function setupSolarTabs() {
  setupCenterTabs((tab) => {
    loadTabData(tab);
  });
}

async function loadTabData(tab) {
  switch (tab) {
    case "overview":
      await refreshOverviewTab();
      break;
    case "health":
      await refreshHealthTab();
      break;
    case "production":
      await refreshProductionTab();
      break;
    case "weather":
      await refreshWeatherTab();
      break;
    case "analytics":
      await refreshAnalyticsTab();
      break;
  }
}

// ============================================================================
// TAB 1: OVERVIEW
// ============================================================================

async function refreshOverviewTab() {
  try {
    const [overview, history, weather] = await Promise.all([
      fetchJSON("/api/solar/overview"),
      fetchJSON("/api/history/metrics?module=solar&metric=current_production_kw&range=1d"),
      fetchJSON("/api/weather/status"),
    ]);

    const solar = overview.status || {};
    SOLAR_STATE.data = solar;
    SOLAR_STATE.history = history.points || [];

    updateOverviewUI(solar);
    renderCenterChart(document.getElementById("solar-overview-chart"), history.points || [], {
      digits: 2,
      yLabel: "kW",
      unit: "kW",
      xLabel: "Time",
      range: "1d",
      emptyMessage: "No production data available yet.",
    });
  } catch (error) {
    console.error("Overview tab error:", error);
  }
}

function updateOverviewUI(solar) {
  const status = solar.enabled ? solar.status || "Unknown" : "Disabled";
  const updated = formatTimestamp(solar.last_updated);

  setElementText("solar-overview-name", solar.name || "Solar Center");
  setElementText("solar-overview-badge", status);
  setElementText("solar-overview-current", solar.enabled ? formatMetric(solar.current_production_kw, "kW", 2) : "Disabled");
  setElementText("solar-overview-today", formatMetric(solar.production_today_kwh, "kWh", 2));
  setElementText("solar-overview-week", formatMetric(solar.production_last_7_days_kwh, "kWh", 2));
  setElementText("solar-overview-lifetime", formatMetric(solar.lifetime_production_mwh, "MWh", 3));
  setElementText("solar-overview-value", formatCurrency(solar.estimated_value_today));
  setElementText("solar-overview-source", solar.source || "Enphase Envoy");
  setElementText("solar-overview-updated", updated);

  // Trend indicator
  const prev = solar.production_yesterday_kwh || 0;
  const curr = solar.production_today_kwh || 0;
  const trend = calculateTrend(curr, prev);
  setElementText("solar-overview-trend", trend);

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

// ============================================================================
// TAB 2: SYSTEM HEALTH
// ============================================================================

async function refreshHealthTab() {
  try {
    const response = await fetchJSON("/api/solar/overview");
    const solar = response.status || {};
    updateHealthUI(solar);
  } catch (error) {
    console.error("Health tab error:", error);
  }
}

function updateHealthUI(solar) {
  setElementText("solar-health-gateway", solar.gateway_status || "Unknown");
  setElementText("solar-health-firmware", solar.firmware_version || "-");
  setElementText("solar-health-envoy", solar.envoy_status || "Unknown");
  setElementText("solar-health-cloud", solar.cloud_status || "Connected");

  const installed = solar.microinverters_installed || 0;
  const online = solar.microinverters_online || 0;
  const offline = installed - online;

  setElementText("solar-health-installed", String(installed));
  setElementText("solar-health-online", String(online));
  setElementText("solar-health-offline", String(offline));

  setElementText("solar-health-power", formatMetric(solar.current_production_kw, "kW", 2));
  setElementText("solar-health-peak-today", formatMetric(solar.peak_power_today_kw, "kW", 2));
  setElementText("solar-health-peak-month", formatMetric(solar.peak_power_month_kw, "kW", 2));
  setElementText("solar-health-lifetime", formatMetric(solar.lifetime_production_mwh, "MWh", 3));

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
        <td><span class="${mapStatusClass(inv.status)}">${inv.status || "Unknown"}</span></td>
        <td>${formatMetric(inv.lifetime_kwh, "kWh", 2)}</td>
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
      fetchJSON("/api/solar/overview"),
      fetchJSON(`/api/history/metrics?module=solar&metric=current_production_kw&range=${encodeURIComponent(range)}`),
    ]);

    const solar = overview.status || {};
    updateProductionUI(solar, history.points || [], range);
    renderCenterChart(chart, history.points || [], {
      digits: 2,
      yLabel: "kW",
      unit: "kW",
      xLabel: "Time",
      range,
      emptyMessage: "No production history for this range.",
      onRangeChange: refreshProductionTab,
    });
  } catch (error) {
    console.error("Production tab error:", error);
  }
}

function updateProductionUI(solar, points, range) {
  const stats = calculateStats(points.map((p) => p.value || p.kwh));

  setElementText("solar-prod-peak", formatMetric(stats.max, "kW", 2));
  setElementText("solar-prod-avg", formatMetric(stats.avg, "kW", 2));
  setElementText("solar-prod-total", formatMetric(stats.total, "kWh", 2));

  setElementText("solar-prod-today", formatMetric(solar.production_today_kwh, "kWh", 2));
  setElementText("solar-prod-yesterday", formatMetric(solar.production_yesterday_kwh, "kWh", 2));
  setElementText("solar-prod-week", formatMetric(solar.production_last_7_days_kwh, "kWh", 2));
  setElementText("solar-prod-month", formatMetric(solar.production_last_30_days_kwh, "kWh", 2));

  const dailyAvg = stats.total || 0;
  const annualEst = dailyAvg * 365;
  setElementText("solar-prod-annual", formatMetric(annualEst, "MWh", 2));
}

// ============================================================================
// TAB 4: WEATHER
// ============================================================================

async function refreshWeatherTab() {
  try {
    const [weather, history] = await Promise.all([
      fetchJSON("/api/weather/status"),
      fetchJSON("/api/history/metrics?module=solar&metric=current_production_kw&range=1d"),
    ]);

    updateWeatherUI(weather);
    renderCenterChart(document.getElementById("solar-weather-chart"), history.points || [], {
      digits: 2,
      yLabel: "kW",
      unit: "kW",
      xLabel: "Time",
      range: "1d",
      emptyMessage: "Collecting correlation data...",
    });
    updateWeatherImpact(weather, history.points || []);
  } catch (error) {
    console.error("Weather tab error:", error);
  }
}

function updateWeatherUI(weather) {
  setElementText("solar-weather-condition", weather.condition || "-");
  setElementText("solar-weather-temp", weather.temperature_f ? `${weather.temperature_f.toFixed(1)}°F` : "-");
  setElementText("solar-weather-feels", weather.feels_like_f ? `${weather.feels_like_f.toFixed(1)}°F` : "-");
  setElementText("solar-weather-humidity", formatPercent(weather.humidity_percent));
  setElementText("solar-weather-wind", weather.wind_mph ? `${weather.wind_mph.toFixed(1)} mph` : "-");
  setElementText("solar-weather-clouds", formatPercent(weather.cloud_cover_percent));
  setElementText("solar-weather-pressure", weather.pressure_mb ? `${weather.pressure_mb.toFixed(1)} mb` : "-");
  setElementText("solar-weather-visibility", weather.visibility_miles ? `${weather.visibility_miles.toFixed(1)} mi` : "-");
  setElementText("solar-weather-uv", weather.uv_index !== undefined ? String(weather.uv_index) : "-");
  setElementText("solar-weather-sunrise", weather.sunrise || "-");
  setElementText("solar-weather-sunset", weather.sunset || "-");

  if (weather.sunrise && weather.sunset) {
    const hours = calculateHours(weather.sunrise, weather.sunset);
    setElementText("solar-weather-daylight", hours);
  }
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
    const response = await fetchJSON("/api/solar/overview");
    const solar = response.status || {};
    updateAnalyticsUI(solar);
  } catch (error) {
    console.error("Analytics tab error:", error);
  }
}

function updateAnalyticsUI(solar) {
  const rates = {
    kwh_to_co2_lbs: 0.92,
    trees_per_year_lbs: 48,
    ev_miles_per_kwh: 4,
  };

  updateAnalyticsKPI("today", solar.production_today_kwh, solar.estimated_value_today);
  updateAnalyticsKPI("yesterday", solar.production_yesterday_kwh, null);
  updateAnalyticsKPI("week", solar.production_last_7_days_kwh, null);
  updateAnalyticsKPI("month", solar.production_last_30_days_kwh, null);
  updateAnalyticsKPI("lifetime", solar.lifetime_production_mwh, null);

  setElementText("solar-analytics-best-day", formatMetric(solar.best_production_day_kwh, "kWh", 2));
  setElementText("solar-analytics-avg-daily", formatMetric(solar.average_daily_production_kwh, "kWh", 2));
  setElementText("solar-analytics-best-hour", formatMetric(solar.peak_power_today_kw, "kW", 2));
  setElementText("solar-analytics-peak", formatMetric(solar.current_production_kw, "kW", 2));

  const lifetimeKwh = (solar.lifetime_production_mwh || 0) * 1000;
  const co2Lbs = lifetimeKwh * rates.kwh_to_co2_lbs;
  const trees = co2Lbs / rates.trees_per_year_lbs;
  const evMiles = lifetimeKwh * rates.ev_miles_per_kwh;

  setElementText("solar-analytics-co2", `${(co2Lbs / 1000).toFixed(1)}K lbs`);
  setElementText("solar-analytics-trees", `${trees.toFixed(0)} trees`);
  setElementText("solar-analytics-ev-miles", `${(evMiles / 1000).toFixed(0)}K miles`);
}

function updateAnalyticsKPI(prefix, kwh, value) {
  const kwhValue = formatMetric(kwh, "kWh", 2);
  const dollarValue = value ? formatCurrency(value) : formatCurrency((kwh || 0) * 0.13);

  setElementText(`solar-analytics-${prefix}`, kwhValue);
  setElementText(`solar-analytics-${prefix}-value`, dollarValue);
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  setupSolarTabs();
  refreshOverviewTab();
  setInterval(refreshOverviewTab, 30000);
});

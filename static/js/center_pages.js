function hpNumber(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim().replace("$", "").replace(",", "");
  if (!text || ["unknown", "unavailable", "none", "null", "--", "-"].includes(text.toLowerCase())) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function hpText(id, value, fallback = "-") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}

function hpMetric(value, unit, digits = 1, fallback = "-") {
  const number = hpNumber(value);
  if (number === null) return fallback;
  return `${number.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${unit}`;
}

function hpCurrency(value, digits = 2, fallback = "-") {
  const number = hpNumber(value);
  if (number === null) return fallback;
  return `$${number.toFixed(digits)}`;
}

function hpTimestamp(value) {
  if (!value) return "-";
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleString();
}

function hpCleanText(value, fallback = "-") {
  const text = String(value ?? "").trim();
  if (!text || ["unknown", "unavailable", "none", "null"].includes(text.toLowerCase())) return fallback;
  return text;
}

function hpSetBadge(id, status) {
  const badge = document.getElementById(id);
  if (!badge) return;
  badge.textContent = status || "Unavailable";
  badge.className = "energy-status-badge";
  const text = String(status || "").toLowerCase();
  if (text.includes("charging") || text.includes("live") || text.includes("producing")) badge.classList.add("charging");
  else if (text.includes("disabled")) badge.classList.add("disabled");
  else if (text.includes("waiting") || text.includes("unavailable") || text.includes("unknown")) badge.classList.add("offline");
  else badge.classList.add("idle");
}

function hpRenderChart(id, points, emptyMessage, options = {}) {
  const element = document.getElementById(id);
  if (!element) return;
  if (window.HomePulseHistory?.renderLineChart) {
    window.HomePulseHistory.renderLineChart(element, points || [], { digits: 1, emptyMessage, ...options });
  }
}

async function hpHistory(moduleName, metricName, rangeOrHours = "1d") {
  if (!window.HomePulseHistory?.fetchMetrics) return [];
  try {
    const payload = await window.HomePulseHistory.fetchMetrics(moduleName, metricName, { range: rangeOrHours });
    return payload.points || [];
  } catch (error) {
    return [];
  }
}

async function hpRenderHistoryChart(id, moduleName, metricName, emptyMessage, options = {}) {
  const element = document.getElementById(id);
  if (!element || !window.HomePulseHistory) return;
  const range = window.HomePulseHistory.selectedRange(element);
  const points = await hpHistory(moduleName, metricName, range);
  hpRenderChart(id, points, emptyMessage, {
    ...options,
    range,
    emptyMessage: points.length ? emptyMessage : "No data available for this range yet.",
    onRangeChange: () => hpRenderHistoryChart(id, moduleName, metricName, emptyMessage, options),
  });
}

async function initEnergyPage() {
  if (!document.getElementById("energy-page-power")) return;
  try {
    const response = await fetch("/api/energy/status", { cache: "no-store" });
    const data = response.ok ? await response.json() : {};
    const status = !data.enabled ? "Disabled" : data.is_charging ? "Charging" : data.configured ? "Not Charging" : "Waiting for Data";
    hpSetBadge("energy-page-status", status);
    hpText("energy-page-charger", data.charger_name || "ChargePoint Charger");
    hpText("energy-page-vehicle", data.vehicle_name || "Vehicle");
    hpText("energy-page-power", data.enabled ? hpMetric(data.power_kw, "kW", 2) : "Disabled");
    hpText("energy-page-charging-status", status);
    hpText("energy-page-session", hpMetric(data.session_energy_kwh, "kWh", 2));
    hpText("energy-page-miles", hpMetric(data.miles_added ?? data.estimated_miles_added, "mi", 1));
    hpText("energy-page-cost", hpCurrency(data.charge_cost ?? data.estimated_cost));
    hpText("energy-page-network", hpCleanText(data.network));
    hpText("energy-page-time", hpCleanText(data.charging_time));
    hpText("energy-page-message", data.message || "Energy Center status loaded.");
  } catch (error) {
    hpSetBadge("energy-page-status", "Waiting for Data");
    hpText("energy-page-message", "Energy Center data is unavailable right now.");
  }
  hpRenderHistoryChart("energy-power-chart", "energy", "charging_power_kw", "Collecting charging history...", { yLabel: "kW", unit: "kW" });
}

async function initVehiclePage() {
  if (!document.getElementById("vehicle-page-battery")) return;
  try {
    const response = await fetch("/api/vehicle/status", { cache: "no-store" });
    const data = response.ok ? await response.json() : {};
    const status = !data.enabled ? "Disabled" : data.configured ? "Live" : "Waiting for Data";
    hpSetBadge("vehicle-page-status", status);
    hpText("vehicle-page-name", data.vehicle_name || "Vehicle");
    hpText("vehicle-page-message", data.message || "Vehicle Center status loaded.");
    hpText("vehicle-page-battery", data.enabled ? hpMetric(data.battery_percent, "%", 0) : "Disabled");
    hpText("vehicle-page-range", hpMetric(data.range_mi, "mi", 1));
    hpText("vehicle-page-plug", hpCleanText(data.plug_state));
    hpText("vehicle-page-charging", hpCleanText(data.charging_state));
    hpText("vehicle-page-odometer", hpMetric(data.odometer_mi, "mi", 1));
    hpText("vehicle-page-energy", hpMetric(data.lifetime_energy_kwh, "kWh", 1));
    hpText("vehicle-page-efficiency", hpMetric(data.lifetime_efficiency_mi_per_kwh, "mi/kWh", 2));
    hpText("vehicle-page-cost-mile", hpCurrency(data.cost_per_mile, 3));
    hpText("vehicle-page-updated", hpTimestamp(data.last_update));
  } catch (error) {
    hpSetBadge("vehicle-page-status", "Waiting for Data");
    hpText("vehicle-page-message", "Vehicle Center data is unavailable right now.");
  }
  hpRenderHistoryChart("vehicle-battery-chart", "vehicle", "battery_percent", "Collecting battery history...", { yLabel: "%", unit: "%" });
  hpRenderHistoryChart("vehicle-range-chart", "vehicle", "ev_range_mi", "Collecting range history...", { yLabel: "mi", unit: "mi" });
  hpRenderHistoryChart("vehicle-efficiency-chart", "vehicle", "lifetime_efficiency_mi_per_kwh", "Collecting efficiency history...", { yLabel: "mi/kWh", unit: "mi/kWh" });
}

async function initInternetCharts() {
  if (!document.getElementById("internet-latency-chart")) return;
  hpRenderHistoryChart("internet-latency-chart", "internet", "latency_ms", "Collecting internet history...", { yLabel: "ms", unit: "ms" });
  hpRenderHistoryChart("internet-health-chart", "internet", "health_score", "Collecting internet history...", { yLabel: "%", unit: "%" });
  hpRenderHistoryChart("internet-packet-loss-chart", "internet", "packet_loss_percent", "Collecting internet history...", { yLabel: "%", unit: "%" });
  hpRenderHistoryChart("internet-speed-chart", "internet", "download_mbps", "Collecting speed test history...", { yLabel: "Mbps", unit: "Mbps" });
  hpRenderHistoryChart("internet-upload-chart", "internet", "upload_mbps", "Collecting speed test history...", { yLabel: "Mbps", unit: "Mbps" });
}

async function initSpeedPage() {
  if (!document.getElementById("speed-download-chart")) return;
  hpRenderHistoryChart("speed-download-chart", "internet", "download_mbps", "Collecting speed test history...", { yLabel: "Mbps", unit: "Mbps" });
  hpRenderHistoryChart("speed-upload-chart", "internet", "upload_mbps", "Collecting speed test history...", { yLabel: "Mbps", unit: "Mbps" });
}

document.addEventListener("DOMContentLoaded", () => {
  initEnergyPage();
  initVehiclePage();
  initInternetCharts();
  initSpeedPage();
});

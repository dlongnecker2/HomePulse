function homeNumber(value) {
  if (value === null || value === undefined) return null;
  const number = Number(String(value).replace("$", "").replace(",", "").trim());
  return Number.isFinite(number) ? number : null;
}

function homeText(id, value, fallback = "--") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}

function homeMetric(value, unit, digits = 1, fallback = "--") {
  const number = homeNumber(value);
  if (number === null) return fallback;
  return `${number.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${unit}`;
}

function homeCurrency(value, fallback = "--") {
  const number = homeNumber(value);
  if (number === null) return fallback;
  return `$${number.toFixed(2)}`;
}

function homeTimestamp(value) {
  if (!value) return "--";
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? "--" : parsed.toLocaleString();
}

function homeClean(value, fallback = "--") {
  const text = String(value ?? "").trim();
  if (!text || ["unknown", "unavailable", "none", "null"].includes(text.toLowerCase())) return fallback;
  return text;
}

function weatherIcon(data) {
  const clouds = homeNumber(data?.cloud_cover_percent);
  const condition = String(data?.condition || "").toLowerCase();
  if (!data?.enabled || !data?.live_data) return "?";
  if (condition.includes("rain")) return "Rain";
  if (clouds !== null && clouds <= 20) return "Sun";
  if (clouds !== null && clouds <= 65) return "Partly";
  if (clouds !== null) return "Cloud";
  return "Weather";
}

function setTileState(selector, state) {
  const tile = document.querySelector(selector);
  if (!tile) return;
  tile.classList.remove("is-healthy", "is-partial", "is-attention");
  tile.classList.add(state);
}

function statusState(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("unhealthy") || text.includes("attention") || text.includes("failed")) return "is-attention";
  if (text.includes("partial") || text.includes("unknown") || text.includes("unavailable") || text.includes("disabled") || text.includes("waiting")) return "is-partial";
  return "is-healthy";
}

async function refreshHomeCenter() {
  try {
    const response = await fetch("/api/home/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`Home status returned ${response.status}`);
    const data = await response.json();
    updateHomeCenter(data);
  } catch (error) {
    homeText("home-overall-status", "Attention");
    homeText("home-last-updated", new Date().toLocaleString());
  }
}

function updateHomeCenter(data) {
  const internet = data.internet || {};
  const solar = data.solar || {};
  const energy = data.energy || {};
  const vehicle = data.vehicle || {};
  const weather = data.weather || {};
  const lighting = data.lighting || {};
  const home = data.home || {};

  homeText("home-overall-status", data.overall_status || "Partial");
  homeText("home-health-score", data.health_score === null || data.health_score === undefined ? "--" : `${data.health_score}%`);
  homeText("home-last-updated", homeTimestamp(data.last_updated));

  homeText("home-internet-status", internet.status);
  homeText("home-internet-health", internet.health_score === null || internet.health_score === undefined ? "--" : `${internet.health_score}/100`);
  homeText("home-internet-latency", homeMetric(internet.latency_ms, "ms", 1));
  homeText("home-internet-speed", internet.download_mbps === null || internet.download_mbps === undefined ? "No speed test" : `${homeMetric(internet.download_mbps, "Mbps", 1)} down`);
  setTileState('[data-tile="internet"]', statusState(internet.status));

  homeText("home-solar-current", solar.enabled ? homeMetric(solar.current_production_kw, "kW", 2) : "Disabled");
  homeText("home-solar-status", solar.enabled ? solar.status : "Disabled");
  homeText("home-solar-today", homeMetric(solar.production_today_kwh, "kWh", 2));
  homeText("home-solar-updated", homeTimestamp(solar.last_updated));
  setTileState('[data-tile="solar"]', statusState(solar.enabled ? solar.status : "Disabled"));

  const energyStatus = !energy.enabled ? "Disabled" : energy.is_charging ? "Charging" : energy.configured ? "Not Charging" : "Waiting for Data";
  homeText("home-energy-status", energyStatus);
  homeText("home-energy-power", homeMetric(energy.power_kw, "kW", 2));
  homeText("home-energy-session", homeMetric(energy.session_energy_kwh, "kWh", 2));
  homeText("home-energy-cost", homeCurrency(energy.charge_cost ?? energy.estimated_cost));
  setTileState('[data-tile="energy"]', statusState(energyStatus));

  homeText("home-vehicle-battery", vehicle.enabled ? homeMetric(vehicle.battery_percent, "%", 0) : "Disabled");
  homeText("home-vehicle-range", homeMetric(vehicle.range_mi, "mi", 1));
  homeText("home-vehicle-plug", homeClean(vehicle.plug_state));
  homeText("home-vehicle-charging", homeClean(vehicle.charging_state));
  setTileState('[data-tile="vehicle"]', statusState(vehicle.enabled ? vehicle.availability || "Live" : "Disabled"));

  homeText("home-weather-icon", weatherIcon(weather));
  homeText("home-weather-temperature", weather.temperature_f === null || weather.temperature_f === undefined ? "Weather unavailable" : homeMetric(weather.temperature_f, "F", 0));
  const cloud = homeNumber(weather.cloud_cover_percent);
  homeText("home-weather-condition", weather.live_data && cloud !== null ? `${homeClean(weather.condition, "Weather")} / ${cloud.toFixed(0)}% clouds` : homeClean(weather.condition, "Weather unavailable"));
  homeText("home-weather-wind", homeMetric(weather.wind_mph, "mph", 1));
  homeText("home-weather-sun", weather.sunrise || weather.sunset ? `${homeClean(weather.sunrise)} / ${homeClean(weather.sunset)}` : "--");
  setTileState('[data-tile="weather"]', statusState(weather.live_data ? weather.condition : "Unavailable"));

  homeText("home-lighting-status", lighting.status || "Not configured");
  homeText("home-lighting-message", lighting.message || "Exterior lighting is not configured yet.");
  homeText("home-alert-status", home.status || "No active alerts");
}

document.addEventListener("DOMContentLoaded", () => {
  refreshHomeCenter();
  setInterval(refreshHomeCenter, 30000);
});

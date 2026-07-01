function setText(id, value, fallback = "--") {
  const element = document.getElementById(id);
  if (!element) return;
  const nextValue = value === null || value === undefined || value === "" ? fallback : String(value);
  if (element.textContent === nextValue) return;
  element.textContent = nextValue;
  element.classList.remove("is-updated");
  void element.offsetWidth;
  element.classList.add("is-updated");
}

function formatMetric(value, unit, emptyState) {
  const number = cleanNumber(value);
  if (number === null) return emptyState;
  const precision = Math.abs(number) >= 10 ? 1 : 2;
  return `${number.toFixed(precision).replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1")} ${unit}`;
}

function statusSubtitle(status) {
  const normalized = String(status || "starting").toLowerCase();
  if (normalized === "healthy") return "All monitored services operating normally.";
  if (normalized === "degraded") return "Performance is degraded. Review latency, packet loss, and DNS status.";
  if (normalized === "unhealthy") return "Critical network issues detected. Immediate attention recommended.";
  return "Collecting the first monitoring sample.";
}

function parseTimestamp(value) {
  if (!value) return null;
  const normalized = String(value).trim().replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatUptime(startedAt) {
  const started = parseTimestamp(startedAt);
  if (!started) return "Calculating";

  const totalSeconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function setStatusClass(element, status) {
  if (!element) return;
  element.classList.remove("healthy", "degraded", "unhealthy", "starting");
  const normalized = String(status || "starting").toLowerCase();
  if (normalized === "healthy") element.classList.add("healthy");
  else if (normalized === "degraded") element.classList.add("degraded");
  else if (normalized === "unhealthy") element.classList.add("unhealthy");
  else element.classList.add("starting");
}

async function refreshDashboardStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const data = await response.json();

    setText("app-version", data.version);
    setText("internet-status", data.internet_status);
    setText("hero-status", data.internet_status);
    setText("internet-details", data.internet_details);
    setText("hero-subtitle", statusSubtitle(data.internet_status));
    setText("latest-latency", data.latest_latency_ms);
    setText("packet-loss", `Packet loss: ${data.packet_loss ?? "--"}%`);
    setText("health-score", data.internet_quality_score ?? data.health_score);
    setText("dns-status", `ISP grade: ${data.isp_grade || "--"}`);
    setText("isp-grade", data.isp_grade);
    setText("reliability-trend", data.reliability_trend);
    setText("last-check", `Last check: ${data.last_check || "--"}`);
    const speedUnavailable = data.speedtest_status === "Failed" || data.speedtest_status === "Unavailable";
    const speedFallback = speedUnavailable && data.last_speedtest ? "Provider unavailable" : "Waiting for first test";
    setText("speed-download", formatMetric(data.download, "Mbps", speedFallback));
    setText("speed-download-table", formatMetric(data.download, "Mbps", speedFallback));
    setText("speed-upload", formatMetric(data.upload, "Mbps", "Unavailable"));
    setText("speed-upload-table", formatMetric(data.upload, "Mbps", "Unavailable"));
    setText("speedtest-ping", `Ping: ${formatMetric(data.speedtest_ping, "ms", "Unavailable")}`);
    setText("speedtest-ping-table", formatMetric(data.speedtest_ping, "ms", "Unavailable"));
    setText("speedtest-status", data.speedtest_status, "Unavailable");
    setText("speedtest-server", data.speedtest_server, "Unavailable");
    setText("next-speedtest", data.next_speedtest, "Schedule disabled");
    setText("automation-next-speedtest", data.next_speedtest, "Schedule disabled");
    setText("speedtest-schedule-label", data.speedtest_schedule_label, "Every 30 minutes");
    setText("last-speedtest", data.speedtest_error && speedUnavailable ? data.speedtest_error : `Last run: ${data.last_speedtest || "--"}`);
    setText("router-status", data.router_status);
    setText("last-reboot", `Last reboot: ${data.last_reboot || "None recorded"}`);
    setText("started-at", data.started_at);
    setText("last-update", data.last_update);
    setText("application-uptime", formatUptime(data.started_at));
    setText("event-health-time", data.last_check);
    setText("event-health", `Status: ${data.internet_status || "--"}${data.latest_latency_ms === null || data.latest_latency_ms === undefined ? "" : ` - ${data.latest_latency_ms} ms`}`);
    setText("event-speedtest-time", data.last_speedtest);
    setText("event-speedtest", data.download === null || data.download === undefined ? (speedUnavailable ? "Speed test provider unavailable" : "Waiting for first test") : `${data.download} Mbps down / ${data.upload ?? "--"} Mbps up`);
    setText("event-router-time", data.last_reboot);
    setText("event-router", `Last reboot: ${data.last_reboot || "None recorded"}`);

    setStatusClass(document.getElementById("internet-status"), data.internet_status);
    setStatusClass(document.getElementById("hero-status"), data.internet_status);
    document.querySelectorAll(".health-indicator").forEach((element) => {
      setStatusClass(element, data.internet_status);
    });

    if (typeof loadLatencyChart === "function") {
      await loadLatencyChart();
    }
  } catch (error) {
    console.error("HomePulse live dashboard refresh failed", error);
  }
}

function formatCurrency(value) {
  const number = cleanNumber(value) ?? 0;
  return `$${number.toFixed(2)}`;
}

function formatCurrencyPrecision(value, digits, emptyState = "—") {
  const number = cleanNumber(value);
  if (number === null) return emptyState;
  return `$${number.toFixed(digits)}`;
}

function formatPercent(value, emptyState = "—") {
  const number = cleanNumber(value);
  if (number === null) return emptyState;
  return `${number.toFixed(number % 1 === 0 ? 0 : 1)}%`;
}

function formatVehicleMetric(value, unit, digits = 1, emptyState = "—") {
  const number = cleanNumber(value);
  if (number === null) return emptyState;
  return `${number.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} ${unit}`;
}

function formatVehicleRate(value, emptyState = "—") {
  const number = cleanNumber(value);
  if (number === null) return emptyState;
  return `$${number.toFixed(3)}/mi`;
}

function formatLastUpdated(value) {
  const parsed = parseTimestamp(value);
  if (!parsed) return "—";
  return parsed.toLocaleString();
}

function cleanNumber(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim().replace("$", "").replace(",", "");
  if (!text || ["unknown", "unavailable", "none", "null"].includes(text.toLowerCase())) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function formatDuration(value) {
  if (value === null || value === undefined) return "—";
  const raw = String(value).trim();
  if (!raw || ["unknown", "unavailable", "none", "null"].includes(raw.toLowerCase())) return "—";
  if (raw.includes(":")) {
    const parts = raw.split(":").map((part) => Number(part || 0));
    if (parts.every(Number.isFinite)) {
      const seconds = parts.reduce((total, part) => (total * 60) + part, 0);
      return formatSeconds(seconds);
    }
  }
  const number = Number(raw);
  if (Number.isFinite(number)) return formatSeconds(number);
  return raw;
}

function formatSeconds(value) {
  const totalSeconds = Math.max(0, Math.round(Number(value) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
  return `${seconds}s`;
}

async function refreshEnergyStatus() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    setText("energy-message", "Updating Energy Center...");
    const response = await fetch("/api/energy/status", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Energy status returned ${response.status}`);
    const data = await response.json();

    setText("energy-vehicle", data.vehicle_name);
    setText("energy-charger", data.charger_name);
    const energyStatus = energyDisplayStatus(data);
    setText("energy-status", energyStatus, "Unavailable");
    setText("energy-status-table", energyStatus, "Unavailable");
    setText("energy-power", formatMetric(data.power_kw, "kW", "0 kW"));
    setText("energy-session", formatMetric(data.session_energy_kwh, "kWh", "0 kWh"));
    setText("energy-network", cleanText(data.network, "—"));
    setText("energy-charging-time", formatDuration(data.charging_time));
    setText("energy-cost", formatCurrency(data.charge_cost ?? data.estimated_cost));
    setText("energy-miles", formatMetric(data.miles_added ?? data.estimated_miles_added, "mi", "0 mi"));
    setText("energy-miles-hour", formatMetric(data.miles_per_hour_added, "mi/hr", "—"));
    setText("energy-message", energyDisplayMessage(data));
    updateEnergyCardState(data, energyStatus);
    const setup = document.getElementById("energy-setup-message");
    if (setup) {
      setup.hidden = data.enabled && data.configured;
      setup.querySelector("div").textContent = energyDisplayMessage(data);
    }
  } catch (error) {
    setText("energy-status", "Waiting for Data");
    setText("energy-status-table", "Waiting for Data");
    setText("energy-network", "—");
    setText("energy-charging-time", "—");
    setText("energy-miles-hour", "—");
    setText("energy-message", "Energy Center data is taking longer than expected. The dashboard will keep trying.");
    updateEnergyCardState({ status: "Unavailable", enabled: true, configured: true }, "Waiting for Data");
  } finally {
    clearTimeout(timeout);
  }
}

function energyDisplayStatus(data) {
  if (!data.enabled) return "Disabled";
  if (!data.configured) return "Waiting for Data";
  if (data.is_charging) return "Charging";
  if (data.status === "Unavailable") return "Waiting for Data";
  return "Not Charging";
}

function energyDisplayMessage(data) {
  if (!data.enabled) return "Energy Center is disabled. Configure it in Settings when ready.";
  if (!data.configured) return "Energy Center enabled — add Home Assistant entity IDs in Settings.";
  if (data.status === "Unavailable") return "Waiting for charger data.";
  if (data.is_charging) return "Charging";
  return "Not Charging";
}

function cleanText(value, fallback) {
  const text = String(value ?? "").trim();
  if (!text || ["unknown", "unavailable", "none", "null"].includes(text.toLowerCase())) return fallback;
  return text;
}

function updateEnergyCardState(data, status) {
  const card = document.querySelector(".energy-card");
  const panel = document.querySelector(".energy-panel");
  const badge = document.getElementById("energy-status-badge");
  const active = Boolean(data?.enabled && data?.configured && data?.is_charging);
  const offline = status === "Waiting for Data";
  [card, panel].forEach((element) => {
    if (!element) return;
    element.classList.toggle("is-charging", active);
    element.classList.toggle("is-offline", offline);
  });
  if (!badge) return;
  badge.textContent = status;
  badge.className = "energy-status-badge";
  if (active) badge.classList.add("charging");
  else if (!data?.enabled) badge.classList.add("disabled");
  else if (offline) badge.classList.add("offline");
  else badge.classList.add("idle");
}

async function refreshVehicleStatus() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    setText("vehicle-message", "Updating Vehicle Center...");
    const response = await fetch("/api/vehicle/status", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Vehicle status returned ${response.status}`);
    const data = await response.json();

    const status = vehicleDisplayStatus(data);
    setText("vehicle-name", data.vehicle_name);
    setText("vehicle-battery", data.enabled ? formatPercent(data.battery_percent, "—") : "Disabled");
    setText("vehicle-battery-table", formatPercent(data.battery_percent));
    setText("vehicle-range", formatVehicleMetric(data.range_mi, "mi", 1));
    setText("vehicle-plug-state", cleanText(data.plug_state, "—"));
    setText("vehicle-charging-state", cleanText(data.charging_state, "—"));
    setText("vehicle-odometer", formatVehicleMetric(data.odometer_mi, "mi", 1));
    setText("vehicle-lifetime-energy", formatVehicleMetric(data.lifetime_energy_kwh, "kWh", 1));
    setText("vehicle-efficiency", formatVehicleMetric(data.lifetime_efficiency_mi_per_kwh, "mi/kWh", 2));
    setText("vehicle-lifetime-cost", formatCurrencyPrecision(data.estimated_lifetime_cost, 2));
    setText("vehicle-cost-per-mile", formatVehicleRate(data.cost_per_mile));
    setText("vehicle-last-updated", formatLastUpdated(data.last_update));
    setText("vehicle-last-updated-card", `Last updated: ${formatLastUpdated(data.last_update)}`);
    setText("vehicle-message", vehicleDisplayMessage(data));
    updateVehicleCardState(data, status);
    const setup = document.getElementById("vehicle-setup-message");
    if (setup) {
      setup.hidden = data.enabled && data.configured;
      setup.querySelector("div").textContent = vehicleDisplayMessage(data);
    }
  } catch (error) {
    setText("vehicle-battery", "Waiting for Data");
    setText("vehicle-battery-table", "—");
    setText("vehicle-range", "—");
    setText("vehicle-plug-state", "—");
    setText("vehicle-charging-state", "—");
    setText("vehicle-odometer", "—");
    setText("vehicle-lifetime-energy", "—");
    setText("vehicle-efficiency", "—");
    setText("vehicle-lifetime-cost", "—");
    setText("vehicle-cost-per-mile", "—");
    setText("vehicle-last-updated", "—");
    setText("vehicle-last-updated-card", "Last updated: —");
    setText("vehicle-message", "Vehicle Center data is taking longer than expected. The dashboard will keep trying.");
    updateVehicleCardState({ enabled: true, configured: true, availability: "home_assistant_unavailable" }, "Home Assistant Unavailable");
  } finally {
    clearTimeout(timeout);
  }
}

function vehicleDisplayStatus(data) {
  if (!data.enabled) return "Disabled";
  if (!data.configured) return "Waiting for Data";
  if (data.availability === "home_assistant_unavailable") return "Home Assistant Unavailable";
  if (data.availability === "partial") return "Partial Data";
  if (data.availability === "waiting" || data.message === "Waiting for vehicle data.") return "Waiting for Data";
  return "Live";
}

function vehicleDisplayMessage(data) {
  if (!data.enabled) return "Vehicle Center is disabled. Configure it in Settings when ready.";
  if (!data.configured) return "Vehicle Center enabled - add Home Assistant entity IDs in Settings.";
  if (data.availability === "home_assistant_unavailable") return "Home Assistant is unavailable for Vehicle Center.";
  if (data.availability === "partial") return "Vehicle Center is receiving partial vehicle data.";
  if (data.availability === "waiting" || data.message === "Waiting for vehicle data.") return "Waiting for vehicle data.";
  return data.message || "Vehicle Center is receiving live vehicle data.";
}

function updateVehicleCardState(data, status) {
  const card = document.querySelector(".vehicle-card");
  const panel = document.querySelector(".vehicle-panel");
  const badge = document.getElementById("vehicle-status-badge");
  const live = status === "Live";
  const partial = status === "Partial Data";
  const waiting = status === "Waiting for Data" || status === "Home Assistant Unavailable";
  [card, panel].forEach((element) => {
    if (!element) return;
    element.classList.toggle("is-live", live);
    element.classList.toggle("is-partial", partial);
    element.classList.toggle("is-offline", waiting);
  });
  if (!badge) return;
  badge.textContent = status;
  badge.className = "energy-status-badge";
  if (!data?.enabled) badge.classList.add("disabled");
  else if (waiting) badge.classList.add("offline");
  else if (partial) badge.classList.add("partial");
  else badge.classList.add("idle");
}

document.addEventListener("DOMContentLoaded", () => {
  refreshDashboardStatus();
  refreshEnergyStatus();
  refreshVehicleStatus();
  setInterval(refreshDashboardStatus, 10000);
  setInterval(refreshEnergyStatus, 10000);
  setInterval(refreshVehicleStatus, 10000);
  setInterval(() => {
    const startedAt = document.getElementById("started-at")?.textContent;
    setText("application-uptime", formatUptime(startedAt));
  }, 60000);
});

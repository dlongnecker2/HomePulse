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
  if (value === null || value === undefined || value === "") return emptyState;
  return `${value} ${unit}`;
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
    const speedFailed = data.speedtest_status === "Failed";
    setText("speed-download", formatMetric(data.download, "Mbps", speedFailed ? "Failed" : "Waiting for first test"));
    setText("speed-download-table", formatMetric(data.download, "Mbps", speedFailed ? "Failed" : "Waiting for first test"));
    setText("speed-upload", formatMetric(data.upload, "Mbps", "Unavailable"));
    setText("speed-upload-table", formatMetric(data.upload, "Mbps", "Unavailable"));
    setText("speedtest-ping", `Ping: ${formatMetric(data.speedtest_ping, "ms", "Unavailable")}`);
    setText("speedtest-ping-table", formatMetric(data.speedtest_ping, "ms", "Unavailable"));
    setText("speedtest-status", data.speedtest_status, "Unavailable");
    setText("speedtest-server", data.speedtest_server, "Unavailable");
    setText("next-speedtest", data.next_speedtest, "Schedule disabled");
    setText("automation-next-speedtest", data.next_speedtest, "Schedule disabled");
    setText("speedtest-schedule-label", data.speedtest_schedule_label, "Every 30 minutes");
    setText("last-speedtest", `Last run: ${data.last_speedtest || "--"}`);
    setText("router-status", data.router_status);
    setText("last-reboot", `Last reboot: ${data.last_reboot || "None recorded"}`);
    setText("started-at", data.started_at);
    setText("last-update", data.last_update);
    setText("application-uptime", formatUptime(data.started_at));
    setText("event-health-time", data.last_check);
    setText("event-health", `Status: ${data.internet_status || "--"}${data.latest_latency_ms === null || data.latest_latency_ms === undefined ? "" : ` - ${data.latest_latency_ms} ms`}`);
    setText("event-speedtest-time", data.last_speedtest);
    setText("event-speedtest", data.download === null || data.download === undefined ? (speedFailed ? "Speed test failed" : "Waiting for first test") : `${data.download} Mbps down / ${data.upload ?? "--"} Mbps up`);
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
  const number = Number(value || 0);
  return `$${number.toFixed(2)}`;
}

async function refreshEnergyStatus() {
  try {
    const response = await fetch("/api/energy/status", { cache: "no-store" });
    const data = await response.json();

    setText("energy-vehicle", data.vehicle_name);
    setText("energy-charger", data.charger_name);
    const energyStatus = energyDisplayStatus(data);
    setText("energy-status", energyStatus, "Unavailable");
    setText("energy-status-table", energyStatus, "Unavailable");
    setText("energy-power", formatMetric(data.power_kw, "kW", "0 kW"));
    setText("energy-session", formatMetric(data.session_energy_kwh, "kWh", "0 kWh"));
    setText("energy-cost", formatCurrency(data.estimated_cost));
    setText("energy-miles", formatMetric(data.estimated_miles_added, "mi", "0 mi"));
    setText("energy-message", energyDisplayMessage(data));
    const setup = document.getElementById("energy-setup-message");
    if (setup) {
      setup.hidden = data.enabled && data.configured;
      setup.querySelector("div").textContent = energyDisplayMessage(data);
    }
  } catch (error) {
    console.error("HomePulse energy status refresh failed", error);
    setText("energy-status", "Unavailable");
    setText("energy-status-table", "Unavailable");
    setText("energy-message", "Energy Center status unavailable.");
  }
}

function energyDisplayStatus(data) {
  if (!data.enabled) return "Disabled";
  if (!data.configured) return "Unavailable";
  if (data.is_charging) return "Charging";
  if (data.status === "Unavailable") return "Unavailable";
  return "Not Charging";
}

function energyDisplayMessage(data) {
  if (!data.enabled) return "Energy Center is disabled. Configure it in Settings when ready.";
  if (!data.configured) return "Energy Center enabled — add Home Assistant entity IDs in Settings.";
  if (data.status === "Unavailable") return "Waiting for charger data.";
  if (data.is_charging) return "Charging";
  return "Not Charging";
}

document.addEventListener("DOMContentLoaded", () => {
  refreshDashboardStatus();
  refreshEnergyStatus();
  setInterval(refreshDashboardStatus, 10000);
  setInterval(refreshEnergyStatus, 10000);
  setInterval(() => {
    const startedAt = document.getElementById("started-at")?.textContent;
    setText("application-uptime", formatUptime(startedAt));
  }, 60000);
});

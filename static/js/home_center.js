/**
 * HOME OPERATIONS CENTER
 * ======================
 * Mission Control for HomePulse
 * Displays unified home health, system status, alerts, timeline, and KPIs
 */

// ════════════════════════════════════════════════════════════════════════════════════
// UTILITIES
// ════════════════════════════════════════════════════════════════════════════════════

function setText(id, value, fallback = "—") {
  const el = document.getElementById(id);
  if (!el) return;
  const text = value === null || value === undefined || value === "" ? fallback : String(value);
  el.textContent = text;
}

function formatMetric(value, unit, digits = 1, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return `${num.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${unit}`;
}

function formatPercent(value, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  const num = Number(value);
  return Number.isFinite(num) ? `${Math.round(num)}%` : fallback;
}

function formatCurrency(value, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  const num = Number(String(value).replace("$", "").replace(",", ""));
  return Number.isFinite(num) ? `$${num.toFixed(2)}` : fallback;
}

function formatTimestamp(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(String(iso).replace(" ", "T"));
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const num = Number(seconds);
  if (!Number.isFinite(num)) return "—";
  if (num < 60) return `${Math.round(num)}s`;
  if (num < 3600) return `${Math.round(num / 60)}m`;
  if (num < 86400) return `${Math.round(num / 3600)}h`;
  return `${(num / 86400).toFixed(1)}d`;
}

function statusDot(status) {
  const s = String(status || "").toLowerCase();
  if (s.includes("unhealthy") || s.includes("offline") || s.includes("critical")) return "unhealthy";
  if (s.includes("degraded") || s.includes("partial") || s.includes("warning")) return "degraded";
  if (s.includes("disabled") || s.includes("unavailable") || s.includes("unconfigured")) return "disabled";
  if (s.includes("healthy") || s.includes("live") || s.includes("connected") || s.includes("ok")) return "healthy";
  return "unknown";
}

// ════════════════════════════════════════════════════════════════════════════════════
// MAIN REFRESH
// ════════════════════════════════════════════════════════════════════════════════════

async function refreshHomeCenter() {
  try {
    const [homeResponse, timelineResponse, notifResponse] = await Promise.all([
      fetch("/api/home/status", { cache: "no-store" }),
      fetch("/api/timeline/recent?limit=50", { cache: "no-store" }),
      fetch("/api/notifications/recent?limit=20", { cache: "no-store" }),
    ]);

    if (!homeResponse.ok) throw new Error(`Home status ${homeResponse.status}`);
    const homeData = await homeResponse.json();
    updateHomeCenter(homeData);

    if (timelineResponse.ok) {
      const timelineData = await timelineResponse.json();
      updateTimeline(timelineData.events || []);
    }

    if (notifResponse.ok) {
      const notifData = await notifResponse.json();
      updateNotifications(notifData);
    }
  } catch (error) {
    console.error("[HomeCenter] Refresh failed:", error);
    setText("noc-health-score", "—");
    setText("noc-updated", "Error");
  }
}

function updateHomeCenter(data) {
  // Health Score
  updateHealthScore(data);

  // Status Ribbon
  updateStatusRibbon(data);

  // Alerts
  updateAlerts(data.alerts || []);

  // System Status Grid
  updateSystemsGrid(data);

  // KPIs
  updateKPIs(data);

  // Statistics
  updateStatistics(data);

  // Metadata
  setText("noc-updated", `Updated: ${formatTimestamp(data.last_updated)}`);
}

// ════════════════════════════════════════════════════════════════════════════════════
// HEALTH SCORE
// ════════════════════════════════════════════════════════════════════════════════════

function updateHealthScore(data) {
  const score = data.health_score ?? "—";
  const status = data.health_status || "Unknown";
  const trend = data.health_trend || "→";

  setText("noc-health-score", score);
  setText("noc-health-status", status);
  setText("noc-health-trend", trend === "→" ? "→ Stable" : trend === "↑" ? "↑ Improving" : "↓ Declining");

  // Update circle color based on score
  const circle = document.getElementById("noc-health-circle");
  if (circle) {
    circle.classList.remove("excellent", "good", "warning", "critical", "offline");
    if (score >= 85) circle.classList.add("excellent");
    else if (score >= 70) circle.classList.add("good");
    else if (score >= 50) circle.classList.add("warning");
    else if (score >= 0) circle.classList.add("critical");
    else circle.classList.add("offline");
  }
}

// ════════════════════════════════════════════════════════════════════════════════════
// STATUS RIBBON
// ════════════════════════════════════════════════════════════════════════════════════

function updateStatusRibbon(data) {
  const ribbon = document.getElementById("noc-status-ribbon");
  if (!ribbon) return;

  const systems = [
    { name: "Internet", status: data.internet?.status },
    { name: "Solar", status: data.solar?.enabled ? data.solar?.status : "Disabled" },
    { name: "Vehicle", status: data.vehicle?.enabled ? data.vehicle?.availability : "Disabled" },
    { name: "Energy", status: data.energy?.enabled ? data.energy?.status : "Disabled" },
    { name: "Weather", status: data.weather?.enabled ? data.weather?.condition : "Disabled" },
    { name: "Home Assistant", status: data.home_assistant?.status || "Connected" },
  ];

  ribbon.innerHTML = systems
    .map((sys) => {
      const dotClass = statusDot(sys.status);
      return `<div class="ribbon-item" title="${sys.name}: ${sys.status}"><span class="ribbon-dot ${dotClass}"></span><span class="ribbon-label">${sys.name}</span></div>`;
    })
    .join("");
}

// ════════════════════════════════════════════════════════════════════════════════════
// ALERTS
// ════════════════════════════════════════════════════════════════════════════════════

function updateAlerts(alerts) {
  const alertsSection = document.getElementById("noc-alerts-section");
  const noAlertsSection = document.getElementById("noc-no-alerts-section");
  const alertsList = document.getElementById("noc-alerts-list");
  const alertCount = document.getElementById("noc-alert-count");

  if (!alerts || alerts.length === 0) {
    alertsSection?.setAttribute("hidden", "");
    noAlertsSection?.removeAttribute("hidden");
    return;
  }

  alertsSection?.removeAttribute("hidden");
  noAlertsSection?.setAttribute("hidden", "");
  alertCount.textContent = alerts.length;

  alertsList.innerHTML = alerts
    .map((alert) => {
      const severityClass = `alert-${alert.severity || "info"}`;
      return `
      <div class="noc-alert-item ${severityClass}">
        <div class="alert-header">
          <strong>${alert.title || "Alert"}</strong>
          <span class="alert-severity">${(alert.severity || "info").toUpperCase()}</span>
        </div>
        <div class="alert-body">${alert.description || ""}</div>
        <div class="alert-footer">${alert.system || ""} · ${formatTimestamp(alert.timestamp)}</div>
      </div>
    `;
    })
    .join("");
}

// ════════════════════════════════════════════════════════════════════════════════════
// SYSTEMS GRID
// ════════════════════════════════════════════════════════════════════════════════════

function updateSystemsGrid(data) {
  updateSystemCard("internet", data.internet);
  updateSystemCard("solar", data.solar);
  updateSystemCard("vehicle", data.vehicle);
  updateSystemCard("energy", data.energy);
  updateSystemCard("weather", data.weather);
  updateSystemCard("ha", data.home_assistant);
}

function updateSystemCard(system, status) {
  if (!status) {
    setText(`noc-${system}-badge`, "disabled");
    setText(`noc-${system}-metric`, "—");
    return;
  }

  // Determine status dot color
  let dotClass = "disabled";
  if (status.enabled === false) dotClass = "disabled";
  else if (status.availability === "live" || status.status === "Healthy" || status.status === "Connected")
    dotClass = "healthy";
  else if (status.availability === "partial" || status.status === "Degraded" || status.status === "Partial")
    dotClass = "degraded";
  else if (
    status.availability === "unavailable" ||
    status.status === "Unavailable" ||
    status.status === "Offline"
  )
    dotClass = "unhealthy";

  const badge = document.getElementById(`noc-${system}-badge`);
  if (badge) {
    badge.classList.remove("healthy", "degraded", "unhealthy", "disabled");
    badge.classList.add(dotClass);
  }

  switch (system) {
    case "internet":
      setText("noc-internet-metric", formatMetric(status.health_score, "%", 0) || status.status || "—");
      setText("noc-internet-latency", formatMetric(status.latency_ms, "ms", 0));
      setText("noc-internet-loss", formatMetric(status.packet_loss_percent, "%", 1));
      setText("noc-internet-status", status.status || "—");
      setText("noc-internet-updated", formatTimestamp(status.last_check));
      break;
    case "solar":
      setText("noc-solar-metric", formatMetric(status.current_production_kw, "kW", 2) || "Disabled");
      setText("noc-solar-status", status.enabled ? status.status || "—" : "Disabled");
      setText("noc-solar-today", formatMetric(status.production_today_kwh, "kWh", 1));
      setText("noc-solar-peak", formatMetric(status.peak_production_kw, "kW", 2));
      setText("noc-solar-updated", formatTimestamp(status.last_updated));
      break;
    case "vehicle":
      setText("noc-vehicle-metric", formatMetric(status.battery_percent, "%", 0) || "Disabled");
      setText("noc-vehicle-range", formatMetric(status.range_mi, "mi", 1));
      setText("noc-vehicle-plugged", status.plugged_in ? "Yes" : "No");
      setText("noc-vehicle-charging", status.charging ? "Yes" : "No");
      setText("noc-vehicle-updated", formatTimestamp(status.last_update));
      break;
    case "energy":
      setText("noc-energy-metric", formatMetric(status.power_kw, "kW", 2) || (status.enabled ? "Not Charging" : "Disabled"));
      setText("noc-energy-power", formatMetric(status.power_kw, "kW", 2));
      setText("noc-energy-session", formatMetric(status.session_energy_kwh, "kWh", 1));
      setText("noc-energy-cost", formatCurrency(status.estimated_cost));
      setText("noc-energy-updated", formatTimestamp(status.last_update));
      break;
    case "weather":
      const tempStr = formatMetric(status.temperature_f, "°F", 0);
      setText("noc-weather-metric", tempStr || "Unavailable");
      setText("noc-weather-condition", status.condition || "—");
      setText("noc-weather-clouds", formatMetric(status.cloud_cover_percent, "%", 0));
      setText("noc-weather-wind", formatMetric(status.wind_mph, "mph", 1));
      setText("noc-weather-updated", formatTimestamp(status.last_updated));
      break;
    case "ha":
      setText("noc-ha-detail", status.status || "Connected");
      setText("noc-ha-message", status.message || "Integration active");
      break;
  }
}

// ════════════════════════════════════════════════════════════════════════════════════
// TIMELINE
// ════════════════════════════════════════════════════════════════════════════════════

function updateTimeline(events) {
  const timelineList = document.getElementById("noc-timeline-list");
  const timelineEmpty = document.getElementById("noc-timeline-empty");

  if (!events || events.length === 0) {
    timelineList.innerHTML = "";
    timelineEmpty?.removeAttribute("hidden");
    return;
  }

  timelineEmpty?.setAttribute("hidden", "");
  timelineList.innerHTML = events
    .map((event) => {
      const severityClass = `timeline-${event.severity || "info"}`;
      return `
      <div class="timeline-item ${severityClass}">
        <div class="timeline-time">${formatTimestamp(event.timestamp)}</div>
        <div class="timeline-dot"></div>
        <div class="timeline-content">
          <div class="timeline-title">${event.title || "Event"}</div>
          ${event.description ? `<div class="timeline-description">${event.description}</div>` : ""}
          <div class="timeline-category">${event.category || ""}</div>
        </div>
      </div>
    `;
    })
    .join("");
}

/**
 * Update notifications display.
 * Notifications are user-facing messages (different from alerts = current conditions).
 */
function updateNotifications(data) {
  const unreadCount = data.unread_count || 0;
  const notifications = data.notifications || [];
  
  // Log for debugging (no dedicated UI panel yet, but infrastructure in place)
  if (unreadCount > 0) {
    console.log(`[Notifications] ${unreadCount} unread`);
  }
  
  // Future: Add notification panel to display warnings/critical notifications
  // Update notification badge on Home Center or in navbar
  // For now, notifications feed the alert system for display
}

// ════════════════════════════════════════════════════════════════════════════════════
// KPIs
// ════════════════════════════════════════════════════════════════════════════════════

function updateKPIs(data) {
  // Solar KPIs
  setText("noc-kpi-solar-today", formatMetric(data.solar?.production_today_kwh, "kWh", 1));
  setText("noc-kpi-solar-peak", formatMetric(data.solar?.peak_production_kw, "kW", 2));

  // Vehicle KPIs
  setText("noc-kpi-vehicle-battery", formatMetric(data.vehicle?.battery_percent, "%", 0));
  setText("noc-kpi-vehicle-range", formatMetric(data.vehicle?.range_mi, "mi", 0));

  // Energy KPIs
  setText("noc-kpi-energy-power", formatMetric(data.energy?.power_kw, "kW", 2));
  setText("noc-kpi-energy-cost", formatCurrency(data.energy?.estimated_cost));

  // Internet KPIs
  const healthScore = data.health_breakdown?.internet ?? data.internet?.health_score ?? 0;
  setText("noc-kpi-internet-health", formatMetric(healthScore, "%", 0));
  setText("noc-kpi-internet-latency", formatMetric(data.internet?.latency_ms, "ms", 0));

  // Weather KPIs
  setText("noc-kpi-weather-temp", formatMetric(data.weather?.temperature_f, "°F", 0));
  setText("noc-kpi-weather-clouds", formatMetric(data.weather?.cloud_cover_percent, "%", 0));

  // System KPIs
  const uptimeSeconds = data.system?.uptime_seconds || 0;
  setText("noc-kpi-system-uptime", `${Math.round(uptimeSeconds / 3600)} hrs`);
}

// ════════════════════════════════════════════════════════════════════════════════════
// STATISTICS
// ════════════════════════════════════════════════════════════════════════════════════

function updateStatistics(data) {
  const uptimeSeconds = data.system?.uptime_seconds || 0;
  const uptime =
    uptimeSeconds < 3600
      ? `${Math.round(uptimeSeconds / 60)} min`
      : `${Math.round(uptimeSeconds / 3600)} hrs`;
  setText("noc-stat-uptime", uptime);
}

// ════════════════════════════════════════════════════════════════════════════════════
// INITIALIZATION
// ════════════════════════════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  refreshHomeCenter();
  setInterval(refreshHomeCenter, 30000); // Refresh every 30 seconds
});

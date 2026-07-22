let gardenRefreshSeq = 0;
let lastGardenSnapshot = window.HomePulseGardenInitial || {};

function normalizeGardenSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") {
    return { garden: {}, greenhouse: {} };
  }

  const hasFlatGardenFields =
    Object.prototype.hasOwnProperty.call(snapshot, "provider") ||
    Object.prototype.hasOwnProperty.call(snapshot, "controller_count") ||
    Object.prototype.hasOwnProperty.call(snapshot, "controllers") ||
    Object.prototype.hasOwnProperty.call(snapshot, "zones") ||
    Object.prototype.hasOwnProperty.call(snapshot, "status");

  if (hasFlatGardenFields) {
    return {
      garden: snapshot,
      greenhouse: snapshot.greenhouse || {},
    };
  }

  return {
    garden: snapshot.garden || {},
    greenhouse: snapshot.greenhouse || {},
  };
}

function gardenText(value, fallback = "--") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function formatGardenTimestamp(value) {
  if (!value) return "Unavailable";
  if (typeof formatTimestamp === "function") {
    const formatted = formatTimestamp(value);
    return formatted === "-" ? String(value) : formatted;
  }
  return String(value);
}

function greenhouseStatusLabel(greenhouse) {
  if (!greenhouse?.enabled) return "Disabled";
  if (!greenhouse?.configured) return "Unavailable";
  if (greenhouse?.status) return greenhouse.status;
  if (greenhouse?.source_status === "cached") return "Last Known";
  if (greenhouse?.source_status === "stale") return "Not Available";
  if (greenhouse?.source_status === "live") return "Connected";
  return "Unavailable";
}

function greenhouseBadgeClass(greenhouse) {
  if (!greenhouse?.enabled || !greenhouse?.configured) return "disabled";
  if (greenhouse?.source_status === "cached") return "degraded";
  if (greenhouse?.source_status === "stale" || greenhouse?.source_status === "unavailable") return "offline";
  const band = String(greenhouse?.temperature_band || "").toLowerCase();
  if (band === "cold" || band === "warm") return "degraded";
  if (band === "hot") return "unhealthy";
  return "healthy";
}

function renderGardenSummary(garden) {
  const current = garden || {};
  const statusText = gardenText(current.status, "Unavailable");
  setElementText("garden-status", gardenText(current.status));
  setElementText("garden-provider", gardenText(current.provider ? String(current.provider).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Home Assistant"));
  setElementText("garden-integration", gardenText(current.integration));
  setElementText("garden-controller-count", gardenText(current.controller_count));
  setElementText("garden-active-zone", gardenText(current.active_watering_zone));
  setElementText("garden-next-schedule", gardenText(current.next_watering_schedule));

  const rainDelay = document.getElementById("garden-rain-delay");
  if (rainDelay) {
    if (current.rain_delay_active === true) {
      rainDelay.textContent = current.rain_delay_until ? `Active until ${current.rain_delay_until}` : "Active";
    } else if (current.rain_delay_active === false) {
      rainDelay.textContent = "Inactive";
    } else {
      rainDelay.textContent = "--";
    }
  }

  setElementText("garden-entity-count", gardenText(current.entity_count));
  setElementText("garden-discovery-status", gardenText(current.discovery_status));
  setElementText("garden-last-updated", formatGardenTimestamp(current.last_successful_refresh || current.last_updated));
  if (current.message) {
    setElementText("garden-message", current.message);
  } else if (current.error) {
    setElementText("garden-message", `Discovery error: ${current.error}`);
  } else if (statusText !== "Unavailable") {
    setElementText("garden-message", statusText);
  } else if (current.configured === false) {
    setElementText("garden-message", "Home Assistant irrigation is unavailable.");
  } else {
    setElementText("garden-message", "Home Assistant irrigation data is loading.");
  }

  const errorEl = document.getElementById("garden-error");
  if (errorEl) {
    if (current.error) {
      errorEl.textContent = `Provider error: ${current.error}`;
      errorEl.style.display = "block";
    } else {
      errorEl.style.display = "none";
    }
  }

  const controllers = Array.isArray(current.controllers) ? current.controllers : [];
  renderControllersTable(controllers, current.configured);
  renderZonesTable(Array.isArray(current.zones) ? current.zones : [], current.configured);
}

function renderControllersTable(controllers, configured) {
  const table = document.getElementById("garden-controllers-table");
  const empty = document.getElementById("garden-controllers-empty");
  const body = document.getElementById("garden-controllers-body");
  if (!table || !empty || !body) return;

  body.innerHTML = "";
  if (controllers.length === 0) {
    table.setAttribute("hidden", "");
    empty.textContent = configured ? "No controllers available." : "No irrigation entities were found in Home Assistant.";
    empty.style.display = "block";
    return;
  }

  controllers.forEach((controller) => {
    const row = document.createElement("tr");
    const status = controller.status || (controller.online === true ? "Connected" : controller.online === false ? "Unavailable" : "--");
    const controls = controller.read_only ? "Read only" : "Unavailable";
    [gardenText(controller.controller_name), gardenText(status), gardenText(controller.active_watering_zone), gardenText(controller.next_watering_schedule), controller.rain_delay_active === true ? "Active" : controller.rain_delay_active === false ? "Inactive" : "--", gardenText(controller.zone_count), controls].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  });

  empty.style.display = "none";
  table.removeAttribute("hidden");
}

function renderZonesTable(zones, configured) {
  const table = document.getElementById("garden-zones-table");
  const empty = document.getElementById("garden-zones-empty");
  const body = document.getElementById("garden-zones-body");
  if (!table || !empty || !body) return;

  body.innerHTML = "";
  if (zones.length === 0) {
    table.setAttribute("hidden", "");
    empty.textContent = configured ? "No zones available." : "No irrigation entities were found in Home Assistant.";
    empty.style.display = "block";
    return;
  }

  zones.forEach((zone) => {
    const row = document.createElement("tr");
    const valveState = zone.status || zone.state || "--";
    const smartWatering = zone.smart_watering_state === "on" ? "On" : zone.smart_watering_state === "off" ? "Off" : "--";
    const remaining = zone.remaining_duration || zone.duration || "--";
    const availability = zone.availability === "available" ? "Available" : zone.availability === "unavailable" ? "Unavailable" : "--";
    const controls = zone.read_only ? "Read only" : "Unavailable";
    [gardenText(zone.zone_label || zone.friendly_name), gardenText(zone.controller_name), gardenText(valveState), gardenText(smartWatering), gardenText(remaining), gardenText(availability), controls].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  });

  empty.style.display = "none";
  table.removeAttribute("hidden");
}

function renderGreenhouseChart(greenhouse) {
  const chart = document.getElementById("garden-greenhouse-temperature-chart");
  if (!chart) return;

  const history = Array.isArray(greenhouse?.history_points) ? greenhouse.history_points : [];
  const points = history
    .map((row) => ({
      timestamp: row.timestamp,
      value: Number(row.value),
      unit: row.unit || greenhouse?.temperature_unit || "°F",
    }))
    .filter((row) => row.timestamp && Number.isFinite(row.value));

  if (!points.length) {
    chart.replaceChildren();
    renderEmptyState(
      "garden-greenhouse-temperature-chart",
      "No greenhouse temperature history is available yet.",
      "History will appear after the next genuine reading is stored.",
    );
    return;
  }

  renderCenterChart(chart, points, {
    digits: 1,
    yLabel: "°F",
    unit: "°F",
    xLabel: "Time",
    range: window.HomePulseHistory?.selectedRange(chart) || "1d",
    emptyMessage: "No greenhouse history available for this range yet.",
    onRangeChange: () => renderGreenhouseChart(greenhouse),
  });
}

function renderGreenhouseSection(greenhouse) {
  const current = greenhouse || {};
  setElementText("garden-greenhouse-status-badge", greenhouseStatusLabel(current));
  setElementText("garden-greenhouse-source-status", current.source_status ? current.source_status.replace(/_/g, " ") : "Unavailable");
  setElementText("garden-greenhouse-temperature", current.temperature_display || "Unavailable");
  setElementText("garden-greenhouse-humidity", current.humidity_display ? `Humidity ${current.humidity_display}` : "Humidity unavailable");
  setElementText("garden-greenhouse-temperature-band", current.temperature_band || "Unavailable");
  setElementText("garden-greenhouse-today-high", current.today_high || "Unavailable");
  setElementText("garden-greenhouse-today-low", current.today_low || "Unavailable");
  setElementText("garden-greenhouse-latest-reading", formatGardenTimestamp(current.latest_reading || current.source_timestamp || current.observed_at));
  setElementText("garden-greenhouse-updated", formatGardenTimestamp(current.observed_at || current.last_updated));
  setElementText("garden-greenhouse-source-timestamp", formatGardenTimestamp(current.source_timestamp));
  setElementText("garden-greenhouse-data-source", current.source ? current.source.replace(/_/g, " ") : current.source_status ? current.source_status.replace(/_/g, " ") : "Unavailable");
  setElementText("garden-greenhouse-message", current.message || "Greenhouse data is waiting for a usable reading.");

  const badge = document.getElementById("garden-greenhouse-status-badge");
  if (badge) {
    badge.className = "energy-status-badge";
    badge.classList.add(greenhouseBadgeClass(current));
    badge.textContent = greenhouseStatusLabel(current);
  }

  const band = document.getElementById("garden-greenhouse-temperature-band");
  if (band) {
    band.className = "greenhouse-band";
    const bandClass = String(current.temperature_band || "disabled").toLowerCase();
    band.classList.add(`greenhouse-band-${bandClass}`);
    band.textContent = current.temperature_band || "Unavailable";
  }

  setElementText("garden-greenhouse-history-meta", `${current.history_count || 0} samples`);
  renderGreenhouseChart(current);
}

function renderGardenSnapshot(snapshot) {
  if (snapshot && typeof snapshot === "object") {
    lastGardenSnapshot = snapshot;
  }
  const normalized = normalizeGardenSnapshot(lastGardenSnapshot);
  renderGardenSummary(normalized.garden || {});
  renderGreenhouseSection(normalized.greenhouse || {});
}

async function refreshGardenCenter() {
  const requestSeq = ++gardenRefreshSeq;
  try {
    const response = await fetch("/api/garden/status", { cache: "no-store" });
    if (requestSeq !== gardenRefreshSeq) return;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    if (requestSeq !== gardenRefreshSeq) return;
    renderGardenSnapshot(snapshot || {});
  } catch (error) {
    if (requestSeq !== gardenRefreshSeq) return;
    console.error("[GardenCenter] Refresh failed:", error);
    if (lastGardenSnapshot) {
      renderGardenSnapshot(lastGardenSnapshot);
    } else {
      setElementText("garden-status", "Unavailable");
      setElementText("garden-message", "Home Assistant irrigation data is unavailable.");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderGardenSnapshot(lastGardenSnapshot);
  refreshGardenCenter();
  setInterval(refreshGardenCenter, 30000);
});

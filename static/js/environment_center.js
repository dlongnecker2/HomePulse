function environmentBadgeClass(snapshot) {
  const status = String(snapshot?.status || "").toLowerCase();
  if (snapshot?.enabled === false || status.includes("disabled")) return "disabled";
  if (snapshot?.stale || status.includes("stale") || status.includes("unavailable")) return "offline";
  if (status.includes("connected") || status.includes("live") || status.includes("ready")) return "healthy";
  return "offline";
}

function entityLatestValue(entity) {
  const reading = entity?.latest_reading || {};
  if (reading.parsed_boolean !== null && reading.parsed_boolean !== undefined) {
    return reading.parsed_boolean ? "true" : "false";
  }
  if (reading.parsed_number !== null && reading.parsed_number !== undefined) {
    return String(reading.parsed_number);
  }
  return reading.raw_state || reading.raw_value || "Unavailable";
}

function entityLatestAge(entity) {
  const reading = entity?.latest_reading || {};
  return reading.timestamp || "never";
}

function entityHistoryHtml(history) {
  if (!history || history.length === 0) {
    return `
      <div class="center-empty-state">
        <p><strong>No history has been captured yet.</strong><br>
        This sensor will remain empty until a refresh records its first meaningful sample.</p>
      </div>
    `;
  }

  return `
    <div class="environment-history-list">
      ${history.map((row) => `
        <div class="environment-history-row">
          <div class="environment-history-time">${formatTimestamp(row.timestamp)}</div>
          <div class="environment-history-value">${row.raw_state ?? row.raw_value ?? "-"}</div>
          <div class="environment-history-meta">
            <span>${row.parsed_number ?? (row.parsed_boolean === null || row.parsed_boolean === undefined ? "-" : String(row.parsed_boolean))}</span>
            <span>${row.unit_of_measurement || "-"}</span>
            <span>${row.availability || "-"}</span>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderEnvironmentGroups(snapshot) {
  const container = document.getElementById("environment-groups");
  if (!container) return;

  const areas = Array.isArray(snapshot?.areas) ? snapshot.areas : [];
  if (areas.length === 0) {
    container.innerHTML = `
      <div class="center-empty-state">
        <p><strong>No supported environmental entities are cached yet.</strong><br>
        Home Assistant discovery will populate this view after the first successful refresh.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = areas.map((area) => `
    <article class="center-glass-card environment-area-card">
      <div class="center-card-heading">
        <div>
          <span class="center-kicker">Area</span>
          <h3>${area.display_name || area.area_name || "Unassigned Area"}</h3>
        </div>
        <span class="energy-status-badge ${area.fallback_group ? "disabled" : "healthy"}">${area.entity_count || 0} entities</span>
      </div>
      <div class="center-detail-list">
        <div><span>Area ID</span><strong>${area.area_id || "-"}</strong></div>
        <div><span>Readings</span><strong>${area.reading_count || 0}</strong></div>
        <div><span>Devices</span><strong>${Array.isArray(area.devices) ? area.devices.length : 0}</strong></div>
      </div>
      <div class="environment-device-list">
        ${(area.devices || []).map((device) => `
          <div class="environment-device-card">
            <div class="environment-device-heading">
              <strong>${device.display_name || device.device_name || "Unassigned Device"}</strong>
              <span class="environment-device-meta">${device.entity_count || 0} entities</span>
            </div>
            <div class="environment-device-meta">Device ID: ${device.device_id || "-"}</div>
            <ul class="environment-entity-list">
              ${(device.entities || []).map((entity) => `
                <li>
                  <button
                    type="button"
                    class="environment-entity-button"
                    data-entity-id="${entity.entity_id}"
                    data-entity-name="${entity.display_name || entity.entity_name || entity.entity_id}"
                  >
                    <span class="environment-entity-name">${entity.display_name || entity.entity_name || entity.entity_id}</span>
                    <span class="environment-entity-state">${entityLatestValue(entity)}</span>
                  </button>
                </li>
              `).join("")}
            </ul>
          </div>
        `).join("")}
      </div>
    </article>
  `).join("");
}

function renderEnvironmentTable(snapshot) {
  const tbody = document.getElementById("environment-readings-body");
  if (!tbody) return;

  const entities = Array.isArray(snapshot?.entities) ? snapshot.entities : [];
  if (entities.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty">No entity readings have been captured yet.</td></tr>';
    return;
  }

  tbody.innerHTML = entities.slice(0, 25).map((entity) => {
    const reading = entity.latest_reading || {};
    return `
      <tr data-entity-id="${entity.entity_id}" data-entity-name="${entity.display_name || entity.entity_name || entity.entity_id}">
        <td>
          <strong>${entity.display_name || entity.entity_name || entity.entity_id}</strong><br>
          <span class="table-muted">${entity.entity_id}</span>
        </td>
        <td>${entity.area_name || "-"}</td>
        <td>${entity.device_name || "-"}</td>
        <td>${reading.raw_state ?? reading.raw_value ?? "No readings"}</td>
        <td>${reading.parsed_number ?? (reading.parsed_boolean === null || reading.parsed_boolean === undefined ? "-" : String(reading.parsed_boolean))}</td>
        <td>${entity.unit_of_measurement || "-"}</td>
        <td>${reading.timestamp || "-"}</td>
      </tr>
    `;
  }).join("");
}

function renderEnvironmentSnapshot(snapshot) {
  const badge = document.getElementById("environment-status-badge");
  if (badge) {
    badge.classList.remove("healthy", "offline", "disabled");
    badge.classList.add(environmentBadgeClass(snapshot));
    badge.textContent = snapshot?.status || "Unavailable";
  }

  setElementText("environment-summary-status", snapshot?.status || "Unavailable");
  setElementText("environment-summary-message", snapshot?.message || "Waiting for data");
  setElementText("environment-summary-age", snapshot?.snapshot_age_label || "never");
  setElementText("environment-summary-stale", snapshot?.stale ? "Stale snapshot" : "Live cache");
  setElementText("environment-summary-entities", snapshot?.summary?.supported_entities ?? 0);
  setElementText("environment-summary-readings", snapshot?.summary?.readings_recorded ?? 0);
  setElementText("environment-summary-areas", `${snapshot?.summary?.areas ?? 0} areas`);
  setElementText("environment-summary-devices", `${snapshot?.summary?.devices ?? 0} devices`);
  setElementText("environment-last-refresh", snapshot?.last_successful_refresh || "No successful refresh yet");

  renderEnvironmentGroups(snapshot);
  renderEnvironmentTable(snapshot);
}

async function loadSelectedEntityHistory(entityId, entityName) {
  const title = document.getElementById("environment-history-title");
  const idLabel = document.getElementById("environment-history-entity");
  const countLabel = document.getElementById("environment-history-count");
  const lastLabel = document.getElementById("environment-history-last");
  const series = document.getElementById("environment-history-series");
  if (!title || !idLabel || !countLabel || !lastLabel || !series) return;

  title.textContent = entityName || "Entity history";
  idLabel.textContent = entityId;
  countLabel.textContent = "Loading...";
  lastLabel.textContent = "Loading...";
  series.innerHTML = '<div class="center-loading"></div>';

  try {
    const response = await fetch(`/api/environment/history/${encodeURIComponent(entityId)}?limit=50`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const history = Array.isArray(payload.history) ? payload.history : [];
    countLabel.textContent = String(history.length);
    lastLabel.textContent = history.length ? formatTimestamp(history[history.length - 1].timestamp) : "-";
    series.innerHTML = entityHistoryHtml(history);
  } catch (error) {
    console.error("[EnvironmentCenter] History load failed:", error);
    countLabel.textContent = "0";
    lastLabel.textContent = "-";
    series.innerHTML = `
      <div class="center-empty-state">
        <p><strong>History is unavailable right now.</strong><br>
        ${String(error.message || error)}</p>
      </div>
    `;
  }
}

function bindEnvironmentInteractions() {
  document.addEventListener("click", (event) => {
    const entityButton = event.target.closest(".environment-entity-button");
    if (entityButton) {
      loadSelectedEntityHistory(
        entityButton.dataset.entityId,
        entityButton.dataset.entityName || entityButton.dataset.entityId,
      );
      return;
    }

    const entityRow = event.target.closest("#environment-readings-body tr[data-entity-id]");
    if (entityRow) {
      loadSelectedEntityHistory(
        entityRow.dataset.entityId,
        entityRow.dataset.entityName || entityRow.dataset.entityId,
      );
    }
  });
}

async function refreshEnvironmentCenter() {
  try {
    const response = await fetch("/api/environment/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    renderEnvironmentSnapshot(snapshot);
  } catch (error) {
    console.error("[EnvironmentCenter] Refresh failed:", error);
    setElementText("environment-summary-status", "Unavailable");
    setElementText("environment-summary-message", "Cached snapshot unavailable");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  bindEnvironmentInteractions();
  renderEnvironmentSnapshot(window.HomePulseEnvironmentInitial || {});
  refreshEnvironmentCenter();
  setInterval(refreshEnvironmentCenter, 30000);
});

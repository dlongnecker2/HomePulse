const INTERNET_STATE = {
  mesh: null,
  filteredClients: [],
};

const INTERNET_REFRESH_MS = 30000;

async function fetchMeshStatus() {
  try {
    const response = await fetch("/api/network/mesh", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    return {
      data_available: false,
      message: "Mesh data is unavailable right now.",
      timestamp: new Date().toISOString(),
      nodes: [],
      clients: [],
      summary: {
        internet_online: null,
        mesh_nodes_online: 0,
        mesh_nodes_total: 0,
        connected_clients: 0,
        current_total_down_kbps: null,
        current_total_up_kbps: null,
      },
      insights: [],
      error: String(error),
    };
  }
}

function formatRate(value) {
  const num = parseNumber(value);
  if (num === null) return "-";
  return `${num.toFixed(1)} KB/s`;
}

function formatDeviceType(type) {
  const map = {
    phone: "Phone",
    computer: "Computer",
    printer: "Printer",
    streaming: "Streaming",
    "smart home": "Smart Home",
    vehicle: "Vehicle",
    unknown: "Unknown",
  };
  return map[String(type || "").toLowerCase()] || "Unknown";
}

function updateInternetBadge(mesh) {
  const badge = document.getElementById("internet-module-status-badge");
  if (!badge) return;

  const summary = mesh.summary || {};
  const dataAvailable = Boolean(mesh.data_available);
  let text = "Unavailable";
  if (summary.internet_online === true) text = dataAvailable ? "Online" : "Internet OK";
  else if (summary.internet_online === false) text = "Attention";
  else if (dataAvailable) text = "Live";

  badge.textContent = text;
  badge.className = "energy-status-badge";
  if (text === "Online" || text === "Live") badge.classList.add("charging");
  else if (text === "Internet OK") badge.classList.add("idle");
  else badge.classList.add("offline");
}

function updateOverview(mesh) {
  const summary = mesh.summary || {};
  setElementText("mesh-summary-nodes", `${summary.mesh_nodes_online ?? 0}/${summary.mesh_nodes_total ?? 0}`);
  setElementText("mesh-summary-clients", `Clients ${summary.connected_clients ?? 0}`);
  setElementText(
    "mesh-summary-traffic",
    `${formatRate(summary.current_total_down_kbps)} down / ${formatRate(summary.current_total_up_kbps)} up`,
  );
  setElementText("mesh-last-updated", `Updated ${formatTimestamp(mesh.timestamp)}`);
  setElementText("mesh-status-message", mesh.message || "Mesh data loaded.");
}

function renderNodeCards(mesh) {
  const container = document.getElementById("mesh-node-cards");
  if (!container) return;

  const nodes = Array.isArray(mesh.nodes) ? mesh.nodes : [];
  if (!mesh.data_available) {
    container.innerHTML = '<div class="center-empty-state"><p>Home Assistant Deco data is unavailable. Existing Internet health features remain active.</p></div>';
    return;
  }
  if (!nodes.length) {
    container.innerHTML = '<div class="center-empty-state"><p>No Deco node entities were found in Home Assistant.</p></div>';
    return;
  }

  container.innerHTML = nodes
    .map((node) => {
      const online = node.online === true;
      const status = online ? "Online" : node.online === false ? "Offline" : "Unknown";
      const statusClass = mapStatusClass(status);
      return `
        <article class="internet-node-card">
          <div class="internet-node-header">
            <h4>${node.name || "Deco Node"}</h4>
            <span class="${statusClass}">${status}</span>
          </div>
          <div class="internet-node-metrics">
            <div><span>Clients</span><strong>${node.connected_clients ?? "-"}</strong></div>
            <div><span>Down</span><strong>${formatRate(node.down_kbps)}</strong></div>
            <div><span>Up</span><strong>${formatRate(node.up_kbps)}</strong></div>
            <div><span>Firmware</span><strong>${node.firmware || "-"}</strong></div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderBarList(elementId, rows, valueSelector, emptyText) {
  const container = document.getElementById(elementId);
  if (!container) return;

  const values = rows.map((row) => Number(valueSelector(row) || 0));
  const maxValue = values.length ? Math.max(...values) : 0;
  if (!rows.length || maxValue <= 0) {
    container.innerHTML = `<div class="table-empty">${emptyText}</div>`;
    return;
  }

  container.innerHTML = rows
    .map((row) => {
      const value = Number(valueSelector(row) || 0);
      const width = maxValue > 0 ? Math.max(4, Math.round((value / maxValue) * 100)) : 0;
      return `
        <div class="internet-bar-row">
          <div class="internet-bar-label">${row.name || "Unknown"}</div>
          <div class="internet-bar-track"><div class="internet-bar-fill" style="width:${width}%"></div></div>
          <div class="internet-bar-value">${value}</div>
        </div>
      `;
    })
    .join("");
}

function renderNodeBars(mesh) {
  const nodes = Array.isArray(mesh.nodes) ? mesh.nodes : [];
  const clientRows = nodes.map((node) => ({ name: node.name || "Unknown", clients: Number(node.connected_clients || 0) }));
  const trafficRows = nodes.map((node) => {
    const down = Number(parseNumber(node.down_kbps) || 0);
    const up = Number(parseNumber(node.up_kbps) || 0);
    return { name: node.name || "Unknown", traffic: Number((down + up).toFixed(1)) };
  });

  renderBarList("mesh-client-bars", clientRows, (row) => row.clients, "No client distribution data yet.");
  renderBarList("mesh-traffic-bars", trafficRows, (row) => row.traffic, "No traffic telemetry reported by nodes.");
}

function iconForDevice(deviceType) {
  const map = {
    phone: "PHN",
    computer: "PC",
    printer: "PRN",
    streaming: "TV",
    "smart home": "IOT",
    vehicle: "EV",
    unknown: "?",
  };
  return map[String(deviceType || "").toLowerCase()] || "?";
}

function renderDevicesTable(clients) {
  const tbody = document.getElementById("mesh-devices-tbody");
  if (!tbody) return;

  if (!clients.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="table-empty">No connected client data is available.</td></tr>';
    return;
  }

  tbody.innerHTML = clients
    .map((client) => {
      const type = formatDeviceType(client.device_type);
      const state = String(client.state || "unknown");
      return `
        <tr>
          <td><span class="internet-device-icon">${iconForDevice(type)}</span> ${client.friendly_name || client.name || "Unknown"}<div class="internet-device-type">${type}</div></td>
          <td>${client.deco_node || "-"}</td>
          <td>${client.band || "-"}${client.connection_type ? ` / ${client.connection_type}` : ""}</td>
          <td>${client.ip || "-"}</td>
          <td>${formatRate(client.down_kbps)}</td>
          <td>${formatRate(client.up_kbps)}</td>
          <td>${formatTimestamp(client.last_updated)}</td>
          <td><span class="${mapStatusClass(state)}">${state}</span></td>
        </tr>
      `;
    })
    .join("");
}

function applyDeviceFilter() {
  const search = document.getElementById("mesh-device-search");
  if (!search) return;

  const term = String(search.value || "").trim().toLowerCase();
  const clients = Array.isArray(INTERNET_STATE.mesh?.clients) ? INTERNET_STATE.mesh.clients : [];
  if (!term) {
    INTERNET_STATE.filteredClients = clients;
    renderDevicesTable(clients);
    return;
  }

  const filtered = clients.filter((client) => {
    const blob = [
      client.name,
      client.friendly_name,
      client.ip,
      client.mac,
      client.deco_node,
      client.band,
      client.connection_type,
      client.device_type,
      client.state,
    ]
      .map((part) => String(part || "").toLowerCase())
      .join(" ");
    return blob.includes(term);
  });
  INTERNET_STATE.filteredClients = filtered;
  renderDevicesTable(filtered);
}

function renderInsights(mesh) {
  const insightsContainer = document.getElementById("mesh-insights-list");
  if (insightsContainer) {
    const rows = Array.isArray(mesh.insights) ? mesh.insights : [];
    if (!rows.length) {
      insightsContainer.innerHTML = '<div><span>Insights</span><strong>No additional network insights are available yet.</strong></div>';
    } else {
      insightsContainer.innerHTML = rows
        .map((item) => `<div><span>${item.type || "Insight"}</span><strong>${item.message || "-"}</strong></div>`)
        .join("");
    }
  }

  const clients = Array.isArray(mesh.clients) ? mesh.clients : [];
  const bands = { "2.4 GHz": 0, "5 GHz": 0, "6 GHz": 0, Unknown: 0 };
  clients.forEach((client) => {
    const band = String(client.band || "").trim();
    if (band === "2.4 GHz" || band === "5 GHz" || band === "6 GHz") bands[band] += 1;
    else bands.Unknown += 1;
  });
  setElementText("mesh-band-24", String(bands["2.4 GHz"]));
  setElementText("mesh-band-5", String(bands["5 GHz"]));
  setElementText("mesh-band-6", String(bands["6 GHz"]));
  setElementText("mesh-band-unknown", String(bands.Unknown));
}

async function refreshMeshData() {
  const mesh = await fetchMeshStatus();
  INTERNET_STATE.mesh = mesh;
  updateInternetBadge(mesh);
  updateOverview(mesh);
  renderNodeCards(mesh);
  renderNodeBars(mesh);
  renderDevicesTable(Array.isArray(mesh.clients) ? mesh.clients : []);
  renderInsights(mesh);
}

function setupInternetCenterTabs() {
  setupCenterTabs((tab) => {
    if (tab === "devices") applyDeviceFilter();
  });
}

function setupDeviceSearch() {
  const input = document.getElementById("mesh-device-search");
  if (!input) return;
  input.addEventListener("input", () => applyDeviceFilter());
}

document.addEventListener("DOMContentLoaded", async () => {
  if (!document.querySelector('[data-module="internet-center"]')) return;
  setupInternetCenterTabs();
  setupDeviceSearch();
  await refreshMeshData();
  setInterval(() => {
    refreshMeshData();
  }, INTERNET_REFRESH_MS);
});

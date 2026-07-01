function setAdminStatus(message) {
  const element = document.getElementById("admin-action-status");
  if (element) element.textContent = message;
}

function setSystemStatus(key, value) {
  const element = document.querySelector(`[data-system-status="${key}"]`);
  if (element) element.textContent = value === null || value === undefined || value === "" ? "--" : String(value);
}

function formatUptime(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total)) return "Unknown";
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = Math.floor(total % 60);
  if (days) return `${days}d ${hours}h ${minutes}m`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remaining}s`;
  return `${remaining}s`;
}

function lastRestartText(value) {
  if (!value) return "None recorded";
  if (typeof value === "object") {
    return `${value.timestamp || "Unknown"} (PID ${value.pid || "Unknown"})`;
  }
  return String(value);
}

async function refreshSystemStatus() {
  try {
    const response = await fetch("/api/system/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`System status returned ${response.status}`);
    const data = await response.json();
    setSystemStatus("pid", data.pid);
    setSystemStatus("started_at", data.started_at);
    setSystemStatus("uptime", formatUptime(data.uptime_seconds));
    setSystemStatus("version", data.version);
    setSystemStatus("executable", data.executable);
    setSystemStatus("working_directory", data.working_directory);
    setSystemStatus("restart_supported", data.restart_supported ? "Enabled" : "Disabled");
    setSystemStatus("last_restart_request", lastRestartText(data.last_restart_request));
  } catch (error) {
    setAdminStatus("System status refresh failed. Check logs for details.");
  }
}

async function runAdminAction(action) {
  const label = action === "shutdown" ? "Stop HomePulse" : "Restart HomePulse";
  const prompt = action === "shutdown" ? "Stop HomePulse now?" : "Restart HomePulse now?";
  if (!window.confirm(prompt)) return;
  setAdminStatus(`${label} requested...`);
  try {
    const response = await fetch(`/api/system/${action}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-HomePulse-Admin-Token": window.HomePulseAdminActionToken || "",
      },
      body: JSON.stringify({ admin_token: window.HomePulseAdminActionToken || "" }),
    });
    const payload = await response.json();
    setAdminStatus(payload.message || `${label} response: ${response.status}`);
    refreshSystemStatus();
  } catch (error) {
    setAdminStatus(`${label} request failed. Check logs for details.`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  refreshSystemStatus();
  document.querySelectorAll("[data-admin-action]").forEach((button) => {
    button.addEventListener("click", () => runAdminAction(button.dataset.adminAction));
  });
  setInterval(refreshSystemStatus, 30000);
});

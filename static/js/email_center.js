async function loadSolarAlertSettings() {
  try {
    const response = await fetch("/api/email/notification-settings", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    const settings = payload.solar_alerts || {};

    const enabled = document.getElementById("solar-alert-enabled");
    const system = document.getElementById("solar-alert-system");
    const envoy = document.getElementById("solar-alert-envoy");
    const inverter = document.getElementById("solar-alert-inverter");
    const cooldown = document.getElementById("solar-alert-cooldown");
    const checks = document.getElementById("solar-alert-min-checks");

    if (enabled) enabled.checked = Boolean(settings.enabled);
    if (system) system.checked = Boolean(settings.system_down_enabled);
    if (envoy) envoy.checked = Boolean(settings.envoy_unreachable_enabled);
    if (inverter) inverter.checked = Boolean(settings.inverter_fault_enabled);
    if (cooldown && settings.cooldown_hours !== undefined) cooldown.value = Number(settings.cooldown_hours);
    if (checks && settings.min_consecutive_checks !== undefined) checks.value = Number(settings.min_consecutive_checks);
  } catch (error) {
    // Keep server-rendered defaults if loading fails.
  }
}

function updateSolarSettingsStatus(text, isError = false) {
  const status = document.getElementById("solar-alert-settings-status");
  if (!status) return;
  status.textContent = text;
  status.classList.toggle("status-error", Boolean(isError));
  status.classList.toggle("status-ok", !isError);
}

async function saveSolarAlertSettings(event) {
  event.preventDefault();
  const payload = {
    enabled: Boolean(document.getElementById("solar-alert-enabled")?.checked),
    system_down_enabled: Boolean(document.getElementById("solar-alert-system")?.checked),
    envoy_unreachable_enabled: Boolean(document.getElementById("solar-alert-envoy")?.checked),
    inverter_fault_enabled: Boolean(document.getElementById("solar-alert-inverter")?.checked),
    cooldown_hours: Number(document.getElementById("solar-alert-cooldown")?.value || 6),
    min_consecutive_checks: Number(document.getElementById("solar-alert-min-checks")?.value || 2),
  };

  updateSolarSettingsStatus("Saving...");

  try {
    const response = await fetch("/api/email/notification-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    updateSolarSettingsStatus("Saved");
  } catch (error) {
    updateSolarSettingsStatus(`Save failed: ${String(error)}`, true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("solar-alert-settings-form");
  if (!form) return;
  form.addEventListener("submit", saveSolarAlertSettings);
  loadSolarAlertSettings();
});

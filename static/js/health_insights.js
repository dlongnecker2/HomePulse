const healthInsightsRefreshButton = document.getElementById("health-insights-refresh");
const healthInsightsRefreshStatus = document.getElementById("health-insights-refresh-status");
let healthInsightsPollTimer = null;

function setHealthInsightsStatus(message, kind = "info", status = "") {
  if (!healthInsightsRefreshStatus) return;
  healthInsightsRefreshStatus.hidden = false;
  healthInsightsRefreshStatus.className = `settings-message ${kind}`;
  healthInsightsRefreshStatus.dataset.status = status;
  healthInsightsRefreshStatus.textContent = message;
}

function stopHealthInsightsPolling() {
  if (healthInsightsPollTimer !== null) {
    window.clearTimeout(healthInsightsPollTimer);
    healthInsightsPollTimer = null;
  }
}

async function pollHealthInsightsRefresh() {
  try {
    const response = await fetch("/api/health-insights/status", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Health Insights status is unavailable.");
    }
    const refresh = payload.health_insights?.manual_refresh || {};
    const status = refresh.status || "idle";
    if (status === "running") {
      setHealthInsightsStatus(refresh.message || "Refreshing health data.", "info", status);
      healthInsightsPollTimer = window.setTimeout(pollHealthInsightsRefresh, 1500);
      return;
    }
    if (status === "succeeded") {
      setHealthInsightsStatus(refresh.message || "Health data refreshed.", "success", status);
      window.setTimeout(() => window.location.reload(), 700);
      return;
    }
    if (status === "failed") {
      setHealthInsightsStatus(refresh.message || "Health data refresh failed.", "error", status);
      if (healthInsightsRefreshButton) healthInsightsRefreshButton.disabled = false;
      return;
    }
    if (healthInsightsRefreshButton) healthInsightsRefreshButton.disabled = false;
  } catch (error) {
    setHealthInsightsStatus(
      error.message || "Health Insights status is unavailable.",
      "error",
      "failed"
    );
    if (healthInsightsRefreshButton) healthInsightsRefreshButton.disabled = false;
  }
}

async function startHealthInsightsRefresh() {
  if (!healthInsightsRefreshButton) return;
  stopHealthInsightsPolling();
  healthInsightsRefreshButton.disabled = true;
  setHealthInsightsStatus("Starting health data refresh.", "info", "starting");
  try {
    const response = await fetch("/api/health-insights/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok && response.status !== 409) {
      throw new Error(payload.error || payload.message || "Health data refresh could not start.");
    }
    setHealthInsightsStatus(payload.message || "Health data refresh started.", "info", "running");
    healthInsightsPollTimer = window.setTimeout(pollHealthInsightsRefresh, 500);
  } catch (error) {
    setHealthInsightsStatus(
      error.message || "Health data refresh could not start.",
      "error",
      "failed"
    );
    healthInsightsRefreshButton.disabled = false;
  }
}

if (healthInsightsRefreshButton) {
  healthInsightsRefreshButton.addEventListener("click", startHealthInsightsRefresh);
}

if (healthInsightsRefreshStatus?.dataset.status === "running") {
  if (healthInsightsRefreshButton) healthInsightsRefreshButton.disabled = true;
  healthInsightsPollTimer = window.setTimeout(pollHealthInsightsRefresh, 500);
}

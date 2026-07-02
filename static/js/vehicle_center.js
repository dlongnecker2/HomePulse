/**
 * VEHICLE CENTER
 * ==============
 * Uses Center Framework for tab management and utilities
 * Implements 5 tabs: Overview, Battery, Charging, Efficiency, Analytics
 */

const VEHICLE_STATE = {
  data: {},
  history: {},
  lastUpdate: null,
};

// ============================================================================
// TAB SETUP (Using Framework)
// ============================================================================

function setupVehicleTabs() {
  setupCenterTabs((tab) => {
    loadTabData(tab);
  });
}

async function loadTabData(tab) {
  switch (tab) {
    case "overview":
      await refreshOverviewTab();
      break;
    case "battery":
      await refreshBatteryTab();
      break;
    case "charging":
      await refreshChargingTab();
      break;
    case "efficiency":
      await refreshEfficiencyTab();
      break;
    case "analytics":
      await refreshAnalyticsTab();
      break;
  }
}

// ============================================================================
// TAB 1: OVERVIEW
// ============================================================================

async function refreshOverviewTab() {
  try {
    const [vehicle, batteryHistory] = await Promise.all([
      fetchJSON("/api/vehicle/status"),
      fetchJSON("/api/history/metrics?module=vehicle&metric=battery_percent&range=1d"),
    ]);

    // API returns the status object directly (not wrapped under a 'status' key)
    const status = vehicle || {};
    VEHICLE_STATE.data = status;
    VEHICLE_STATE.history = batteryHistory.points || [];

    updateOverviewUI(status);
  } catch (error) {
    console.error("Overview tab error:", error);
  }
}

function updateOverviewUI(status) {
  // Determine online state from availability string returned by the API
  // "live" and "partial" = data available; all others = offline/unavailable
  const availability = status.availability || "disabled";
  const isOnline = availability === "live" || availability === "partial";
  const badge = isOnline ? "Connected" : "Offline";

  if (!status.vehicle_name) {
    console.warn("[VehicleCenter] updateOverviewUI: vehicle_name missing — check /api/vehicle/status response", status);
  }

  setElementText("vehicle-overview-name", status.vehicle_name || "Vehicle");
  setElementText("vehicle-overview-badge", badge);
  setElementText("vehicle-overview-battery",
    status.battery_percent != null ? `${status.battery_percent}%` : "-");
  setElementText("vehicle-overview-range",
    status.range_mi != null ? `${status.range_mi} mi` : "-");
  setElementText("vehicle-overview-plug", status.plug_state || "-");
  setElementText("vehicle-overview-charging", status.charging_state || "-");
  setElementText("vehicle-overview-odometer",
    status.odometer_mi != null ? `${status.odometer_mi} mi` : "-");
  setElementText("vehicle-overview-energy",
    formatMetric(status.lifetime_energy_kwh, "kWh", 2));
  setElementText("vehicle-overview-lifetime-eff",
    status.lifetime_efficiency_mi_per_kwh != null
      ? `${status.lifetime_efficiency_mi_per_kwh.toFixed(2)} mi/kWh` : "-");
  setElementText("vehicle-overview-cost-mile", formatCurrency(status.cost_per_mile));
  setElementText("vehicle-overview-updated", formatTimestamp(status.last_update));

  // Summary row
  setElementText("vehicle-summary-miles",
    status.odometer_mi != null ? `${status.odometer_mi} mi` : "-");
  setElementText("vehicle-summary-efficiency",
    status.lifetime_efficiency_mi_per_kwh != null
      ? `${status.lifetime_efficiency_mi_per_kwh.toFixed(2)} mi/kWh` : "-");
  setElementText(
    "vehicle-summary-cost",
    status.estimated_lifetime_cost != null
      ? formatCurrency(status.estimated_lifetime_cost)
      : "-"
  );

  // Update badge color
  const moduleBadge = document.getElementById("vehicle-overview-badge");
  if (moduleBadge) {
    moduleBadge.className = "energy-status-badge";
    moduleBadge.classList.add(isOnline ? "charging" : "offline");
  }

  // Update module-level badge
  const headerBadge = document.getElementById("vehicle-module-status-badge");
  if (headerBadge) {
    headerBadge.className = "energy-status-badge";
    headerBadge.classList.add(isOnline ? "charging" : "offline");
    headerBadge.textContent = badge;
  }
}

// ============================================================================
// TAB 2: BATTERY
// ============================================================================

async function refreshBatteryTab() {
  try {
    const chartEl = document.getElementById("vehicle-battery-chart");
    const range = window.HomePulseHistory?.selectedRange(chartEl) || "1d";
    console.debug(`[VehicleCenter] Battery chart range selected: ${range}`);

    const [vehicle, batteryHistory] = await Promise.all([
      fetchJSON("/api/vehicle/status"),
      fetchJSON(`/api/history/metrics?module=vehicle&metric=battery_percent&range=${encodeURIComponent(range)}`),
    ]);

    console.debug(`[VehicleCenter] Battery history points returned: ${(batteryHistory.points || []).length}`);
    const status = vehicle || {};
    updateBatteryUI(status, batteryHistory.points || []);
    renderCenterChart(chartEl, batteryHistory.points || [], {
      digits: 1,
      yLabel: "%",
      unit: "%",
      xLabel: "Time",
      range,
      emptyMessage: "No battery history available for this range.",
      onRangeChange: refreshBatteryTab,
    });
  } catch (error) {
    console.error("Battery tab error:", error);
  }
}

function updateBatteryUI(status, points) {
  const currentBattery = status.battery_percent || 0;
  const previousBattery = points.length > 0 ? parseNumber(points[0].value || points[0].battery_percent) : currentBattery;
  const trend = calculateTrend(currentBattery, previousBattery);

  setElementText("vehicle-battery-percent", `${currentBattery}%`);
  setElementText("vehicle-battery-trend", trend);
  setElementText("vehicle-battery-range", status.range_mi != null ? `${status.range_mi} mi` : "-");

  // Low battery warning
  const warning = currentBattery < 20 ? `Low (${currentBattery}%)` : "Normal";
  const warningClass = currentBattery < 20 ? "status-warning" : "status-ok";
  const warningEl = document.getElementById("vehicle-battery-warning");
  if (warningEl) {
    warningEl.className = warningClass;
    warningEl.textContent = warning;
  }

  // Battery health (placeholder - would come from degradation analysis)
  setElementText("vehicle-battery-health", "Good");
  setElementText("vehicle-battery-last-charge", status.last_charge_time || "-");
  setElementText("vehicle-battery-cycles", status.charge_cycles || "-");
}

// ============================================================================
// TAB 3: CHARGING
// ============================================================================

async function refreshChargingTab() {
  try {
    const vehicle = await fetchJSON("/api/vehicle/status");
    const status = vehicle || {};
    updateChargingUI(status);
    // No vehicle charging session history metric is stored; show a permanent empty state
    renderCenterChart(document.getElementById("vehicle-charging-chart"), [], {
      digits: 2,
      yLabel: "kW",
      unit: "kW",
      xLabel: "Time",
      range: "1d",
      emptyMessage: "No charging session history available.",
    });
  } catch (error) {
    console.error("Charging tab error:", error);
  }
}

function updateChargingUI(status) {
  const isCharging = status.charging_state === "Charging";
  const chargingPower = status.chargepoint_power_kw || 0;
  const sessionEnergy = status.chargepoint_session_kwh || 0;

  setElementText("vehicle-charging-plug", status.plug_state || "-");
  setElementText("vehicle-charging-state", status.charging_state || "-");
  setElementText("vehicle-charging-power", chargingPower > 0 ? formatMetric(chargingPower, "kW", 2) : "Not charging");
  setElementText("vehicle-charging-energy", formatMetric(sessionEnergy, "kWh", 2));

  // Estimates
  const milesAdded = sessionEnergy * 4; // Approx 4 miles per kWh
  const chargingCost = sessionEnergy * 0.13; // Assume $0.13/kWh
  setElementText("vehicle-charging-miles", formatMetric(milesAdded, "mi", 0));
  setElementText("vehicle-charging-cost", formatCurrency(chargingCost));
  setElementText("vehicle-charging-time", isCharging ? "Calculating..." : "-");

  // ChargePoint status
  const cpStatus = status.chargepoint_connected ? "Connected" : "N/A";
  const cpStatusEl = document.getElementById("vehicle-charging-cp-status");
  if (cpStatusEl) {
    cpStatusEl.className = status.chargepoint_connected ? "status-ok" : "status-warning";
    cpStatusEl.textContent = cpStatus;
  }
}

// ============================================================================
// TAB 4: EFFICIENCY
// ============================================================================

async function refreshEfficiencyTab() {
  try {
    const chartEl = document.getElementById("vehicle-efficiency-chart");
    const range = window.HomePulseHistory?.selectedRange(chartEl) || "1d";
    console.debug(`[VehicleCenter] Efficiency chart range selected: ${range}`);

    const [vehicle, efficiencyHistory] = await Promise.all([
      fetchJSON("/api/vehicle/status"),
      // History metric key is lifetime_efficiency_mi_per_kwh (matches collect_vehicle in service.py)
      fetchJSON(`/api/history/metrics?module=vehicle&metric=lifetime_efficiency_mi_per_kwh&range=${encodeURIComponent(range)}`),
    ]);

    console.debug(`[VehicleCenter] Efficiency history points returned: ${(efficiencyHistory.points || []).length}`);
    const status = vehicle || {};
    updateEfficiencyUI(status);
    renderCenterChart(chartEl, efficiencyHistory.points || [], {
      digits: 2,
      yLabel: "mi/kWh",
      unit: "mi/kWh",
      xLabel: "Time",
      range,
      emptyMessage: "No efficiency history available for this range.",
      onRangeChange: refreshEfficiencyTab,
    });
  } catch (error) {
    console.error("Efficiency tab error:", error);
  }
}

function updateEfficiencyUI(status) {
  const lifetimeKwh = status.lifetime_energy_kwh || 0;
  const lifetimeEfficiency = status.lifetime_efficiency_mi_per_kwh || 0;
  const odometer = status.odometer_mi || 0;
  // Use API-calculated lifetime cost when available, otherwise estimate at $0.13/kWh
  const costPerKwh = 0.13;
  const lifetimeCost = status.estimated_lifetime_cost != null
    ? status.estimated_lifetime_cost
    : lifetimeKwh * costPerKwh;
  const costPerMile = status.cost_per_mile || 0;

  // Lifetime Stats
  setElementText("vehicle-efficiency-lifetime-mi-per-kwh",
    lifetimeEfficiency ? `${lifetimeEfficiency.toFixed(2)} mi/kWh` : "-");
  setElementText("vehicle-efficiency-total-kwh", formatMetric(lifetimeKwh, "kWh", 2));
  setElementText("vehicle-efficiency-odometer", odometer ? `${odometer} mi` : "-");
  setElementText("vehicle-efficiency-lifetime-cost", formatCurrency(lifetimeCost || null));

  // Cost Analysis
  setElementText("vehicle-efficiency-cost-per-mile", formatCurrency(costPerMile || null));
  setElementText("vehicle-efficiency-cost-per-kwh", formatCurrency(costPerKwh));
  setElementText("vehicle-efficiency-rate", formatCurrency(costPerKwh));
}

// ============================================================================
// TAB 5: ANALYTICS
// ============================================================================

async function refreshAnalyticsTab() {
  try {
    const vehicle = await fetchJSON("/api/vehicle/status");
    const status = vehicle || {};
    updateAnalyticsUI(status);
  } catch (error) {
    console.error("Analytics tab error:", error);
  }
}

function updateAnalyticsUI(status) {
  const battery = status.battery_percent || 0;
  const range = status.range_mi || 0;
  const odometer = status.odometer_mi || 0;
  const energy = status.lifetime_energy_kwh || 0;
  const efficiency = status.lifetime_efficiency_mi_per_kwh || 0;
  const costPerMile = status.cost_per_mile || 0;
  const costPerKwh = 0.13; // Assume rate
  const lifetimeCost = status.estimated_lifetime_cost != null ? status.estimated_lifetime_cost : energy * costPerKwh;
  const milesPerDollar = costPerMile > 0 ? 1 / costPerMile : 0;

  // KPI Cards
  setElementText("vehicle-analytics-battery", `${battery}%`);
  setElementText("vehicle-analytics-battery-sub", "Current level");

  setElementText("vehicle-analytics-range", `${range} mi`);
  setElementText("vehicle-analytics-range-sub", "Estimated");

  setElementText("vehicle-analytics-odometer", `${odometer} mi`);
  setElementText("vehicle-analytics-odometer-sub", "Total miles");

  setElementText("vehicle-analytics-energy", formatMetric(energy, "kWh", 0));
  setElementText("vehicle-analytics-energy-sub", "Total used");

  setElementText("vehicle-analytics-lifetime-cost", formatCurrency(lifetimeCost));
  setElementText("vehicle-analytics-lifetime-cost-sub", "Electricity cost");

  setElementText("vehicle-analytics-cost-per-mile", formatCurrency(costPerMile));
  setElementText("vehicle-analytics-cost-per-mile-sub", "Average");

  setElementText("vehicle-analytics-miles-per-dollar", `${milesPerDollar.toFixed(1)} mi/$`);
  setElementText("vehicle-analytics-miles-per-dollar-sub", "Efficiency value");

  setElementText("vehicle-analytics-efficiency", `${efficiency.toFixed(2)} mi/kWh`);
  setElementText("vehicle-analytics-efficiency-sub", "Lifetime");
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  setupVehicleTabs();
  refreshOverviewTab();
  setInterval(refreshOverviewTab, 30000);
});

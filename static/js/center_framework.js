/**
 * CENTER FRAMEWORK
 * ===============
 * Reusable functions and utilities for all HomePulse Centers
 * Used by: Solar Center, Vehicle Center, Internet Center, Energy Center, Weather Center
 */

// ============================================================================
// TAB MANAGEMENT
// ============================================================================

/**
 * Setup tab switching for center pages
 * Attaches click handlers to all [data-center-tab] buttons
 */
function setupCenterTabs(onTabChange = null) {
  document.querySelectorAll("[data-center-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.centerTab;
      // Update active button
      document.querySelectorAll("[data-center-tab]").forEach((b) => {
        b.classList.toggle("active", b === button);
      });
      // Show/hide panels
      document.querySelectorAll("[data-center-panel]").forEach((panel) => {
        const active = panel.dataset.centerPanel === tab;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
      // Call optional callback for custom tab logic
      if (onTabChange) onTabChange(tab);
    });
  });
}

/**
 * Load data for specific tab on-demand
 * Centers override this with their own tab loading logic
 */
async function loadCenterTabData(tab, handlers = {}) {
  if (handlers[tab]) {
    await handlers[tab]();
  }
}

// ============================================================================
// FORMATTING & DISPLAY UTILITIES
// ============================================================================

/**
 * Safely set text content of an element by ID
 */
function setElementText(id, value, fallback = "-") {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}

/**
 * Parse number from string, handling currency symbols and commas
 */
function parseNumber(value) {
  if (value === null || value === undefined) return null;
  const number = Number(String(value).replace(/[$,%]/g, "").trim());
  return Number.isFinite(number) ? number : null;
}

/**
 * Format number with unit and decimal places
 * Example: formatMetric(12.456, "kWh", 2) => "12.46 kWh"
 */
function formatMetric(value, unit, digits = 2) {
  const number = parseNumber(value);
  if (number === null) return "-";
  return `${number.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} ${unit}`;
}

/**
 * Format as currency
 * Example: formatCurrency(12.5) => "$12.50"
 */
function formatCurrency(value) {
  const number = parseNumber(value);
  if (number === null) return "-";
  return `$${number.toFixed(2)}`;
}

/**
 * Format as percentage
 * Example: formatPercent(45.67) => "46%"
 */
function formatPercent(value) {
  const number = parseNumber(value);
  if (number === null) return "-";
  return `${number.toFixed(0)}%`;
}

/**
 * Format timestamp for display
 * Accepts ISO strings with space separator and converts to local time
 */
function formatTimestamp(value) {
  if (!value) return "-";
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleTimeString();
}

/**
 * Calculate trend indicator based on two values
 * Returns ↑ if up, ↓ if down, → if flat (within 5% threshold)
 */
function calculateTrend(current, previous) {
  if (current === null || previous === null || previous === 0) return "→";
  const percentChange = ((current - previous) / previous) * 100;
  if (percentChange > 5) return "↑";
  if (percentChange < -5) return "↓";
  return "→";
}

/**
 * Map status string to CSS class for color coding
 */
function mapStatusClass(status) {
  if (!status) return "";
  const normalized = String(status).toLowerCase();
  if (
    normalized.includes("online") ||
    normalized.includes("ok") ||
    normalized.includes("charging") ||
    normalized.includes("producing")
  ) {
    return "status-ok";
  }
  if (normalized.includes("offline") || normalized.includes("error") || normalized.includes("unavailable")) {
    return "status-error";
  }
  return "status-warning";
}

// ============================================================================
// CHART RENDERING
// ============================================================================

/**
 * Format chart x-axis label from a timestamp string, range-aware.
 * - 1d  → HH:MM  (intra-day data)
 * - 1w  → MM-DD  (hourly data across multiple days)
 * - 1m  → MM-DD  (daily data)
 * - 6m  → MM-DD  (weekly/daily data)
 * - 1y  → YYYY-MM (monthly data)
 */
function formatChartLabel(timestamp, range) {
  if (!timestamp) return "";
  const text = String(timestamp);
  if (text.length < 10) return text;
  switch (String(range || "1d").toLowerCase()) {
    case "1d":
      // Show HH:MM for intraday; fall back to MM-DD for midnight-only timestamps
      return text.length >= 16 && text.slice(11, 16) !== "00:00"
        ? text.slice(11, 16)
        : text.slice(5, 10);
    case "1w":
    case "1m":
    case "6m":
      // Show MM-DD — date gives context across multi-day views
      return text.slice(5, 10);
    case "1y":
      // Show YYYY-MM for yearly roll-ups
      return text.slice(0, 7);
    default:
      return text.length >= 16 && text.slice(11, 16) !== "00:00"
        ? text.slice(11, 16)
        : text.slice(5, 10);
  }
}

/**
 * Normalize data points for chart rendering
 * Expected input: Array of { label, value/kwh, timestamp, unit }
 * Pass range so x-axis labels are formatted correctly for the time window.
 */
function normalizeChartPoints(points, range) {
  if (!Array.isArray(points)) return [];
  return points
    .map((point) => ({
      label: point.label || formatChartLabel(point.timestamp, range),
      value: point.value ?? point.kwh,
      unit: point.unit || "kW",
    }))
    .filter((point) => parseNumber(point.value) !== null);
}

/**
 * Render chart using history_api.js LineChart
 * Requires window.HomePulseHistory to be available
 */
function renderCenterChart(chartElement, points, options = {}) {
  if (!chartElement || !window.HomePulseHistory?.renderLineChart) {
    if (chartElement) {
      chartElement.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "center-empty-state";
      empty.textContent = options.emptyMessage || "No data available.";
      chartElement.appendChild(empty);
    }
    return;
  }

  // Determine the active range: caller-supplied > persisted in DOM/sessionStorage > default 1d
  const range = options.range
    || window.HomePulseHistory.selectedRange(chartElement)
    || "1d";

  window.HomePulseHistory.renderLineChart(chartElement, normalizeChartPoints(points, range), {
    digits: options.digits || 2,
    yLabel: options.yLabel || "Value",
    unit: options.unit || "",
    xLabel: options.xLabel || "Time",
    range,
    emptyMessage: options.emptyMessage || "No data available for this range yet.",
    onRangeChange: options.onRangeChange || null,
  });
}

// ============================================================================
// TABLE RENDERING
// ============================================================================

/**
 * Populate data table from array of objects
 * Expects: tbody element ID, data array, column map
 * Column map example: { inverter_id: "Inverter ID", status: "Status", lifetime_kwh: "Lifetime kWh" }
 */
function populateDataTable(tbodyId, data, columnMap) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;

  if (!data || data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${Object.keys(columnMap).length}" class="table-empty">No data available</td></tr>`;
    return;
  }

  const columns = Object.keys(columnMap);
  tbody.innerHTML = data
    .map((row) => {
      return `<tr>${columns.map((col) => `<td>${row[col] !== undefined ? row[col] : "-"}</td>`).join("")}</tr>`;
    })
    .join("");
}

// ============================================================================
// FORM HELPERS
// ============================================================================

/**
 * Format time for display from HH:MM string
 */
function formatTime(timeString) {
  if (!timeString) return "-";
  return timeString;
}

/**
 * Calculate hours between two time strings
 * Input: "06:30" and "18:45"
 * Output: "12.25 hrs"
 */
function calculateHours(startTime, endTime) {
  if (!startTime || !endTime) return "-";
  const start = new Date(`2000-01-01 ${startTime}`);
  const end = new Date(`2000-01-01 ${endTime}`);
  const hours = (end - start) / 3600000;
  return `${hours.toFixed(2)} hrs`;
}

// ============================================================================
// EMPTY STATE RENDERING
// ============================================================================

/**
 * Render empty state card for tab with no data
 */
function renderEmptyState(containerId, message = "No data available.", subtext = "") {
  const container = document.getElementById(containerId);
  if (!container) return;

  const card = document.createElement("div");
  card.className = "center-empty-state";
  card.innerHTML = `<p><strong>${message}</strong>${subtext ? `<br><small>${subtext}</small>` : ""}</p>`;
  container.replaceChildren(card);
}

// ============================================================================
// LOADING STATE RENDERING
// ============================================================================

/**
 * Show loading spinner in container
 */
function showLoading(elementId) {
  const element = document.getElementById(elementId);
  if (!element) return;
  element.innerHTML = '<div class="center-loading"></div>';
}

/**
 * Clear loading spinner from container
 */
function clearLoading(elementId) {
  const element = document.getElementById(elementId);
  if (!element) return;
  const spinner = element.querySelector(".center-loading");
  if (spinner) spinner.remove();
}

// ============================================================================
// DATA CALCULATION HELPERS
// ============================================================================

/**
 * Calculate statistics from array of numeric points
 * Returns: { min, max, avg, total, count }
 */
function calculateStats(values) {
  const nums = (values || []).map((v) => parseNumber(v)).filter((v) => v !== null);
  if (nums.length === 0) return { min: 0, max: 0, avg: 0, total: 0, count: 0 };

  return {
    min: Math.min(...nums),
    max: Math.max(...nums),
    avg: nums.reduce((a, b) => a + b, 0) / nums.length,
    total: nums.reduce((a, b) => a + b, 0),
    count: nums.length,
  };
}

/**
 * Calculate percent change between two values
 */
function calculatePercentChange(current, previous) {
  if (!previous || previous === 0) return 0;
  return ((current - previous) / previous) * 100;
}

// ============================================================================
// FETCH HELPERS
// ============================================================================

/**
 * Safely fetch JSON from API with error handling
 */
async function fetchJSON(url, options = {}) {
  try {
    const response = await fetch(url, { cache: "no-store", ...options });
    if (!response.ok) return {};
    return await response.json();
  } catch (error) {
    console.error(`Fetch error: ${url}`, error);
    return {};
  }
}

/**
 * Fetch multiple URLs in parallel
 */
async function fetchMultiple(urls) {
  return Promise.all(urls.map((url) => fetchJSON(url)));
}

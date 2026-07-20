let weightProgressChart = null;
let weightProgressCompositionChart = null;
let weightProgressImportToken = null;

const WEIGHT_PROGRESS_RANGE_STORAGE_KEY = "homepulse.weight_progress.range";
const WEIGHT_PROGRESS_COMPOSITION_METRIC_STORAGE_KEY = "homepulse.weight_progress.composition.metric";

function parseWeightProgressTimestamp(value) {
  if (!value) return null;
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function normalizeWeightProgressRange(range) {
  const normalized = String(range || "current_journey").toLowerCase();
  const aliases = {
    "1w": "30d",
    "1m": "30d",
    "6m": "90d",
    current: "current_journey",
    journey: "current_journey",
  };
  const mapped = aliases[normalized] || normalized;
  return ["current_journey", "30d", "90d", "1y", "all"].includes(mapped) ? mapped : "current_journey";
}

function weightProgressRangeStart(range, journeyStartDate) {
  const now = new Date();
  const normalized = normalizeWeightProgressRange(range);
  if (normalized === "all") return null;
  if (normalized === "current_journey") {
    if (!journeyStartDate) return null;
    const parsed = new Date(`${journeyStartDate}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  const days = { "30d": 30, "90d": 90, "1y": 365 }[normalized];
  if (!days) return null;
  return new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
}

function formatWeightProgressLabel(timestamp, range) {
  const parsed = parseWeightProgressTimestamp(timestamp);
  if (!parsed) return "";
  const normalized = normalizeWeightProgressRange(range);
  if (normalized === "1y") {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(parsed);
  }
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(parsed);
}

function formatWeightProgressTooltip(timestamp) {
  const parsed = parseWeightProgressTimestamp(timestamp);
  if (!parsed) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function filteredWeightProgressPoints(points, range, journeyStartDate) {
  const start = weightProgressRangeStart(range, journeyStartDate);
  return (Array.isArray(points) ? points : []).filter((point) => {
    const parsed = parseWeightProgressTimestamp(point.timestamp);
    return parsed && (!start || parsed >= start);
  });
}

function formatWeightValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(1)} ${unit}`;
}

function setWeightProgressActiveRange(range) {
  const normalized = normalizeWeightProgressRange(range);
  sessionStorage.setItem(WEIGHT_PROGRESS_RANGE_STORAGE_KEY, normalized);
  document.querySelectorAll("[data-range]").forEach((item) => {
    item.classList.toggle("active", item.dataset.range === normalized);
  });
}

function getWeightProgressSelectedRange(container) {
  return normalizeWeightProgressRange(
    sessionStorage.getItem(WEIGHT_PROGRESS_RANGE_STORAGE_KEY)
      || container?.dataset.defaultRange
      || "current_journey"
  );
}

function getWeightProgressCompositionMetric(container) {
  const defaultMetric = container?.dataset.defaultMetric || "body_fat";
  const metric = sessionStorage.getItem(WEIGHT_PROGRESS_COMPOSITION_METRIC_STORAGE_KEY) || defaultMetric;
  return metric || "body_fat";
}

function setWeightProgressCompositionMetric(metric) {
  const normalized = String(metric || "body_fat").trim() || "body_fat";
  sessionStorage.setItem(WEIGHT_PROGRESS_COMPOSITION_METRIC_STORAGE_KEY, normalized);
  document.querySelectorAll("[data-composition-metric]").forEach((item) => {
    item.classList.toggle("active", item.dataset.compositionMetric === normalized);
  });
}

function formatCompositionDate(timestamp) {
  const parsed = parseWeightProgressTimestamp(timestamp);
  if (!parsed) return "--";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(parsed);
}

function compositionMetricConfig(data, metric) {
  const trend = data.composition_trends || {};
  return {
    key: metric,
    label: trend.metric_labels?.[metric] || metric,
    unit: trend.metric_units?.[metric] || data.display_unit || "lb",
    field: trend.metric_fields?.[metric] || metric,
    kind: trend.metric_kinds?.[metric] || "mass",
  };
}

function formatCompositionMetricValue(value, metricConfig) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  if (metricConfig.kind === "percent") {
    return `${Number(value).toFixed(1)}%`;
  }
  if (metricConfig.kind === "index") {
    return `${Number(value).toFixed(1)} Index`;
  }
  return formatWeightValue(Number(value), metricConfig.unit);
}

function formatCompositionMetricChange(value, metricConfig) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  if (Number(value) === 0) return "No change";
  const direction = Number(value) > 0 ? "Up" : "Down";
  const magnitude = Math.abs(Number(value)).toFixed(1);
  if (metricConfig.kind === "percent") {
    return `${direction} ${magnitude} percentage points`;
  }
  if (metricConfig.kind === "index") {
    return `${direction} ${magnitude} Index`;
  }
  return `${direction} ${magnitude} ${metricConfig.unit}`;
}

function compositionValueNote(point, metricConfig) {
  if (!point) return null;
  if (metricConfig.key === "fat_free_mass" && point.fat_free_mass_derived) {
    return "Derived from weight - fat mass";
  }
  return null;
}

function filteredCompositionMetricPoints(points, metricConfig, range, journeyStartDate) {
  const selectedPoints = filteredWeightProgressPoints(points, range, journeyStartDate);
  return selectedPoints.map((point) => ({
    timestamp: point.timestamp,
    value: point[metricConfig.field],
    derived: metricConfig.key === "fat_free_mass" ? Boolean(point.fat_free_mass_derived) : false,
  }));
}

function rollingAverageForPoints(points, index) {
  if (index < 1) return null;
  const endPoint = parseWeightProgressTimestamp(points[index].timestamp);
  if (!endPoint) return null;
  const windowStart = endPoint.getTime() - 7 * 24 * 60 * 60 * 1000;
  const values = [];
  for (let i = 0; i <= index; i += 1) {
    const point = points[i];
    const parsed = parseWeightProgressTimestamp(point.timestamp);
    if (!parsed || parsed.getTime() < windowStart) continue;
    if (point.value === null || point.value === undefined || Number.isNaN(Number(point.value))) continue;
    values.push(Number(point.value));
  }
  if (values.length < 2) return null;
  return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2));
}

function buildCompositionSummary(selectedPoints, allPoints, metricConfig, journeyStartDate) {
  const visiblePoints = selectedPoints.filter((point) => point.value !== null && point.value !== undefined && !Number.isNaN(Number(point.value)));
  const allMetricPoints = allPoints.filter((point) => point.value !== null && point.value !== undefined && !Number.isNaN(Number(point.value)));
  const journeyStart = journeyStartDate ? new Date(`${journeyStartDate}T00:00:00`) : null;
  const journeyPoints = journeyStart
    ? allMetricPoints.filter((point) => {
        const parsed = parseWeightProgressTimestamp(point.timestamp);
        return parsed && parsed >= journeyStart;
      })
    : allMetricPoints;
  const currentPoint = visiblePoints[visiblePoints.length - 1] || null;
  const earliestPoint = visiblePoints[0] || null;
  const latestPoint = visiblePoints[visiblePoints.length - 1] || null;
  const journeyPoint = journeyPoints[0] || visiblePoints[0] || null;
  const currentValue = currentPoint ? Number(currentPoint.value) : null;
  const journeyValue = journeyPoint ? Number(journeyPoint.value) : null;
  const change = currentValue === null || journeyValue === null ? null : Number((currentValue - journeyValue).toFixed(1));
  const summaryCards = [
    {
      key: "current_value",
      label: "Current Value",
      value: formatCompositionMetricValue(currentValue, metricConfig),
      note: compositionValueNote(currentPoint, metricConfig),
    },
    {
      key: "journey_starting_value",
      label: "Journey Starting Value",
      value: formatCompositionMetricValue(journeyValue, metricConfig),
      note: compositionValueNote(journeyPoint, metricConfig),
    },
    {
      key: "change_since_journey_start",
      label: "Change Since Journey Start",
      value: formatCompositionMetricChange(change, metricConfig),
    },
    {
      key: "earliest_available_date",
      label: "Earliest Available Date",
      value: formatCompositionDate(earliestPoint?.timestamp),
    },
    {
      key: "latest_measurement_date",
      label: "Latest Measurement Date",
      value: formatCompositionDate(latestPoint?.timestamp),
    },
  ];

  let summaryMessage = "The selected body-composition trend uses actual readings and a seven-day trend line.";
  if (metricConfig.key === "visceral_fat" && visiblePoints.length <= 1) {
    summaryMessage = "Visceral-fat history will appear as additional measurements are collected.";
  } else if (visiblePoints.length <= 1) {
    summaryMessage = "Only one reading is available so far. Additional history will appear as measurements are collected.";
  }

  return {
    metric: metricConfig.key,
    metric_label: metricConfig.label,
    metric_unit: metricConfig.unit,
    current_value: currentValue,
    journey_value: journeyValue,
    change,
    summary_cards: summaryCards,
    summary_message: summaryMessage,
    earliest_date: formatCompositionDate(earliestPoint?.timestamp),
    latest_date: formatCompositionDate(latestPoint?.timestamp),
    trend_points: visiblePoints.length,
  };
}

function renderCompositionSummary(summary) {
  const grid = document.getElementById("weight-progress-composition-summary");
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll(".summary-card"));
  summary.summary_cards.forEach((card, index) => {
    const element = cards[index];
    if (!element) return;
    const labelEl = element.querySelector("span");
    const valueEl = element.querySelector("strong");
    let noteEl = element.querySelector(".small");
    if (labelEl) labelEl.textContent = card.label;
    if (valueEl) valueEl.textContent = card.value || "--";
    if (card.note) {
      if (!noteEl) {
        noteEl = document.createElement("div");
        noteEl.className = "small";
        element.appendChild(noteEl);
      }
      noteEl.textContent = card.note;
      noteEl.hidden = false;
    } else if (noteEl) {
      noteEl.remove();
    }
  });

  const note = document.getElementById("weight-progress-composition-chart-note");
  if (note) {
    note.textContent = summary.summary_message || "The selected body-composition trend uses actual readings and a seven-day trend line.";
  }
}

function renderWeightProgressCompositionChart() {
  const data = window.WeightProgressData || {};
  const container = document.getElementById("weight-progress-composition-chart-box");
  let canvas = document.getElementById("weight-progress-composition-chart");
  const note = document.getElementById("weight-progress-composition-chart-note");
  if (!container || !note) return;

  const range = getWeightProgressSelectedRange(container);
  const metric = getWeightProgressCompositionMetric(container);
  setWeightProgressActiveRange(range);
  setWeightProgressCompositionMetric(metric);

  const metricConfig = compositionMetricConfig(data, metric);
  const journeyStartDate = container.dataset.journeyStartDate || data.composition_trends?.journey_start_date || null;
  const sourcePoints = data.composition_trends?.all_points || data.composition_trends?.points || [];
  const selectedPoints = filteredCompositionMetricPoints(sourcePoints, metricConfig, range, journeyStartDate);
  const summary = buildCompositionSummary(selectedPoints, sourcePoints, metricConfig, journeyStartDate);
  renderCompositionSummary(summary);

  if (!canvas && sourcePoints.length > 0) {
    canvas = document.createElement("canvas");
    canvas.id = "weight-progress-composition-chart";
    container.replaceChildren(canvas);
  }
  if (!canvas) return;

  const visiblePoints = selectedPoints.filter((point) => point.value !== null && point.value !== undefined && !Number.isNaN(Number(point.value)));
  if (!visiblePoints.length) {
    weightProgressCompositionChart?.destroy();
    weightProgressCompositionChart = null;
    const empty = document.createElement("div");
    empty.className = "chart-empty-state";
    empty.textContent = sourcePoints.length
      ? "No body composition readings are available for this range."
      : "No body composition history has been collected yet. The first successful measurement will appear here.";
    container.replaceChildren(empty);
    note.textContent = summary.summary_message;
    return;
  }

  const labels = selectedPoints.map((point) => formatWeightProgressLabel(point.timestamp, range));
  const tooltipLabels = selectedPoints.map((point) => formatWeightProgressTooltip(point.timestamp));
  const actualValues = selectedPoints.map((point) => (point.value === null || point.value === undefined ? null : Number(point.value)));
  const trendValues = selectedPoints.map((point, index) => {
    if (point.value === null || point.value === undefined || Number.isNaN(Number(point.value))) return null;
    const average = rollingAverageForPoints(selectedPoints, index);
    return average;
  });
  const unit = metricConfig.unit === "%" || metricConfig.unit === "Index" ? metricConfig.unit : (data.display_unit || "lb");
  const context = canvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, 0, canvas.clientHeight || 320);
  gradient.addColorStop(0, "rgba(15, 118, 110, 0.3)");
  gradient.addColorStop(1, "rgba(15, 118, 110, 0.05)");

  if (weightProgressCompositionChart) {
    weightProgressCompositionChart.data.labels = labels;
    weightProgressCompositionChart.data.datasets[0].data = actualValues;
    weightProgressCompositionChart.data.datasets[1].data = trendValues;
    weightProgressCompositionChart.options.plugins.tooltip.callbacks.title = (items) => tooltipLabels[items[0].dataIndex] || "";
    weightProgressCompositionChart.options.scales.y.title.text = unit;
    weightProgressCompositionChart.options.plugins.legend.labels.filter = (legendItem) => legendItem.text !== "7-day trend" || visiblePoints.length > 1;
    weightProgressCompositionChart.update("active");
  } else {
    weightProgressCompositionChart = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: metricConfig.label,
            data: actualValues,
            borderColor: "#0f766e",
            backgroundColor: gradient,
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: "7-day trend",
            data: trendValues,
            borderColor: "#7c3aed",
            borderDash: [6, 5],
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.35,
            spanGaps: true,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: {
              color: "#344258",
              boxWidth: 10,
              usePointStyle: true,
            },
          },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.94)",
            borderColor: "rgba(255, 255, 255, 0.16)",
            borderWidth: 1,
            padding: 11,
            callbacks: {
              title(items) {
                return tooltipLabels[items[0].dataIndex] || "";
              },
              label(context) {
                const label = context.dataset.label || "";
                const value = context.parsed.y;
                return `${label}: ${formatCompositionMetricValue(value, metricConfig)}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: "#6b7688", maxRotation: 0, autoSkipPadding: 18 },
          },
          y: {
            beginAtZero: false,
            border: { display: false },
            grid: { color: "rgba(107, 118, 136, 0.14)" },
            ticks: { color: "#6b7688" },
            title: { display: true, text: unit, color: "#6b7688" },
          },
        },
      },
    });
  }

  note.textContent = summary.summary_message;
}

function renderWeightProgressChart() {
  const data = window.WeightProgressData || {};
  const container = document.getElementById("weight-progress-chart-box");
  let canvas = document.getElementById("weight-progress-chart");
  const note = document.getElementById("weight-progress-chart-note");
  if (!container || !note) return;

  const range = getWeightProgressSelectedRange(container);
  setWeightProgressActiveRange(range);

  if (!canvas && (data.chart?.measurement_count || 0) > 0) {
    canvas = document.createElement("canvas");
    canvas.id = "weight-progress-chart";
    container.replaceChildren(canvas);
  }
  if (!canvas) return;

  const journeyStartDate = container.dataset.journeyStartDate || data.chart?.journey_start_date || null;
  const sourcePoints = data.chart?.all_points || data.chart?.points || [];
  const points = filteredWeightProgressPoints(sourcePoints, range, journeyStartDate);
  if (!points.length) {
    weightProgressChart?.destroy();
    weightProgressChart = null;
    const empty = document.createElement("div");
    empty.className = "chart-empty-state";
    empty.textContent = data.chart?.measurement_count
      ? "No measurements are available for this range."
      : "No weight history stored yet. The first successful weigh-in will appear here.";
    container.replaceChildren(empty);
    note.textContent = data.chart_message || "No weight history has been collected yet.";
    return;
  }

  const labels = points.map((point) => formatWeightProgressLabel(point.timestamp, range));
  const tooltipLabels = points.map((point) => formatWeightProgressTooltip(point.timestamp));
  const weightValues = points.map((point) => point.weight);
  const rollingValues = points.map((point) => point.rolling_average);
  const goalValues = points.map((point) => point.goal_weight);
  const unit = data.chart?.display_unit || data.display_unit || "lb";
  const context = canvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, 0, canvas.clientHeight || 320);
  gradient.addColorStop(0, "rgba(37, 99, 168, 0.28)");
  gradient.addColorStop(1, "rgba(37, 99, 168, 0.02)");

  if (weightProgressChart) {
    weightProgressChart.data.labels = labels;
    weightProgressChart.data.datasets[0].data = weightValues;
    weightProgressChart.data.datasets[1].data = rollingValues;
    weightProgressChart.data.datasets[2].data = goalValues;
    weightProgressChart.options.plugins.tooltip.callbacks.title = (items) => tooltipLabels[items[0].dataIndex] || "";
    weightProgressChart.options.scales.y.title.text = unit;
    weightProgressChart.update("active");
  } else {
    weightProgressChart = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Weight",
            data: weightValues,
            borderColor: "#2563a8",
            backgroundColor: gradient,
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: "7-day average",
            data: rollingValues,
            borderColor: "#16803c",
            borderDash: [6, 5],
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.35,
            spanGaps: true,
            fill: false,
          },
          {
            label: "Goal weight",
            data: goalValues,
            borderColor: "#b7791f",
            borderDash: [4, 4],
            borderWidth: 2,
            pointRadius: 0,
            tension: 0,
            spanGaps: true,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: {
              color: "#344258",
              boxWidth: 10,
              usePointStyle: true,
            },
          },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.94)",
            borderColor: "rgba(255, 255, 255, 0.16)",
            borderWidth: 1,
            padding: 11,
            callbacks: {
              title(items) {
                return tooltipLabels[items[0].dataIndex] || "";
              },
              label(context) {
                const label = context.dataset.label || "";
                const value = context.parsed.y;
                return `${label}: ${formatWeightValue(value, unit)}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: "#6b7688", maxRotation: 0, autoSkipPadding: 18 },
          },
          y: {
            beginAtZero: false,
            border: { display: false },
            grid: { color: "rgba(107, 118, 136, 0.14)" },
            ticks: { color: "#6b7688" },
            title: { display: true, text: unit, color: "#6b7688" },
          },
        },
      },
    });
  }

  if (points.length === 1) {
    note.textContent = "Only one reading is available so far. Additional history will appear as measurements are collected.";
  } else {
    note.textContent = data.chart_message || "Daily weight and body-composition readings can vary. The trend is generally more useful than a single reading.";
  }
}

function renderImportPreview(preview) {
  const grid = document.getElementById("weight-progress-import-preview-grid");
  const errors = document.getElementById("weight-progress-import-errors");
  if (!grid || !errors) return;

  const rows = [
    ["Filename", preview.filename],
    ["Worksheet", preview.worksheet],
    ["Rows Found", preview.rows_found],
    ["Valid Measurements", preview.valid_measurements],
    ["Invalid Rows", preview.invalid_rows],
    ["Exact Duplicates", preview.exact_duplicates],
    ["Likely Overlaps", preview.likely_overlaps],
    ["Before Journey Start", preview.measurements_before_journey_start],
    ["On/After Journey Start", preview.measurements_on_or_after_journey_start],
    ["Earliest Measurement", preview.earliest_measurement],
    ["Latest Measurement", preview.latest_measurement],
    ["Proposed Journey Date", preview.proposed_journey_date],
    ["Proposed Baseline", preview.proposed_journey_baseline],
    ["Proposed Starting Weight", preview.proposed_starting_weight],
    ["Journey Source", preview.journey_start_source],
  ];

  grid.replaceChildren(...rows.map(([label, value]) => {
    const card = document.createElement("article");
    card.className = "summary-card";
    const labelEl = document.createElement("span");
    const valueEl = document.createElement("strong");
    labelEl.textContent = label;
    valueEl.textContent = value === null || value === undefined || value === "" ? "--" : String(value);
    card.append(labelEl, valueEl);
    return card;
  }));
  grid.hidden = false;

  const errorRows = Array.isArray(preview.errors) ? preview.errors : [];
  if (errorRows.length) {
    errors.hidden = false;
    errors.innerHTML = errorRows.map((entry) => {
      const messages = Array.isArray(entry.messages) ? entry.messages.join(" ") : String(entry.message || "");
      return `<div>Row ${entry.row}: ${messages}</div>`;
    }).join("");
  } else {
    errors.hidden = true;
    errors.textContent = "";
  }
}

function setImportStatus(message, kind = "info") {
  const status = document.getElementById("weight-progress-import-status");
  if (!status) return;
  status.hidden = false;
  status.className = `settings-message ${kind}`;
  status.textContent = message;
}

function setImportButtonsEnabled({ preview = false, confirm = false, cancel = false } = {}) {
  const previewButton = document.getElementById("weight-progress-import-preview");
  const confirmButton = document.getElementById("weight-progress-import-confirm");
  const cancelButton = document.getElementById("weight-progress-import-cancel");
  if (previewButton) previewButton.disabled = !preview;
  if (confirmButton) confirmButton.disabled = !confirm;
  if (cancelButton) cancelButton.disabled = !cancel;
}

function setupWeightProgressImport() {
  const fileInput = document.getElementById("weight-progress-import-file");
  const previewButton = document.getElementById("weight-progress-import-preview");
  const confirmButton = document.getElementById("weight-progress-import-confirm");
  const cancelButton = document.getElementById("weight-progress-import-cancel");
  if (!fileInput || !previewButton || !confirmButton || !cancelButton) return;

  const resetPreviewState = (clearFile = false) => {
    weightProgressImportToken = null;
    setImportButtonsEnabled({ preview: !!fileInput.files.length, confirm: false, cancel: false });
    if (clearFile) {
      fileInput.value = "";
    }
    const grid = document.getElementById("weight-progress-import-preview-grid");
    const errors = document.getElementById("weight-progress-import-errors");
    const status = document.getElementById("weight-progress-import-status");
    if (grid) {
      grid.hidden = true;
      grid.replaceChildren();
    }
    if (errors) {
      errors.hidden = true;
      errors.textContent = "";
    }
    if (status) {
      status.hidden = true;
      status.textContent = "";
    }
  };

  fileInput.addEventListener("change", () => {
    resetPreviewState(false);
    setImportButtonsEnabled({ preview: !!fileInput.files.length, confirm: false, cancel: false });
  });

  previewButton.addEventListener("click", async () => {
    const file = fileInput.files?.[0];
    if (!file) {
      setImportStatus("Choose an .xlsx workbook before previewing.", "error");
      return;
    }
    setImportButtonsEnabled({ preview: false, confirm: false, cancel: false });
    setImportStatus("Previewing workbook...", "info");
    try {
      const formData = new FormData();
      formData.append("workbook", file, file.name);
      const response = await fetch("/api/weight-progress/import/preview", {
        method: "POST",
        body: formData,
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Preview failed.");
      }
      weightProgressImportToken = payload.preview.preview_token;
      renderImportPreview(payload.preview);
      setImportStatus(`Preview ready for ${payload.preview.filename}. No rows were written yet.`, "success");
      setImportButtonsEnabled({ preview: true, confirm: true, cancel: true });
    } catch (error) {
      setImportStatus(error.message || "Preview failed.", "error");
      setImportButtonsEnabled({ preview: !!fileInput.files.length, confirm: false, cancel: false });
    }
  });

  confirmButton.addEventListener("click", async () => {
    if (!weightProgressImportToken) {
      setImportStatus("Preview the workbook before importing.", "error");
      return;
    }
    setImportButtonsEnabled({ preview: false, confirm: false, cancel: false });
    setImportStatus("Importing workbook...", "info");
    try {
      const response = await fetch("/api/weight-progress/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preview_token: weightProgressImportToken }),
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Import failed.");
      }
      setImportStatus(
        `Imported ${payload.inserted} row(s). Skipped ${payload.exact_duplicates} exact duplicate(s), ${payload.likely_overlaps} likely overlap(s), and ${payload.invalid_rows} invalid row(s).`,
        "success"
      );
      if (payload.preview) {
        renderImportPreview(payload.preview);
      }
      setTimeout(() => {
        window.location.reload();
      }, 900);
    } catch (error) {
      setImportStatus(error.message || "Import failed.", "error");
      setImportButtonsEnabled({ preview: !!fileInput.files.length, confirm: !!weightProgressImportToken, cancel: !!weightProgressImportToken });
    }
  });

  cancelButton.addEventListener("click", async () => {
    if (!weightProgressImportToken) {
      resetPreviewState(true);
      return;
    }
    try {
      await fetch("/api/weight-progress/import/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preview_token: weightProgressImportToken }),
        cache: "no-store",
      });
    } catch (error) {
      // Ignore cancel errors and clear local state regardless.
    } finally {
      resetPreviewState(true);
      setImportStatus("Import canceled.", "info");
    }
  });

  resetPreviewState(false);
}

function setupWeightProgressComposition() {
  const selectors = document.querySelectorAll("[data-composition-metric]");
  if (!selectors.length) return;
  selectors.forEach((item) => {
    item.addEventListener("click", () => {
      setWeightProgressCompositionMetric(item.dataset.compositionMetric);
      renderWeightProgressCompositionChart();
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("weight-progress-chart-box");
  const compositionContainer = document.getElementById("weight-progress-composition-chart-box");

  setupWeightProgressImport();
  if (!container && !compositionContainer) return;

  document.querySelectorAll("[data-range]").forEach((item) => {
    item.addEventListener("click", () => {
      const range = item.dataset.range;
      setWeightProgressActiveRange(range);
      renderWeightProgressChart();
      renderWeightProgressCompositionChart();
    });
  });

  setupWeightProgressComposition();
  renderWeightProgressChart();
  renderWeightProgressCompositionChart();
});

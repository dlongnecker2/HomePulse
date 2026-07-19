let weightProgressChart = null;

function parseWeightProgressTimestamp(value) {
  if (!value) return null;
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function weightProgressRangeStart(range) {
  const now = new Date();
  const normalized = String(range || "1m").toLowerCase();
  const days = { "1w": 7, "1m": 30, "6m": 180, "1y": 365 }[normalized] || 30;
  return new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
}

function formatWeightValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(1)} ${unit}`;
}

function setActiveRange(container, range) {
  if (!container) return;
  const normalized = window.HomePulseHistory?.normalizeRange?.(range) || range || "1m";
  window.HomePulseHistory?.setSelectedRange?.(container, normalized);
  document.querySelectorAll("[data-range]").forEach((item) => {
    const active = item.dataset.range === normalized;
    item.classList.toggle("active", active);
  });
}

function filteredPoints(points, range) {
  const start = weightProgressRangeStart(range);
  return (Array.isArray(points) ? points : []).filter((point) => {
    const parsed = parseWeightProgressTimestamp(point.timestamp);
    return parsed && parsed >= start;
  });
}

function renderWeightProgressChart() {
  const data = window.WeightProgressData || {};
  const container = document.getElementById("weight-progress-chart-box");
  const canvas = document.getElementById("weight-progress-chart");
  const note = document.getElementById("weight-progress-chart-note");
  if (!container || !canvas || !note) return;

  const range = window.HomePulseHistory?.selectedRange?.(container) || data.default_range || "1m";
  setActiveRange(container, range);

  const points = filteredPoints(data.chart?.points || [], range);
  if (!points.length) {
    weightProgressChart?.destroy();
    weightProgressChart = null;
    const empty = document.createElement("div");
    empty.className = "chart-empty-state";
    empty.textContent = "No weight history stored yet. The first successful weigh-in will appear here.";
    container.replaceChildren(empty);
    note.textContent = data.chart_message || "No weight history has been collected yet.";
    return;
  }

  const labels = points.map((point) => window.HomePulseHistory?.formatHistoryLabel?.(point.timestamp, range) || point.timestamp);
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

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("weight-progress-chart-box");
  if (!container) return;
  document.querySelectorAll("[data-range]").forEach((item) => {
    item.addEventListener("click", () => {
      const range = item.dataset.range;
      setActiveRange(container, range);
      renderWeightProgressChart();
    });
  });
  renderWeightProgressChart();
});

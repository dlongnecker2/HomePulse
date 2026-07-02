let latencyChart = null;

function numericValues(values) {
  return values
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function average(values) {
  const numbers = numericValues(values);
  if (!numbers.length) return null;
  return numbers.reduce((total, value) => total + value, 0) / numbers.length;
}

const averageLinePlugin = {
  id: "averageLatencyLine",
  afterDatasetsDraw(chart) {
    const avg = chart.options.plugins.averageLatencyLine?.value;
    if (!Number.isFinite(avg)) return;

    const { ctx, chartArea, scales } = chart;
    const y = scales.y.getPixelForValue(avg);
    if (y < chartArea.top || y > chartArea.bottom) return;

    ctx.save();
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = "rgba(37, 99, 168, 0.38)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(chartArea.left, y);
    ctx.lineTo(chartArea.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#6b7688";
    ctx.font = "600 11px Inter, Segoe UI, Arial, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(`Avg ${Math.round(avg)} ms`, chartArea.right - 6, y - 7);
    ctx.restore();
  }
};

if (window.Chart) {
  Chart.register(averageLinePlugin);
}

async function loadLatencyChart() {
  const canvas = document.getElementById("latencyChart");
  if (!canvas) {
    return;
  }

  const data = await loadLatencyHistoryData(canvas);
  const empty = ensureLatencyEmptyState(canvas);
  if (!data.values.length) {
    canvas.hidden = true;
    empty.hidden = false;
    empty.textContent = "No data available for this range yet.";
    return;
  }
  canvas.hidden = false;
  empty.hidden = true;
  const averageLatency = average(data.values);
  const xAxisTitle = { "1d": "Time", "1w": "Day", "1m": "Date", "6m": "Month / Date", "1y": "Month" }[data.range || "1d"] || "Time";

  if (latencyChart) {
    latencyChart.data.labels = data.labels;
    latencyChart.data.datasets[0].data = data.values;
    latencyChart.options.plugins.averageLatencyLine.value = averageLatency;
    latencyChart.options.scales.x.title.text = xAxisTitle;
    latencyChart.update("active");
    return;
  }

  const context = canvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, 0, canvas.clientHeight || 320);
  gradient.addColorStop(0, "rgba(47, 95, 159, 0.22)");
  gradient.addColorStop(1, "rgba(47, 95, 159, 0.02)");

  latencyChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Latency (ms)",
          data: data.values,
          borderColor: "#2563a8",
          backgroundColor: gradient,
          borderWidth: 2.75,
          fill: true,
          tension: 0.35,
          pointRadius(context) {
            return context.dataIndex === context.dataset.data.length - 1 ? 5 : 0;
          },
          pointHoverRadius: 5,
          pointHoverBorderWidth: 2,
          pointHoverBackgroundColor: "#ffffff",
          pointHoverBorderColor: "#2563a8",
          pointBackgroundColor: "#ffffff",
          pointBorderColor: "#2563a8",
          pointBorderWidth: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 420,
        easing: "easeOutQuart"
      },
      interaction: {
        mode: "index",
        intersect: false
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          enabled: true,
          backgroundColor: "rgba(15, 23, 42, 0.94)",
          borderColor: "rgba(255, 255, 255, 0.16)",
          borderWidth: 1,
          padding: 11,
          titleColor: "#ffffff",
          bodyColor: "#e7edf7",
          displayColors: false,
          callbacks: {
            label(context) {
              return `Latency: ${context.parsed.y} ms`;
            }
          }
        },
        averageLatencyLine: {
          value: averageLatency
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          border: { display: false },
          grid: { color: "rgba(107, 118, 136, 0.14)" },
          ticks: {
            color: "#6b7688",
            padding: 8
          },
          title: {
            display: true,
            text: "Milliseconds",
            color: "#6b7688",
            font: { weight: "600" }
          }
        },
        x: {
          border: { display: false },
          grid: { display: false },
          ticks: {
            color: "#6b7688",
            maxRotation: 0,
            autoSkipPadding: 18
          },
          title: {
            display: true,
            text: xAxisTitle,
            color: "#6b7688",
            font: { weight: "600" }
          }
        }
      }
    }
  });
}

async function loadLatencyHistoryData(canvas) {
  const container = canvas.parentElement;
  const range = window.HomePulseHistory?.selectedRange(container) || "1d";
  ensureLatencyRangeControls(container, range);
  if (window.HomePulseHistory?.fetchMetrics) {
    try {
      const payload = await window.HomePulseHistory.fetchMetrics("internet", "latency_ms", { range });
      const points = Array.isArray(payload.points) ? payload.points : [];
      return {
        labels: points.map((point) => latencyLabel(point.timestamp, range)),
        values: points.map((point) => point.value).filter((value) => Number.isFinite(Number(value))),
        range,
      };
    } catch (error) {
      return { labels: [], values: [], range };
    }
  }
  const response = await fetch("/api/charts/latency");
  return response.json();
}

function ensureLatencyRangeControls(container, activeRange) {
  if (!container || container.querySelector(".chart-time-range")) return;
  const controls = document.createElement("div");
  controls.className = "chart-time-range";
  controls.setAttribute("role", "group");
  controls.setAttribute("aria-label", "Latency chart time range");
  [["1d", "1D"], ["1w", "1W"], ["1m", "1M"], ["6m", "6M"], ["1y", "1Y"]].forEach(([range, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = range === activeRange ? "active" : "";
    button.setAttribute("aria-pressed", String(range === activeRange));
    button.addEventListener("click", () => {
      window.HomePulseHistory?.setSelectedRange(container, range);
      controls.querySelectorAll("button").forEach((item) => {
        item.classList.toggle("active", item === button);
        item.setAttribute("aria-pressed", String(item === button));
      });
      loadLatencyChart();
    });
    controls.appendChild(button);
  });
  container.prepend(controls);
}

function ensureLatencyEmptyState(canvas) {
  let empty = canvas.parentElement?.querySelector(".chart-empty-state");
  if (!empty) {
    empty = document.createElement("div");
    empty.className = "chart-empty-state";
    canvas.parentElement?.appendChild(empty);
  }
  return empty;
}

function latencyLabel(timestamp, range) {
  if (window.HomePulseHistory?.formatHistoryLabel) {
    return window.HomePulseHistory.formatHistoryLabel(timestamp, range || "1d");
  }
  // Fallback
  if (!timestamp) return "";
  const text = String(timestamp);
  if (text.length >= 16 && text.slice(11, 16) !== "00:00") return text.slice(11, 16);
  return text.length >= 10 ? text.slice(5, 10) : text;
}

document.addEventListener("DOMContentLoaded", loadLatencyChart);

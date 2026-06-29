function chartGradient(canvas, color) {
  const context = canvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, 0, canvas.clientHeight || 260);
  gradient.addColorStop(0, color.replace("1)", "0.20)"));
  gradient.addColorStop(1, color.replace("1)", "0.02)"));
  return gradient;
}

function baseOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        labels: {
          color: "#344258",
          boxWidth: 10,
          usePointStyle: true
        }
      },
      tooltip: {
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderColor: "rgba(255, 255, 255, 0.16)",
        borderWidth: 1,
        displayColors: true,
        padding: 11
      }
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: "#6b7688", maxRotation: 0, autoSkipPadding: 18 }
      },
      y: {
        beginAtZero: true,
        border: { display: false },
        grid: { color: "rgba(107, 118, 136, 0.14)" },
        ticks: { color: "#6b7688" }
      }
    },
    ...extra
  };
}

function renderSpeedHistory(data) {
  const canvas = document.getElementById("speedHistoryChart");
  if (!canvas) return;

  new Chart(canvas, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Download Mbps",
          data: data.download,
          borderColor: "#2563a8",
          backgroundColor: chartGradient(canvas, "rgba(37, 99, 168, 1)"),
          yAxisID: "speed",
          fill: true,
          tension: 0.35,
          borderWidth: 2.5,
          pointRadius: 2
        },
        {
          label: "Upload Mbps",
          data: data.upload,
          borderColor: "#16803c",
          backgroundColor: "rgba(22, 128, 60, 0.08)",
          yAxisID: "speed",
          fill: false,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 2
        },
        {
          label: "Latency ms",
          data: data.latency,
          borderColor: "#b7791f",
          backgroundColor: "rgba(183, 121, 31, 0.08)",
          yAxisID: "latency",
          fill: false,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 2
        }
      ]
    },
    options: baseOptions({
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#6b7688", maxRotation: 0, autoSkipPadding: 18 }
        },
        speed: {
          type: "linear",
          position: "left",
          beginAtZero: true,
          border: { display: false },
          grid: { color: "rgba(107, 118, 136, 0.14)" },
          ticks: { color: "#6b7688" },
          title: { display: true, text: "Mbps", color: "#6b7688" }
        },
        latency: {
          type: "linear",
          position: "right",
          beginAtZero: true,
          border: { display: false },
          grid: { drawOnChartArea: false },
          ticks: { color: "#6b7688" },
          title: { display: true, text: "ms", color: "#6b7688" }
        }
      }
    })
  });
}

function renderSingleLineChart(id, labels, values, label, color, yTitle) {
  const canvas = document.getElementById(id);
  if (!canvas) return;

  new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label,
          data: values,
          borderColor: color,
          backgroundColor: chartGradient(canvas, color.replace("#2563a8", "rgba(37, 99, 168, 1)").replace("#b7791f", "rgba(183, 121, 31, 1)")),
          fill: true,
          tension: 0.35,
          borderWidth: 2.25,
          pointRadius: 0,
          pointHoverRadius: 4
        }
      ]
    },
    options: baseOptions({
      plugins: {
        ...baseOptions().plugins,
        legend: { display: false }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#6b7688", maxRotation: 0, autoSkipPadding: 18 }
        },
        y: {
          beginAtZero: true,
          border: { display: false },
          grid: { color: "rgba(107, 118, 136, 0.14)" },
          ticks: { color: "#6b7688" },
          title: { display: true, text: yTitle, color: "#6b7688" }
        }
      }
    })
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const data = window.HomePulseHistory || {};
  renderSpeedHistory(data.speed || { labels: [], download: [], upload: [], latency: [] });
  renderSingleLineChart(
    "qualityHistoryChart",
    data.quality?.labels || [],
    data.quality?.values || [],
    "Internet Quality",
    "#2563a8",
    "Score"
  );
  renderSingleLineChart(
    "latencyHistoryChart",
    data.latency?.labels || [],
    data.latency?.values || [],
    "Latency",
    "#b7791f",
    "ms"
  );
});

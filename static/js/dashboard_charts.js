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

  const response = await fetch("/api/charts/latency");
  const data = await response.json();
  const averageLatency = average(data.values);

  if (latencyChart) {
    latencyChart.data.labels = data.labels;
    latencyChart.data.datasets[0].data = data.values;
    latencyChart.options.plugins.averageLatencyLine.value = averageLatency;
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
            text: "Time",
            color: "#6b7688",
            font: { weight: "600" }
          }
        }
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", loadLatencyChart);

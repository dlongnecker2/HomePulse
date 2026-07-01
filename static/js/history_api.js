window.HomePulseHistory = (() => {
  async function fetchMetrics(moduleName, metricName, hours = 24) {
    const params = new URLSearchParams({
      module: moduleName,
      metric: metricName,
      hours: String(hours),
    });
    const response = await fetch(`/api/history/metrics?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`History request failed: ${response.status}`);
    }
    return response.json();
  }

  async function fetchLatest() {
    const response = await fetch("/api/history/latest", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`History latest request failed: ${response.status}`);
    }
    return response.json();
  }

  function renderBarChart(element, points, options = {}) {
    if (!element) return;
    element.replaceChildren();
    if (!Array.isArray(points) || points.length === 0) {
      const empty = document.createElement("div");
      empty.className = "chart-empty-state";
      empty.textContent = options.emptyMessage || "Collecting data...";
      element.appendChild(empty);
      return;
    }

    const values = points.map((point) => numberValue(point.value ?? point.kwh)).filter((value) => value !== null);
    const max = Math.max(...values, 1);
    points.forEach((point) => {
      const value = numberValue(point.value ?? point.kwh) || 0;
      const item = document.createElement("div");
      item.className = "mock-bar";
      item.style.setProperty("--bar-height", `${Math.max(4, (value / max) * 100)}%`);
      item.innerHTML = `<span>${formatNumber(value, options.digits ?? 2)}</span><strong>${point.label || ""}</strong>`;
      element.appendChild(item);
    });
  }

  function renderComparisonChart(element, series, options = {}) {
    if (!element) return;
    element.replaceChildren();
    const first = Array.isArray(series?.first) ? series.first : [];
    const second = Array.isArray(series?.second) ? series.second : [];
    const length = Math.min(first.length, second.length);
    if (length < (options.minimumPoints || 2)) {
      const empty = document.createElement("div");
      empty.className = "chart-empty-state";
      empty.textContent = options.emptyMessage || "Collecting data...";
      element.appendChild(empty);
      return;
    }

    const firstValues = first.slice(-length).map((point) => numberValue(point.value));
    const secondValues = second.slice(-length).map((point) => numberValue(point.value));
    const max = Math.max(...firstValues, ...secondValues, 1);
    const width = 640;
    const height = 220;
    const padding = 18;
    const chartWidth = width - padding * 2;
    const chartHeight = height - padding * 2;
    const pointsFor = (values) => values.map((value, index) => {
      const x = padding + (length === 1 ? 0 : (index / (length - 1)) * chartWidth);
      const y = height - padding - ((value || 0) / max) * chartHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.classList.add("comparison-svg");
    svg.innerHTML = `
      <polyline class="comparison-grid" points="${padding},${height - padding} ${width - padding},${height - padding}"></polyline>
      <polyline class="comparison-line solar" points="${pointsFor(firstValues)}"></polyline>
      <polyline class="comparison-line ev" points="${pointsFor(secondValues)}"></polyline>
    `;
    const legend = document.createElement("div");
    legend.className = "comparison-legend";
    legend.innerHTML = `<span class="solar">${options.firstLabel || "Solar"}</span><span class="ev">${options.secondLabel || "EV Charging"}</span>`;
    element.append(svg, legend);
  }

  function numberValue(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(String(value).replace("$", "").replace(",", "").trim());
    return Number.isFinite(number) ? number : null;
  }

  function formatNumber(value, digits) {
    const number = numberValue(value);
    if (number === null) return "-";
    return number.toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  return {
    fetchMetrics,
    fetchLatest,
    renderBarChart,
    renderComparisonChart,
  };
})();

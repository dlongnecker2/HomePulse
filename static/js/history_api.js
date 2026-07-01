window.HomePulseHistory = (() => {
  const RANGE_OPTIONS = [
    ["1d", "1D"],
    ["1w", "1W"],
    ["1m", "1M"],
    ["6m", "6M"],
    ["1y", "1Y"],
  ];

  async function fetchMetrics(moduleName, metricName, hoursOrOptions = 24) {
    const options = typeof hoursOrOptions === "object" && hoursOrOptions !== null
      ? hoursOrOptions
      : { hours: hoursOrOptions };
    const params = new URLSearchParams({
      module: moduleName,
      metric: metricName,
    });
    if (options.range) params.set("range", normalizeRange(options.range));
    else params.set("hours", String(options.hours ?? 24));
    const response = await fetch(`/api/history/metrics?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`History request failed: ${response.status}`);
    return response.json();
  }

  async function fetchLatest() {
    const response = await fetch("/api/history/latest", { cache: "no-store" });
    if (!response.ok) throw new Error(`History latest request failed: ${response.status}`);
    return response.json();
  }

  function renderBarChart(element, points, options = {}) {
    renderLineChart(element, points, options);
  }

  function renderLineChart(element, points, options = {}) {
    if (!element) return;
    const target = renderTarget(element, options);
    const rows = normalizedPoints(points);
    if (rows.length < (options.minimumPoints || 2)) {
      renderEmpty(target, options.emptyMessage || "No data available for this range yet.");
      return;
    }

    const width = 720;
    const height = 280;
    const left = 58;
    const right = 18;
    const top = 18;
    const bottom = 46;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const maxValue = niceMax(Math.max(...rows.map((row) => row.value), 1));
    const yTicks = [0, maxValue * 0.25, maxValue * 0.5, maxValue * 0.75, maxValue];
    const pointsText = rows.map((row, index) => {
      const x = left + (rows.length === 1 ? 0 : (index / (rows.length - 1)) * plotWidth);
      const y = top + plotHeight - (row.value / maxValue) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const xLabels = xAxisLabels(rows, left, plotWidth);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.classList.add("history-line-svg");
    svg.innerHTML = `
      <text class="axis-title y-title" x="14" y="${top + 12}">${escapeText(options.yLabel || options.unit || "")}</text>
      <text class="axis-title x-title" x="${left + plotWidth / 2}" y="${height - 6}">${escapeText(options.xLabel || "Time")}</text>
      ${yTicks.map((tick) => {
        const y = top + plotHeight - (tick / maxValue) * plotHeight;
        return `<line class="axis-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line>
          <text class="axis-label y-axis" x="${left - 10}" y="${y + 4}">${formatTick(tick, options.tickDigits ?? 1)}</text>`;
      }).join("")}
      ${xLabels.map((label) => `<text class="axis-label x-axis" x="${label.x}" y="${height - 24}">${escapeText(label.text)}</text>`).join("")}
      <line class="axis-base" x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}"></line>
      <line class="axis-base" x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}"></line>
      <polyline class="history-line primary" points="${pointsText}"></polyline>
      ${rows.map((row, index) => {
        const x = left + (rows.length === 1 ? 0 : (index / (rows.length - 1)) * plotWidth);
        const y = top + plotHeight - (row.value / maxValue) * plotHeight;
        return `<circle class="history-point" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"><title>${escapeText(row.label)}: ${formatTick(row.value, options.digits ?? 2)} ${escapeText(options.unit || row.unit || "")}</title></circle>`;
      }).join("")}
    `;
    target.appendChild(svg);
  }

  function renderComparisonChart(element, series, options = {}) {
    if (!element) return;
    const target = renderTarget(element, options);
    const first = normalizedPoints(series?.first);
    const second = normalizedPoints(series?.second);
    const length = Math.min(first.length, second.length);
    if (length < (options.minimumPoints || 2)) {
      renderEmpty(target, options.emptyMessage || "No data available for this range yet.");
      return;
    }

    const rowsA = first.slice(-length);
    const rowsB = second.slice(-length);
    const maxValue = niceMax(Math.max(...rowsA.map((row) => row.value), ...rowsB.map((row) => row.value), 1));
    const width = 720;
    const height = 300;
    const left = 58;
    const right = 18;
    const top = 18;
    const bottom = 54;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const yTicks = [0, maxValue * 0.25, maxValue * 0.5, maxValue * 0.75, maxValue];
    const pointsFor = (rows) => rows.map((row, index) => {
      const x = left + (index / (rows.length - 1)) * plotWidth;
      const y = top + plotHeight - (row.value / maxValue) * plotHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const xLabels = xAxisLabels(rowsA, left, plotWidth);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.classList.add("comparison-svg");
    svg.innerHTML = `
      <text class="axis-title y-title" x="14" y="${top + 12}">${escapeText(options.yLabel || "kW")}</text>
      <text class="axis-title x-title" x="${left + plotWidth / 2}" y="${height - 8}">${escapeText(options.xLabel || "Time")}</text>
      ${yTicks.map((tick) => {
        const y = top + plotHeight - (tick / maxValue) * plotHeight;
        return `<line class="axis-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"></line>
          <text class="axis-label y-axis" x="${left - 10}" y="${y + 4}">${formatTick(tick, options.tickDigits ?? 1)}</text>`;
      }).join("")}
      ${xLabels.map((label) => `<text class="axis-label x-axis" x="${label.x}" y="${height - 28}">${escapeText(label.text)}</text>`).join("")}
      <line class="axis-base" x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}"></line>
      <line class="axis-base" x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}"></line>
      <polyline class="comparison-line solar" points="${pointsFor(rowsA)}"></polyline>
      <polyline class="comparison-line ev" points="${pointsFor(rowsB)}"></polyline>
    `;
    const legend = document.createElement("div");
    legend.className = "comparison-legend";
    legend.innerHTML = `<span class="solar">${escapeText(options.firstLabel || "Solar")}</span><span class="ev">${escapeText(options.secondLabel || "EV Charging")}</span>`;
    target.append(svg, legend);
  }

  function renderTarget(element, options = {}) {
    element.replaceChildren();
    if (!options.onRangeChange) return element;
    const activeRange = normalizeRange(options.range || selectedRange(element));
    element.dataset.historyRange = activeRange;
    const controls = document.createElement("div");
    controls.className = "chart-time-range";
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "Chart time range");
    RANGE_OPTIONS.forEach(([value, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.dataset.range = value;
      button.className = value === activeRange ? "active" : "";
      button.setAttribute("aria-pressed", String(value === activeRange));
      button.addEventListener("click", () => {
        if (value === selectedRange(element)) return;
        setSelectedRange(element, value);
        options.onRangeChange(value);
      });
      controls.appendChild(button);
    });
    const chartArea = document.createElement("div");
    chartArea.className = "chart-render-area";
    element.append(controls, chartArea);
    return chartArea;
  }

  function selectedRange(element) {
    if (!element) return "1d";
    const key = rangeStorageKey(element);
    return normalizeRange(sessionStorage.getItem(key) || element.dataset.historyRange || "1d");
  }

  function setSelectedRange(element, range) {
    if (!element) return;
    const normalized = normalizeRange(range);
    element.dataset.historyRange = normalized;
    sessionStorage.setItem(rangeStorageKey(element), normalized);
  }

  function rangeStorageKey(element) {
    return `homepulse.history.range.${element.id || element.dataset.chartKey || "chart"}`;
  }

  function normalizeRange(range) {
    const normalized = String(range || "1d").toLowerCase();
    return RANGE_OPTIONS.some(([value]) => value === normalized) ? normalized : "1d";
  }

  function renderEmpty(element, message) {
    const empty = document.createElement("div");
    empty.className = "chart-empty-state";
    empty.textContent = message;
    element.appendChild(empty);
  }

  function normalizedPoints(points) {
    if (!Array.isArray(points)) return [];
    return points.map((point) => ({
      label: point.label || shortTime(point.timestamp),
      value: numberValue(point.value ?? point.kwh),
      unit: point.unit || "",
    })).filter((point) => point.value !== null);
  }

  function xAxisLabels(rows, left, plotWidth) {
    if (!rows.length) return [];
    const indexes = Array.from(new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1]));
    return indexes.map((index) => ({
      x: left + (rows.length === 1 ? 0 : (index / (rows.length - 1)) * plotWidth),
      text: rows[index].label || "",
    }));
  }

  function numberValue(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(String(value).replace("$", "").replace(",", "").trim());
    return Number.isFinite(number) ? number : null;
  }

  function niceMax(value) {
    if (value <= 1) return 1;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    return Math.ceil(value / magnitude) * magnitude;
  }

  function shortTime(timestamp) {
    if (!timestamp) return "";
    const text = String(timestamp);
    if (text.length >= 16 && text.slice(11, 16) !== "00:00") return text.slice(11, 16);
    if (text.length >= 10) return text.slice(5, 10);
    return text;
  }

  function formatTick(value, digits) {
    const number = numberValue(value);
    if (number === null) return "-";
    return number.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    });
  }

  function escapeText(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[char]));
  }

  return {
    fetchMetrics,
    fetchLatest,
    renderBarChart,
    renderLineChart,
    renderComparisonChart,
    selectedRange,
    setSelectedRange,
    normalizeRange,
  };
})();

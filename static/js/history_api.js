window.HomePulseHistory = (() => {
  const RANGE_OPTIONS = [
    ["1d", "1D"],
    ["1w", "1W"],
    ["1m", "1M"],
    ["6m", "6M"],
    ["1y", "1Y"],
  ];

  const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const DAY_NAMES   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

  // Parse "2026-06-30 20:28:52" or ISO strings into a Date object.
  function parseTs(ts) {
    if (!ts) return null;
    const d = new Date(String(ts).replace(" ", "T").replace(/\.\d+$/, ""));
    return Number.isNaN(d.getTime()) ? null : d;
  }

  /**
   * Short x-axis tick label, range-aware.
   *   1d → "20:28" (HH:MM)    1w → "Mon" (day name)
   *   1m → "6/30"              6m → "Jun 30"    1y → "Jun"
   */
  function formatHistoryLabel(timestamp, range) {
    const d = parseTs(timestamp);
    if (!d) return shortTime(timestamp);
    const h  = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    switch (String(range || "1d").toLowerCase()) {
      case "1d":  return `${h}:${mi}`;
      case "1w":  return DAY_NAMES[d.getDay()];
      case "1m":  return `${d.getMonth() + 1}/${d.getDate()}`;
      case "6m":  return `${MONTH_NAMES[d.getMonth()]} ${d.getDate()}`;
      case "1y":  return MONTH_NAMES[d.getMonth()];
      default:    return `${h}:${mi}`;
    }
  }

  /**
   * Full descriptive tooltip label, range-aware.
   *   1d → "Jun 30 20:28"           1w → "Mon Jun 30 20:00"
   *   1m → "Jun 30"                 6m → "Jun 30, 2026"    1y → "Jun 2026"
   */
  function formatHistoryTooltip(timestamp, range) {
    const d = parseTs(timestamp);
    if (!d) return shortTime(timestamp);
    const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    const date = `${MONTH_NAMES[d.getMonth()]} ${d.getDate()}`;
    switch (String(range || "1d").toLowerCase()) {
      case "1d":  return `${date} ${time}`;
      case "1w":  return `${DAY_NAMES[d.getDay()]} ${date} ${time}`;
      case "1m":  return date;
      case "6m":  return `${date}, ${d.getFullYear()}`;
      case "1y":  return `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
      default:    return `${date} ${time}`;
    }
  }

  // ── Tooltip overlay ────────────────────────────────────────────────────────
  function getTooltipEl() {
    let el = document.getElementById("hp-chart-tooltip");
    if (!el) {
      el = document.createElement("div");
      el.id = "hp-chart-tooltip";
      el.className = "hp-chart-tooltip";
      el.hidden = true;
      document.body.appendChild(el);
    }
    return el;
  }

  function positionTooltip(tip, event) {
    const margin = 14;
    let x = event.clientX + margin;
    let y = event.clientY + margin;
    if (x + 200 > window.innerWidth)  x = event.clientX - 200 - margin;
    if (y + 80  > window.innerHeight) y = event.clientY - 80  - margin;
    tip.style.left = `${x}px`;
    tip.style.top  = `${y}px`;
  }

  // ── Stats ──────────────────────────────────────────────────────────────────
  function calcStats(rows) {
    if (!rows.length) return null;
    const vals = rows.map(r => r.value);
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    };
  }

  // ── CSV export ─────────────────────────────────────────────────────────────
  function exportChartCSV(element, rows, options, range) {
    const id = (element.id || "chart").replace(/[^a-z0-9_-]/gi, "-");
    const unit = options.unit || "";
    const lines = [
      `"timestamp","value","unit","range"`,
      ...rows.map(r => [
        `"${String(r.tooltip || r.label).replace(/"/g, '""')}"`,
        r.value,
        `"${unit.replace(/"/g, '""')}"`,
        `"${range}"`,
      ].join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `homepulse-${id}-${range}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  function exportComparisonCSV(element, rowsA, rowsB, options, range) {
    const id = (element.id || "chart").replace(/[^a-z0-9_-]/gi, "-");
    const unit = (options.unit || "kW").replace(/"/g, '""');
    const maxLen = Math.max(rowsA.length, rowsB.length);
    const lines = [
      `"timestamp","${String(options.firstLabel || "A").replace(/"/g, '""')}","${String(options.secondLabel || "B").replace(/"/g, '""')}","unit","range"`,
      ...Array.from({ length: maxLen }, (_, i) => {
        const a = rowsA[i]; const b = rowsB[i];
        const ts = String(a?.tooltip || a?.label || b?.tooltip || b?.label || "").replace(/"/g, '""');
        return `"${ts}",${a?.value ?? ""},${b?.value ?? ""},"${unit}","${range}"`;
      }),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `homepulse-${id}-${range}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  // ── Chart footer: stats bar + export button ────────────────────────────────
  function renderChartFooter(target, element, rows, options, range) {
    const stats = calcStats(rows);
    if (!stats) return;
    const unit = escapeText(options.unit || "");
    const d = options.digits ?? 2;
    const footer = document.createElement("div");
    footer.className = "chart-footer";
    const statsBar = document.createElement("div");
    statsBar.className = "chart-stats-bar";
    statsBar.innerHTML =
      `<span>Min&nbsp;<strong>${formatTick(stats.min, d)}${unit ? "&nbsp;" + unit : ""}</strong></span>` +
      `<span>Avg&nbsp;<strong>${formatTick(stats.avg, d)}${unit ? "&nbsp;" + unit : ""}</strong></span>` +
      `<span>Max&nbsp;<strong>${formatTick(stats.max, d)}${unit ? "&nbsp;" + unit : ""}</strong></span>`;
    const exportBtn = document.createElement("button");
    exportBtn.type = "button";
    exportBtn.className = "chart-export-btn";
    exportBtn.textContent = "\u2b07 CSV";
    exportBtn.title = "Export chart data as CSV";
    exportBtn.addEventListener("click", () => exportChartCSV(element, rows, options, range));
    footer.append(statsBar, exportBtn);
    target.appendChild(footer);
  }

  function renderComparisonFooter(target, element, rowsA, rowsB, options, range) {
    const statsA = calcStats(rowsA);
    const statsB = calcStats(rowsB);
    if (!statsA && !statsB) return;
    const d = options.tickDigits ?? 1;
    const unitStr = escapeText(options.unit || "kW");
    const footer = document.createElement("div");
    footer.className = "chart-footer";
    const statsBar = document.createElement("div");
    statsBar.className = "chart-stats-bar";
    if (statsA) {
      const la = escapeText(options.firstLabel || "Solar");
      statsBar.innerHTML +=
        `<span>${la}&nbsp;peak&nbsp;<strong>${formatTick(statsA.max, d)}&nbsp;${unitStr}</strong></span>` +
        `<span>${la}&nbsp;avg&nbsp;<strong>${formatTick(statsA.avg, d)}&nbsp;${unitStr}</strong></span>`;
    }
    if (statsB) {
      const lb = escapeText(options.secondLabel || "EV");
      statsBar.innerHTML +=
        `<span>${lb}&nbsp;peak&nbsp;<strong>${formatTick(statsB.max, d)}&nbsp;${unitStr}</strong></span>`;
    }
    const exportBtn = document.createElement("button");
    exportBtn.type = "button";
    exportBtn.className = "chart-export-btn";
    exportBtn.textContent = "\u2b07 CSV";
    exportBtn.title = "Export comparison data as CSV";
    exportBtn.addEventListener("click", () => exportComparisonCSV(element, rowsA, rowsB, options, range));
    footer.append(statsBar, exportBtn);
    target.appendChild(footer);
  }

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
    const range = options.range || selectedRange(element);
    const rows = normalizedPoints(points, range);
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
        return `<circle class="history-point" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"></circle>`;
      }).join("")}
    `;
    target.appendChild(svg);

    // Styled hover tooltip via event delegation (replaces native <title>)
    const circles = [...svg.querySelectorAll("circle.history-point")];
    const tip = getTooltipEl();
    svg.addEventListener("mouseover", (e) => {
      const c = e.target.closest("circle.history-point");
      if (!c) { tip.hidden = true; return; }
      const i = circles.indexOf(c);
      if (i < 0 || i >= rows.length) return;
      const row = rows[i];
      const unit = options.unit || row.unit || "";
      tip.innerHTML =
        `<div class="hp-tip-time">${escapeText(row.tooltip || row.label)}</div>` +
        `<div class="hp-tip-val">${formatTick(row.value, options.digits ?? 2)}` +
        (unit ? `<span>\u00a0${escapeText(unit)}</span>` : "") +
        `</div>`;
      tip.hidden = false;
      positionTooltip(tip, e);
    });
    svg.addEventListener("mousemove", (e) => { if (!tip.hidden) positionTooltip(tip, e); });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; });

    renderChartFooter(target, element, rows, options, range);
  }

  function renderComparisonChart(element, series, options = {}) {
    if (!element) return;
    const target = renderTarget(element, options);
    const range = options.range || selectedRange(element);
    const first = normalizedPoints(series?.first, range);
    const second = normalizedPoints(series?.second, range);
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
    renderComparisonFooter(target, element, rowsA, rowsB, options, range);
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

  function normalizedPoints(points, range) {
    if (!Array.isArray(points)) return [];
    return points.map((point) => ({
      label:   point.label   || formatHistoryLabel(point.timestamp, range),
      tooltip: point.tooltip || formatHistoryTooltip(point.timestamp, range),
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
    formatHistoryLabel,
    formatHistoryTooltip,
    exportChartCSV,
    calcStats,
  };
})();

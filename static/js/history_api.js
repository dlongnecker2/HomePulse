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
  };
})();

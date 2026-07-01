async function loadDashboardSolarEvChart() {
  const chart = document.getElementById("dashboard-solar-ev-chart");
  if (!chart || !window.HomePulseHistory) return;
  const range = window.HomePulseHistory.selectedRange(chart);
  try {
    const [solar, ev] = await Promise.all([
      window.HomePulseHistory.fetchMetrics("solar", "current_production_kw", { range }),
      window.HomePulseHistory.fetchMetrics("energy", "charging_power_kw", { range }),
    ]);
    window.HomePulseHistory.renderComparisonChart(
      chart,
      { first: solar.points || [], second: ev.points || [] },
      {
        range,
        firstLabel: "Solar kW",
        secondLabel: "EV charging kW",
        emptyMessage: "No data available for this range yet.",
        onRangeChange: loadDashboardSolarEvChart,
      }
    );
  } catch (error) {
    window.HomePulseHistory.renderComparisonChart(chart, { first: [], second: [] }, {
      range,
      emptyMessage: "Collecting solar and charging history...",
      onRangeChange: loadDashboardSolarEvChart,
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadDashboardSolarEvChart();
  setInterval(loadDashboardSolarEvChart, 60000);
});

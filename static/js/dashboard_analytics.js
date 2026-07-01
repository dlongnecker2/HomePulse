async function loadDashboardSolarEvChart() {
  const chart = document.getElementById("dashboard-solar-ev-chart");
  if (!chart || !window.HomePulseHistory) return;
  try {
    const [solar, ev] = await Promise.all([
      window.HomePulseHistory.fetchMetrics("solar", "current_production_kw", 24),
      window.HomePulseHistory.fetchMetrics("energy", "charging_power_kw", 24),
    ]);
    window.HomePulseHistory.renderComparisonChart(
      chart,
      { first: solar.points || [], second: ev.points || [] },
      {
        firstLabel: "Solar kW",
        secondLabel: "EV charging kW",
        emptyMessage: "Collecting solar and charging history...",
      }
    );
  } catch (error) {
    window.HomePulseHistory.renderComparisonChart(chart, { first: [], second: [] }, {
      emptyMessage: "Collecting solar and charging history...",
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadDashboardSolarEvChart();
  setInterval(loadDashboardSolarEvChart, 60000);
});

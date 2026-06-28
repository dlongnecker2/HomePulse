async function loadLatencyChart() {
    const canvas = document.getElementById("latencyChart");

    if (!canvas) {
        return;
    }

    const response = await fetch("/api/charts/latency");
    const data = await response.json();

    new Chart(canvas, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: "Latency (ms)",
                    data: data.values,
                    tension: 0.25
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: {
                    display: true
                },
                tooltip: {
                    enabled: true
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: "Milliseconds"
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: "Time"
                    }
                }
            }
        }
    });
}

document.addEventListener("DOMContentLoaded", loadLatencyChart);

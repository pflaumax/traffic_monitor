/* ── Constants ──────────────────────────────────────────────────────────── */

const POLL_INTERVAL_MS = 3_000;

// Mirror CSS design tokens so chart colors stay in sync with the theme.
const COLORS = {
    accentGreen:   '#22c55e',
    accentDim:     '#16a34a',
    accentGlow:    'rgba(34, 197, 94, 0.1)',
    bgPrimary:     '#0a0f0d',
    bgSurface:     '#111a15',
    border:        '#1f3028',
    textPrimary:   '#f0fdf4',
    textSecondary: '#86efac',
    textMuted:     '#4ade80',
    statusOk:      '#22c55e', // 2xx
    statusRedirect:'#06b6d4', // 3xx
    statusWarn:    '#fbbf24', // 4xx
    statusError:   '#f87171', // 5xx
    // Rotating palette for the methods bar chart
    methods: ['#22c55e', '#16a34a', '#86efac', '#4ade80', '#10b981'],
};

/* ── Chart.js global defaults ───────────────────────────────────────────── */
Chart.defaults.color       = COLORS.textMuted;
Chart.defaults.borderColor = COLORS.border;
Chart.defaults.font.family = "'JetBrains Mono', monospace";

/* ── Helpers ────────────────────────────────────────────────────────────── */

/**
 * Map an HTTP status code string to a display color.
 * @param {string} code
 * @returns {string} hex color
 */
function getStatusColor(code) {
    const n = parseInt(code, 10);
    if (n >= 200 && n < 300) return COLORS.statusOk;
    if (n >= 300 && n < 400) return COLORS.statusRedirect;
    if (n >= 400 && n < 500) return COLORS.statusWarn;
    if (n >= 500)             return COLORS.statusError;
    return COLORS.textMuted;
}

/**
 * Format a Unix timestamp (seconds) as HH:MM.
 * @param {number} timestamp
 * @returns {string}
 */
function formatTime(timestamp) {
    return new Date(timestamp * 1000).toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
    });
}

/* ── Chart initialisation ───────────────────────────────────────────────── */

const historyChart = new Chart(
    document.getElementById('historyChart').getContext('2d'),
    {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Requests/min',
                data: [],
                borderColor:          COLORS.accentGreen,
                backgroundColor:      COLORS.accentGlow,
                fill: true,
                tension: 0.4,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: COLORS.accentGreen,
                pointBorderColor:     COLORS.bgPrimary,
                pointBorderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                y: {
                    beginAtZero: true,
                    grid:  { color: COLORS.border },
                    ticks: { color: COLORS.textMuted },
                },
                x: {
                    grid:  { color: COLORS.border },
                    ticks: { color: COLORS.textMuted, maxRotation: 45, minRotation: 45 },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: COLORS.bgSurface,
                    titleColor:      COLORS.textPrimary,
                    bodyColor:       COLORS.textSecondary,
                    borderColor:     COLORS.accentGreen,
                    borderWidth: 1,
                    padding: 12,
                    displayColors: false,
                },
            },
        },
    }
);

const statusCodesChart = new Chart(
    document.getElementById('statusCodesChart').getContext('2d'),
    {
        type: 'doughnut',
        data: {
            labels: window.__chartData.statusCodeLabels,
            datasets: [{
                data:            window.__chartData.statusCodeValues,
                backgroundColor: window.__chartData.statusCodeLabels.map(getStatusColor),
                borderColor:     COLORS.bgPrimary,
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { padding: 15, font: { size: 11 } },
                },
            },
        },
    }
);

const methodsChart = new Chart(
    document.getElementById('methodsChart').getContext('2d'),
    {
        type: 'bar',
        data: {
            labels: window.__chartData.methodLabels,
            datasets: [{
                label: 'Requests',
                data:            window.__chartData.methodValues,
                backgroundColor: COLORS.methods,
                borderColor:     COLORS.accentDim,
                borderWidth: 1,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    grid:  { color: COLORS.border },
                    ticks: { color: COLORS.textMuted },
                },
                x: {
                    grid:  { display: false },
                    ticks: { color: COLORS.textMuted },
                },
            },
            plugins: { legend: { display: false } },
        },
    }
);

/* ── Polling ────────────────────────────────────────────────────────────── */

async function updateCharts() {
    try {
        const data = await fetch('/fragments/charts').then(r => r.json());

        if (data.status_codes && Object.keys(data.status_codes).length > 0) {
            const entries = Object.entries(data.status_codes);
            statusCodesChart.data.labels                          = entries.map(([code]) => code);
            statusCodesChart.data.datasets[0].data                = entries.map(([, count]) => count);
            statusCodesChart.data.datasets[0].backgroundColor     = entries.map(([code]) => getStatusColor(code));
            statusCodesChart.update('none');
        }

        if (data.methods && Object.keys(data.methods).length > 0) {
            const entries = Object.entries(data.methods);
            methodsChart.data.labels                          = entries.map(([method]) => method);
            methodsChart.data.datasets[0].data                = entries.map(([, count]) => count);
            methodsChart.data.datasets[0].backgroundColor     = entries.map((_, i) => COLORS.methods[i % COLORS.methods.length]);
            methodsChart.update('none');
        }

        document.getElementById('lastUpdated').textContent =
            `Updated: ${new Date().toLocaleTimeString('en-US', {
                hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
            })}`;
    } catch (err) {
        console.error('Failed to update charts:', err);
    }
}

async function updateHistory() {
    try {
        const data = await fetch('/fragments/history?limit=60').then(r => r.json());

        if (data.history?.length > 0) {
            historyChart.data.labels              = data.history.map(p => formatTime(p.timestamp));
            historyChart.data.datasets[0].data    = data.history.map(p => p.count);
            historyChart.update('none');
        }
    } catch (err) {
        console.error('Failed to update history:', err);
    }
}

// Kick off immediately, then poll on interval
updateCharts();
updateHistory();

setInterval(updateCharts,  POLL_INTERVAL_MS);
setInterval(updateHistory, POLL_INTERVAL_MS);

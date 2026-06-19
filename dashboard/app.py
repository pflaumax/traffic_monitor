import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

app = FastAPI(title="Traffic Monitor")
templates = Jinja2Templates(directory="templates")

# Proxy URL (configurable via environment)
PROXY_URL = os.getenv("PROXY_URL", "http://proxy:8000")


async def fetch_stats() -> dict[str, Any] | None:
    """Fetch stats from the proxy service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{PROXY_URL}/stats", timeout=5.0)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error("Failed to fetch stats: %s", e)
        return None


def calculate_error_rate(stats: dict[str, Any]) -> float:
    """Calculate error rate from status codes."""
    total = stats.get("total_requests", 0)
    if total == 0:
        return 0.0

    error_count = 0
    status_codes = stats.get("status_codes", {})
    for code, count in status_codes.items():
        if int(code) >= 400:
            error_count += count

    return round((error_count / total) * 100, 2)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main dashboard page."""
    stats = await fetch_stats()

    if stats is None:
        stats = {
            "total_requests": 0,
            "avg_response_time_ms": 0.0,
            "status_codes": {},
            "methods": {},
            "top_paths": [],
        }

    error_rate = calculate_error_rate(stats)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "total_requests": stats.get("total_requests", 0),
            "avg_latency": stats.get("avg_response_time_ms", 0.0),
            "error_rate": error_rate,
            "top_paths": stats.get("top_paths", []),
            "status_codes": stats.get("status_codes", {}),
            "methods": stats.get("methods", {}),
        },
    )


@app.get("/fragments/kpis", response_class=HTMLResponse)
async def kpis_fragment(request: Request):
    """Return KPI cards HTML fragment."""
    stats = await fetch_stats()

    if stats is None:
        return HTMLResponse(
            """
            <div class="kpi-card">
                <div class="kpi-label">Total Requests</div>
                <div class="kpi-value">—</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Avg Latency</div>
                <div class="kpi-value">—<span class="kpi-unit">ms</span></div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Error Rate</div>
                <div class="kpi-value">—<span class="kpi-unit">%</span></div>
            </div>
            """
        )

    error_rate = calculate_error_rate(stats)
    total = stats.get("total_requests", 0)
    avg_latency = stats.get("avg_response_time_ms", 0.0)

    return HTMLResponse(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Total Requests</div>
            <div class="kpi-value">{total:,}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Avg Latency</div>
            <div class="kpi-value">{avg_latency:.1f}<span class="kpi-unit">ms</span></div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Error Rate</div>
            <div class="kpi-value">{error_rate}<span class="kpi-unit">%</span></div>
        </div>
        """
    )


@app.get("/fragments/top-paths", response_class=HTMLResponse)
async def top_paths_fragment():
    """Return top paths table rows HTML fragment."""
    stats = await fetch_stats()

    if stats is None or not stats.get("top_paths"):
        return HTMLResponse(
            """
            <tr>
                <td colspan="2" class="empty-state">
                    <div>No data available</div>
                </td>
            </tr>
            """
        )

    rows = []
    for item in stats["top_paths"]:
        path = item.get("path", "—")
        count = item.get("count", 0)
        rows.append(
            f"""
            <tr>
                <td>
                    <div class="path-cell">
                        <span class="status-dot"></span>
                        <span>{path}</span>
                    </div>
                </td>
                <td class="count-cell" style="text-align: right;">
                    {count:,}
                </td>
            </tr>
            """
        )

    return HTMLResponse("".join(rows))


@app.get("/fragments/charts")
async def charts_data():
    """Return chart data as JSON for client-side Chart.js updates."""
    stats = await fetch_stats()

    if stats is None:
        return JSONResponse(
            {"status_codes": {}, "methods": {}},
        )

    return JSONResponse(
        {
            "status_codes": stats.get("status_codes", {}),
            "methods": stats.get("methods", {}),
        }
    )

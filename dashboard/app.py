import html
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

app = FastAPI(title="Traffic Monitor")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Proxy URL (configurable via environment)
PROXY_URL = os.getenv("PROXY_URL", "http://proxy:8000")

AUTH_COOKIE = "tm_token"


async def fetch_stats(token: str) -> dict[str, Any] | None:
    """Fetch stats from the proxy service using a Bearer token."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PROXY_URL}/stats",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0,
            )
            if response.status_code == 401:
                return None
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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login page."""
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Exchange credentials for a JWT via the proxy and set a session cookie."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{PROXY_URL}/auth/token",
                data={"username": username, "password": password},
                timeout=5.0,
            )
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(AUTH_COOKIE, token, httponly=True, samesite="lax")
            return response
        # Bad credentials
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"},
            status_code=401,
        )
    except Exception as e:
        logger.error("Login request failed: %s", e)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Could not reach the proxy service"},
            status_code=503,
        )


@app.post("/logout")
async def logout():
    """Clear the session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    return response


def _get_token(request: Request) -> str | None:
    return request.cookies.get(AUTH_COOKIE)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main dashboard page."""
    token = _get_token(request)
    if not token:
        return RedirectResponse(url="/login", status_code=302)

    stats = await fetch_stats(token)

    if stats is None:
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie(AUTH_COOKIE)
        return response

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
    token = _get_token(request)
    if not token:
        return HTMLResponse(status_code=401)

    stats = await fetch_stats(token)

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
async def top_paths_fragment(request: Request):
    """Return top paths table rows HTML fragment."""
    token = _get_token(request)
    if not token:
        return HTMLResponse(status_code=401)

    stats = await fetch_stats(token)

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
        path = html.escape(item.get("path", "—"))
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
async def charts_data(request: Request):
    """Return chart data as JSON for client-side Chart.js updates."""
    token = _get_token(request)
    if not token:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    stats = await fetch_stats(token)

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


@app.get("/fragments/history")
async def history_data(request: Request, limit: int = 60):
    """Return stats:history time-series data as JSON for the line chart."""
    token = _get_token(request)
    if not token:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PROXY_URL}/stats/history",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0,
            )
            response.raise_for_status()
            return JSONResponse(response.json())
    except Exception as e:
        logger.error("Failed to fetch history: %s", e)
        return JSONResponse({"history": []})

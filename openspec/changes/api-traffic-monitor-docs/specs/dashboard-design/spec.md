## ADDED Requirements

### Requirement: Dashboard Goal
The system SHALL provide a real-time traffic visualization dashboard (`dashboard/` service) that displays data from the existing `/stats` endpoint and Redis, giving the team a visual picture of live API traffic.

#### Scenario: Dashboard data source
- **WHEN** the dashboard is running
- **THEN** it SHALL read data from `GET /stats` (and optionally direct Redis reads for time-series)

### Requirement: Tech Stack Options
The dashboard design SHALL document three implementation options with pros, cons, and effort estimates:

**Option A — HTMX + FastAPI (recommended primary)**
- FastAPI serves HTML templates with Jinja2
- HTMX polls `/stats` every 3 seconds and swaps DOM elements
- Zero build step; fits existing Python stack
- Effort: ~4 hours
- Pros: No JS framework, hot reload via Compose Watch, easy Docker integration
- Cons: Requires a new FastAPI service; slightly more setup than Option B

**Option B — Static HTML (fast demo fallback)**
- Single `dashboard/index.html` served by nginx or Python's `http.server`
- Fetches `/stats` via `fetch()` every 3 seconds
- Chart.js for graphs
- Effort: ~2 hours
- Pros: Zero backend, fastest to demo
- Cons: No server-side logic, harder to extend

**Option C — Grafana + Redis plugin (future Phase 3)**
- Grafana reads directly from Redis
- Adds `grafana` service to `docker-compose.yml`
- Effort: ~1 hour setup, 0 code
- Pros: Production-grade, time-series support, alerting
- Cons: Adds Grafana dependency; less custom

**Recommendation:** Option A (HTMX) as primary implementation; Option B as 2-hour demo fallback.

#### Scenario: Tech stack decision documented
- **WHEN** dashboard implementation begins
- **THEN** the chosen option SHALL be recorded in the implementation notes

### Requirement: Main Dashboard UI Layout
The dashboard SHALL display the following layout at `/dashboard` (or `/ui`):

```
┌─────────────────────────────────────────────┐
│  🚦 API Traffic Monitor          [live ●]   │
├──────────┬──────────┬──────────┬────────────┤
│  Total   │   Avg    │  Error   │  Uptime    │
│ Requests │ Latency  │  Rate    │            │
│  12,453  │  284ms   │  2.1%    │  4h 32m    │
├──────────┴──────────┴──────────┴────────────┤
│  Requests/min (last 10 min) [line chart]    │
│  ▁▂▄▆▅▃▂▅▇█▆▄                              │
├─────────────────────┬───────────────────────┤
│  Top Endpoints      │  Status Codes         │
│  /get        4,231  │  ██ 200  89%          │
│  /post       2,108  │  ░░ 404   8%          │
│  /anything   1,892  │  ░  500   3%          │
├─────────────────────┼───────────────────────┤
│  HTTP Methods       │  Top Client IPs       │
│  GET    ████ 78%    │  127.0.0.1    8,231   │
│  POST   ██   19%    │  1.2.3.4      2,104   │
│  PUT    ░     3%    │  5.6.7.8        118   │
└─────────────────────┴───────────────────────┘
```

#### Scenario: Dashboard renders all components
- **WHEN** the dashboard page loads
- **THEN** it SHALL display total requests, avg latency, error rate, top endpoints, status codes, and HTTP methods

### Requirement: Dashboard UI Components
Each dashboard component SHALL have a defined data source, update frequency, and visual type:

| Component | Data Source | Update Frequency | Visual Type |
|---|---|---|---|
| Total Requests | `stats:total` via `/stats` → `total_requests` | Every 3s | Large number |
| Avg Latency | `/stats` → `avg_response_time_ms` | Every 3s | Large number (ms) |
| Error Rate | Computed: `(4xx+5xx) / total * 100` from `/stats` → `status_codes` | Every 3s | Percentage |
| Requests/min chart | `GET /stats/history` (🔲 planned) | Every 3s | Line chart |
| Top Endpoints | `/stats` → `top_paths` | Every 3s | Table (path, count) |
| Status Codes | `/stats` → `status_codes` | Every 3s | Bar/pie chart |
| HTTP Methods | `/stats` → `methods` | Every 3s | Bar chart |
| Top Client IPs | 🔲 Requires new Redis key `stats:top_ips` | Every 3s | Table |

#### Scenario: Auto-refresh
- **WHEN** the dashboard is open
- **THEN** all components SHALL refresh every 3 seconds without a full page reload

### Requirement: New Endpoints for Dashboard
The dashboard SHALL require the following endpoints beyond what currently exists:

- `GET /stats` — ✅ already exists; returns totals
- `GET /health` — ✅ already exists
- `GET /stats/history` — 🔲 planned; returns time-series data for the line chart (requires Redis sorted sets with timestamps)

#### Scenario: History endpoint needed
- **WHEN** the line chart component is implemented
- **THEN** `GET /stats/history` SHALL return an array of `{timestamp, request_count}` objects

### Requirement: Phased Implementation Plan
The dashboard SHALL be implemented in phases:

**Phase 1 — Demo-ready (~2 hours):**
- Single `dashboard/index.html` with Chart.js
- Polls `GET /stats` every 3s via `fetch()`
- Displays: total requests, top endpoints, status code pie chart, method breakdown
- Served by adding a static file endpoint to FastAPI or a minimal nginx service

**Phase 2 — Proper service (~4 hours):**
- `dashboard/` FastAPI app with Jinja2 templates
- HTMX for real-time DOM updates
- Added to `docker-compose.yml` as `dashboard` service
- Compose Watch for hot reload

**Phase 3 — Production-grade (future):**
- Grafana + Redis datasource plugin
- Pre-built dashboards with time-series support
- Alerts on error rate spike

#### Scenario: Phase 1 deliverable
- **WHEN** Phase 1 is complete
- **THEN** opening `dashboard/index.html` in a browser SHALL show live stats from the running proxy

### Requirement: Docker Compose Addition
The `docker-compose.yml` SHALL be updated to include the dashboard service in Phase 2:

```yaml
dashboard:
  build:
    context: .
    dockerfile: dashboard/Dockerfile
  ports:
    - "8080:8080"
  environment:
    - PROXY_BASE_URL=http://proxy:8000
  depends_on:
    proxy:
      condition: service_healthy
  develop:
    watch:
      - action: sync
        path: ./dashboard
        target: /app/dashboard
```

#### Scenario: Dashboard service starts
- **WHEN** `docker compose watch` is run after Phase 2
- **THEN** the dashboard service SHALL start and be accessible at `http://localhost:8080/dashboard`

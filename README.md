# Traffic Monitor

HTTP reverse proxy that forwards requests to an upstream API and emits traffic events to Kafka for monitoring and analytics.

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │         Docker Compose              │
                    │                                     │
Client ──────────►  │  FastAPI Proxy (:8000)              │
                    │         │                           │
                    │         ├──► Upstream (httpbin.org) │
                    │         │                           │
                    │         ├──► Kafka (http.traffic)   │
                    │         │         │                 │
                    │         │         ▼                 │
                    │         │    Consumer               │
                    │         │         │                 │
                    │         │         ▼                 │
                    │         └──► Redis (stats:*)        │
                    │                   │                 │
Browser ─────────►  │  Dashboard (:8080)                  │
                    │         │                           │
                    │         └──► /stats (reads Redis)   │
                    └─────────────────────────────────────┘
```

- `proxy/` — FastAPI app that proxies HTTP requests, enforces per-IP rate limiting, and emits traffic events to Kafka
- `shared/` — shared schemas and constants (Pydantic models, Kafka topics)
- `consumer/` — Kafka consumer that aggregates traffic events into Redis (owns all `stats:*` writes)
- `dashboard/` — Real-time analytics dashboard (FastAPI + HTMX + Chart.js) with login

## Authentication

The `/stats` and `/stats/history` endpoints are protected by **JWT (OAuth2 password flow)**:

1. **Obtain a token** via `POST /auth/token` with `username` + `password` (form-encoded)
2. **Use the token** in subsequent requests: `Authorization: Bearer <token>`
3. Tokens expire after `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default: 60 min)

The dashboard handles this transparently — users log in at `/login` and a session cookie stores the JWT.

**Default credentials (local dev only):** `admin` / `admin`

**Startup validation:** The proxy will refuse to start if `JWT_SECRET_KEY` is the default placeholder or shorter than 32 characters. Generate a production key with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Observability

### Prometheus Metrics

`GET /metrics` exposes metrics in Prometheus exposition format (no auth required):

| Metric | Type | Labels | Description |
|---|---|---|---|
| `proxy_requests_total` | counter | method, status_code | Total proxied requests |
| `proxy_request_duration_seconds` | histogram | method | Upstream response latency |
| `proxy_rate_limited_total` | counter | — | Requests rejected by rate limiter |

### Structured Logging

All proxy logs are JSON-structured via **Loguru** (serialized to stderr). Each log line includes timestamp, level, module, function, line number, and message with structured context fields.

## Consumer Groups

Kafka distributes partitions across consumer instances by `group_id`:

- **Same `group_id` → horizontal scaling.** Running multiple consumer replicas with `KAFKA_GROUP_ID=traffic-consumer-group` splits `http.traffic` partitions across them. Each event is processed by exactly one replica.
- **Distinct `group_id` → independent pipelines.** A new service (for example alerting, retention, or archival) SHALL use its own `KAFKA_GROUP_ID` so it receives every event independently of the stats aggregator.

Tune consumer behavior via environment variables documented in `.env.example` (session timeout, poll interval, fetch batching, etc.).

## Services

The system consists of 5 Docker services:

| Service | Port | Description |
|---|---|---|
| **kafka** | 29092 | Kafka broker (KRaft mode, no Zookeeper) |
| **redis** | 6379 | In-memory store for stats and rate limiting |
| **proxy** | 8000 | FastAPI reverse proxy with rate limiting and JWT auth |
| **consumer** | - | Kafka consumer that aggregates stats to Redis |
| **dashboard** | 8080 | Real-time analytics dashboard with login |

All services include health checks and Compose Watch for hot reload during development.

## Rate Limiting

The proxy includes a Redis-based sliding window rate limiter to prevent abuse:

- **Default limit**: 100 requests per minute per IP
- **Configurable** via `RATE_LIMIT_PER_MINUTE` environment variable
- **Per-IP tracking** using `x-forwarded-for` header or client IP
- **HTTP 429** response when limit exceeded
- **Fail-open**: Allows requests if Redis is unavailable (graceful degradation)

Rate limit keys: `rl:{client_ip}` (60-second TTL)

## Redis Metrics

The **consumer service** reads `http.traffic` from Kafka and atomically writes aggregated stats to Redis using a transactional pipeline. The `/stats` endpoint on the proxy reads them back in parallel via `asyncio.gather`. All `stats:*` keys have a **24-hour TTL** (configurable via `STATS_TTL_SECONDS`) for a rolling window. Tracked keys:

| Key | Type | Description | Writer | TTL |
|---|---|---|---|---|
| `stats:total_requests` | string (int) | Total proxied requests | consumer | 24h |
| `stats:status_codes` | hash | Count per HTTP status code | consumer | 24h |
| `stats:methods` | hash | Count per HTTP method | consumer | 24h |
| `stats:response_time_sum` / `stats:response_time_count` | string (float/int) | Running average response time | consumer | 24h |
| `stats:top_paths` | sorted set | Most requested paths (top 10) | consumer | 24h |
| `stats:history` | sorted set | Time-series request counts (for line chart) | consumer | 24h |
| `stats:dead_letter` | list | Poison-pill / structurally invalid events (capped at `DEAD_LETTER_MAX_LEN`) | consumer | none |
| `rl:{client_ip}` | string (int) | Rate limit counter per IP | proxy | 60s |

The consumer processes events with **at-least-once** semantics: Kafka offsets are committed manually after a successful Redis write. If Redis is unreachable, the offset stays uncommitted and Kafka redelivers on the next poll. After `KAFKA_MAX_MESSAGE_RETRIES` failed redeliveries of the same offset, or when a payload is structurally invalid, the message is routed to the `stats:dead_letter` Redis list so the partition does not stall on a poison pill. If Redis is unreachable when `/stats` is read, the endpoint returns `503`.

## Quick Start

```bash
# 1. copy env and configure
cp .env.example .env

# 2. generate required secrets
# KAFKA_CLUSTER_ID (see .env.example for instructions)
# JWT_SECRET_KEY:
python3 -c "import secrets; print(secrets.token_hex(32))"
# paste the output into .env as JWT_SECRET_KEY=<value>

# 3. start full stack
docker compose up

# 4. access services
# Proxy API: http://localhost:8000
# Dashboard: http://localhost:8080 (login with admin/admin)
# Prometheus: http://localhost:8000/metrics
```

Or run services individually:

```bash
# start infrastructure only
docker compose up -d kafka redis

# install dependencies
uv sync

# run proxy locally
KAFKA_BOOTSTRAP_SERVERS=localhost:29092 uvicorn proxy.main:app --reload

# run consumer locally (in another terminal)
KAFKA_BOOTSTRAP_SERVERS=localhost:29092 python -m consumer.main
```

## API Endpoints

### Proxy Service (port 8000)

| Endpoint | Auth | Description |
|---|---|---|
| `GET /health` | No | Health check |
| `POST /auth/token` | No | Login — returns JWT access token (form: username + password) |
| `ANY /proxy/{path}` | No | Proxy to upstream (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS) |
| `GET /stats` | Bearer | Aggregated traffic metrics from Redis |
| `GET /stats/history` | Bearer | Time-series request counts (for dashboard line chart) |
| `GET /metrics` | No | Prometheus metrics (exposition format) |

### Dashboard (port 8080)

| Endpoint | Description |
|---|---|
| `GET /login` | Login page |
| `POST /login` | Submit credentials (redirects to `/` on success) |
| `POST /logout` | Clear session and redirect to login |
| `GET /` | Real-time analytics dashboard (requires session) |
| `GET /fragments/kpis` | KPI cards HTML fragment (HTMX) |
| `GET /fragments/top-paths` | Top paths table HTML fragment (HTMX) |
| `GET /fragments/charts` | Chart data JSON |
| `GET /fragments/history` | Time-series data JSON |

**Dashboard Features:**
- Login/logout with JWT session cookie
- 3-second auto-refresh via HTMX polling
- KPI cards: Total Requests, Avg Latency, Error Rate
- Requests per minute line chart (last hour)
- Top 10 endpoints table
- Status codes breakdown (doughnut chart)
- HTTP methods distribution (bar chart)
- Dark green analytics theme

## Manual Testing

```bash
# ── Health & Metrics ──

curl http://localhost:8000/health
curl http://localhost:8000/metrics

# ── Authentication ──

# get a JWT token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -d "username=admin&password=admin" | jq -r .access_token)

echo $TOKEN

# ── Proxied Requests ──

curl http://localhost:8000/proxy/get
curl "http://localhost:8000/proxy/get?foo=bar&tag=a&tag=b"
curl -H "x-forwarded-for: 1.2.3.4" http://localhost:8000/proxy/get
curl -H "x-user-id: user123" http://localhost:8000/proxy/get

curl -X POST http://localhost:8000/proxy/post \
  -H "Content-Type: application/json" \
  -d '{"hello": "world"}'

# ── Stats (requires token) ──

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/stats | jq
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/stats/history | jq

# without token → 401
curl http://localhost:8000/stats

# ── Dashboard ──

open http://localhost:8080

# ── Rate Limiting ──

for i in {1..105}; do
  curl -s http://localhost:8000/proxy/get > /dev/null && echo "Request $i: OK" || echo "Request $i: RATE LIMITED"
done
```

## Development

```bash
# install with dev deps
uv sync --all-groups

# lint
ruff check .

# format
ruff format .

# run tests
pytest

# run tests with coverage
pytest --cov=proxy --cov=consumer --cov=shared tests/
# Current coverage: 92%
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `UPSTREAM_BASE_URL` | `https://httpbin.org` | Target API to proxy |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka broker address |
| `KAFKA_CLUSTER_ID` | *(required)* | Stable KRaft cluster ID |
| `REDIS_URL` | `redis://redis:6379` | Redis connection URL |
| `RATE_LIMIT_PER_MINUTE` | `100` | Max requests per minute per IP |
| `JWT_SECRET_KEY` | *(required, ≥32 chars)* | HMAC signing key for JWTs |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Token lifetime in minutes |
| `ADMIN_USERNAME` | `admin` | Login username |
| `ADMIN_PASSWORD` | `admin` | Login password |
| `KAFKA_GROUP_ID` | `traffic-consumer-group` | Consumer group ID |
| `KAFKA_MAX_MESSAGE_RETRIES` | `3` | Retries before dead-letter |
| `DEAD_LETTER_MAX_LEN` | `1000` | Max dead-letter list size |
| `STATS_TTL_SECONDS` | `86400` | Redis stats key TTL (rolling window) |

See `.env.example` for the full template with inline docs.

## Tech Stack

- **Backend:** Python 3.14, FastAPI, httpx, aiokafka, redis, Pydantic
- **Auth:** python-jose (JWT), bcrypt
- **Observability:** Loguru (JSON structured logs), prometheus-client
- **Frontend:** HTMX, Chart.js, Jinja2, vanilla CSS
- **Infrastructure:** Kafka (KRaft mode), Redis
- **Dev Tools:** uv (dependency management), ruff (linting/formatting), pytest
- **Deployment:** Docker Compose with Compose Watch for hot reload

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
- `dashboard/` — Real-time analytics dashboard (FastAPI + HTMX + Chart.js)

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
| **proxy** | 8000 | FastAPI reverse proxy with rate limiting |
| **consumer** | - | Kafka consumer that aggregates stats to Redis |
| **dashboard** | 8080 | Real-time analytics dashboard |

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
| `stats:dead_letter` | list | Poison-pill / structurally invalid events (capped at `DEAD_LETTER_MAX_LEN`) | consumer | none |
| `rl:{client_ip}` | string (int) | Rate limit counter per IP | proxy | 60s |

The consumer processes events with **at-least-once** semantics: Kafka offsets are committed manually after a successful Redis write. If Redis is unreachable, the offset stays uncommitted and Kafka redelivers on the next poll. After `KAFKA_MAX_MESSAGE_RETRIES` failed redeliveries of the same offset, or when a payload is structurally invalid, the message is routed to the `stats:dead_letter` Redis list so the partition does not stall on a poison pill. If Redis is unreachable when `/stats` is read, the endpoint returns `503`.

## Quick Start

```bash
# 1. copy env
cp .env.example .env
# generate KAFKA_CLUSTER_ID as described in .env.example

# 2. start full stack
docker compose up

# 3. access services
# Proxy API: http://localhost:8000
# Dashboard: http://localhost:8080
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

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `ANY /proxy/{path}` | Proxy to upstream (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS) |
| `GET /stats` | Aggregated traffic metrics from Redis |

### Dashboard (port 8080)

| Endpoint | Description |
|---|---|
| `GET /` | Real-time analytics dashboard |
| `GET /fragments/kpis` | KPI cards HTML fragment (HTMX) |
| `GET /fragments/top-paths` | Top paths table HTML fragment (HTMX) |
| `GET /fragments/charts` | Chart data JSON |

**Dashboard Features:**
- 3-second auto-refresh via HTMX polling
- KPI cards: Total Requests, Avg Latency, Error Rate
- Top 10 endpoints table
- Status codes breakdown (doughnut chart)
- HTTP methods distribution (bar chart)
- Dark green analytics theme

## Fast Tests

```bash
# healthcheck
curl http://localhost:8000/health

# proxy GET
curl http://localhost:8000/proxy/get

# query params
curl "http://localhost:8000/proxy/get?foo=bar"

# custom headers
curl -H "x-forwarded-for: 1.2.3.4" http://localhost:8000/proxy/get
curl -H "x-user-id: user123" http://localhost:8000/proxy/get

# POST with body
curl -X POST http://localhost:8000/proxy/post \
  -H "Content-Type: application/json" \
  -d '{"hello": "world"}'

# traffic stats (JSON)
curl http://localhost:8000/stats | jq

# dashboard (browser)
open http://localhost:8080

# test rate limiting (make 101+ requests quickly)
for i in {1..105}; do curl -s http://localhost:8000/proxy/get > /dev/null && echo "Request $i: OK" || echo "Request $i: RATE LIMITED"; done
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

## Tech Stack

- **Backend:** Python 3.14, FastAPI, httpx, aiokafka, redis, Pydantic
- **Frontend:** HTMX, Chart.js, vanilla CSS
- **Infrastructure:** Kafka (KRaft mode), Redis
- **Dev Tools:** uv (dependency management), ruff (linting/formatting), pytest
- **Deployment:** Docker Compose with Compose Watch for hot reload

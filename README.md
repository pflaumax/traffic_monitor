# Traffic Monitor

HTTP reverse proxy that forwards requests to an upstream API and emits traffic events to Kafka for monitoring and analytics.

## Architecture

```
Client → FastAPI Proxy → Upstream API (httpbin.org)
                ↓                ↓
            Kafka           Redis (metrics)
        (http.traffic)      (stats:*)
```

- `proxy/` — FastAPI app that proxies HTTP requests and emits traffic events
- `shared/` — shared schemas and constants (Pydantic models, Kafka topics)
- `consumer/` — Kafka consumer (planned)
- `dashboard/` — analytics dashboard (planned)

## Rate Limiting

The proxy includes a Redis-based sliding window rate limiter to prevent abuse:

- **Default limit**: 100 requests per minute per IP
- **Configurable** via `RATE_LIMIT_PER_MINUTE` environment variable
- **Per-IP tracking** using `x-forwarded-for` header or client IP
- **HTTP 429** response when limit exceeded
- **Fail-open**: Allows requests if Redis is unavailable (graceful degradation)

Rate limit keys: `rl:{client_ip}` (60-second TTL)

## Redis Metrics

After each proxied request, the proxy atomically writes aggregated stats to Redis using a pipeline. The `/stats` endpoint reads them back in parallel via `asyncio.gather`. Tracked keys:

| Key | Type | Description |
|---|---|---|
| `stats:total_requests` | string (int) | Total proxied requests |
| `stats:status_codes` | hash | Count per HTTP status code |
| `stats:methods` | hash | Count per HTTP method |
| `stats:response_time_sum` / `stats:response_time_count` | string (float/int) | Running average response time |
| `stats:top_paths` | sorted set | Most requested paths (top 10) |
| `rl:{client_ip}` | string (int) | Rate limit counter per IP (60s TTL) |

Stats writes are fire-and-forget — a Redis failure never affects the proxy response. If Redis is unreachable, `/stats` returns `503`.

## Quick Start

```bash
# 1. copy env
cp .env.example .env
# generate KAFKA_CLUSTER_ID as described in .env.example

# 2. start infrastructure
docker compose up -d kafka redis

# 3. install dependencies
uv sync

# 4. run proxy locally
KAFKA_BOOTSTRAP_SERVERS=localhost:29092 uvicorn proxy.main:app --reload
```

Or run everything in Docker:

```bash
docker compose up
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `ANY /proxy/{path}` | Proxy to upstream (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS) |
| `GET /stats` | Aggregated traffic metrics from Redis |

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

# traffic stats
curl http://localhost:8000/stats | jq

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
pytest --cov=proxy --cov=shared tests/
# Current coverage: 86%
```

## Tech Stack

- Python 3.14, FastAPI, httpx, aiokafka, redis, Pydantic
- Kafka (KRaft mode), Redis
- uv for dependency management
- ruff for linting/formatting
- Docker Compose for local infrastructure

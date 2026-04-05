# Traffic Monitor

HTTP reverse proxy that forwards requests to an upstream API and emits traffic events to Kafka for monitoring and analytics.

## Architecture

```
Client → FastAPI Proxy → Upstream API (httpbin.org)
                ↓
            Kafka (http.traffic topic)
```

- `proxy/` — FastAPI app that proxies HTTP requests and emits traffic events
- `shared/` — shared schemas and constants (Pydantic models, Kafka topics)
- `consumer/` — Kafka consumer (planned)
- `dashboard/` — analytics dashboard (planned)

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
| `ANY /proxy/{path}` | Proxy to upstream (GET, POST, PUT, PATCH, DELETE) |
| `GET /stats` | Stats skeleton (TODO) |

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
```

## Development

```bash
# install with dev deps
uv sync --all-groups

# lint
ruff check .

# format check
ruff format --check .

# run tests
pytest
```

## Tech Stack

- Python 3.14, FastAPI, httpx, aiokafka, Pydantic
- Kafka (KRaft mode), Redis
- uv for dependency management
- ruff for linting/formatting
- Docker Compose for local infrastructure

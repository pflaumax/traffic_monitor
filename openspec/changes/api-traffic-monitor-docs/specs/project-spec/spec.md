## ADDED Requirements

### Requirement: Problem Statement
The system SHALL address the need for real-time API traffic observability without modifying the upstream service. The target users are developers and operators who need to monitor, debug, and plan capacity for an HTTP API.

#### Scenario: Transparent proxying
- **WHEN** a client sends any HTTP request to the proxy
- **THEN** the proxy SHALL forward the request to the upstream API and return the upstream response unchanged (modulo filtered headers), regardless of whether monitoring side effects succeed

### Requirement: Solution Overview
The system SHALL operate as an HTTP reverse proxy that sits between clients and an upstream API (default: httpbin.org). It SHALL transparently forward all HTTP requests while emitting traffic events to Kafka and writing aggregated metrics to Redis in real time.

#### Scenario: Stats availability
- **WHEN** a client calls `GET /stats`
- **THEN** the system SHALL return aggregated metrics including total requests, status code breakdown, method breakdown, average response time, and top paths

### Requirement: Core Principles — AP over CP
The system SHALL prioritize availability over consistency (AP in CAP theorem terms). All monitoring side effects (Kafka emit, Redis stats write) SHALL be fire-and-forget via `asyncio.create_task`. Losing a monitoring event is acceptable; blocking real traffic is not.

#### Scenario: Kafka unavailable
- **WHEN** the Kafka broker is unreachable
- **THEN** the proxy SHALL still forward the request and return the upstream response to the client

#### Scenario: Redis unavailable
- **WHEN** the Redis server is unreachable
- **THEN** the proxy SHALL still forward the request and return the upstream response to the client

### Requirement: System Boundaries — In Scope
The following SHALL be in scope for the current implementation:
- HTTP reverse proxy forwarding (GET, POST, PUT, PATCH, DELETE)
- Traffic event emission to Kafka topic `http.traffic`
- Aggregated metrics storage in Redis (`stats:*` keys)
- `/health`, `/proxy/{path}`, and `/stats` endpoints
- Docker Compose orchestration of proxy, Kafka (KRaft), and Redis
- Unit tests with mocked Kafka and Redis
- CI/CD via GitHub Actions (lint + test)

#### Scenario: Proxy endpoint coverage
- **WHEN** a client sends a GET, POST, PUT, PATCH, or DELETE request to `/proxy/{path}`
- **THEN** the proxy SHALL forward it to the upstream and return the response

### Requirement: System Boundaries — Out of Scope
The following SHALL be explicitly out of scope for the current implementation:
- Authentication or authorization on any endpoint
- Rate limiting (planned, not yet implemented)
- Kafka consumer service (planned, not yet implemented)
- Dashboard UI (planned, not yet implemented)
- Prometheus metrics endpoint
- Structured logging (Loguru)
- RAG anomaly detection

#### Scenario: Unauthenticated stats access
- **WHEN** a client calls `GET /stats` without any credentials
- **THEN** the system SHALL return the stats response (no auth required in current implementation)

### Requirement: Success Criteria
The system SHALL be considered working correctly when all of the following hold:
- All 10 unit tests pass (`pytest -v`)
- `ruff check .` and `ruff format --check .` pass with zero errors
- `docker compose watch` starts all services (Kafka, Redis, proxy) with healthchecks passing
- `curl http://localhost:8000/health` returns `{"status": "ok"}`
- `curl http://localhost:8000/proxy/get` returns the upstream httpbin.org response
- `curl http://localhost:8000/stats` returns a JSON object with `total_requests`, `status_codes`, `methods`, `avg_response_time_ms`, `top_paths`

#### Scenario: Full stack smoke test
- **WHEN** `docker compose watch` is running and all healthchecks pass
- **THEN** proxying a request and then calling `/stats` SHALL show `total_requests` incremented by 1

### Requirement: Constraints
The system SHALL operate under the following constraints:
- Python ≥ 3.14 (modern union syntax `str | None`)
- All I/O SHALL be async (FastAPI + asyncio; no blocking calls in request path)
- Docker-first: all services run in containers; local dev requires Docker
- Package management via `uv` with lockfile (`uv.lock`)
- Build backend: `hatchling` for monorepo packages (`proxy/`, `shared/`)
- Linting and formatting via `ruff` ≥ 0.11

#### Scenario: Async enforcement
- **WHEN** a new route handler or background task is added
- **THEN** it SHALL use `async def` and SHALL NOT call blocking I/O directly

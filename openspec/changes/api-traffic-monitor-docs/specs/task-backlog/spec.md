## ADDED Requirements

### Requirement: DONE Tasks — Completed Commits
The task backlog SHALL include the following completed tasks derived from the commit history:

**TASK-01: Project Scaffolding**
Status: DONE | Priority: P0 | Commit: `22b577b`
The system SHALL have initial project scaffolding with skeleton FastAPI routes, `pyproject.toml`, and package structure (`proxy/`, `shared/`, `tests/`).

#### Scenario: TASK-01 complete
- **WHEN** the repository is cloned
- **THEN** `proxy/main.py`, `shared/__init__.py`, and `pyproject.toml` SHALL exist

**TASK-02: Real HTTP Proxy Forwarding**
Status: DONE | Priority: P0 | Commit: `f03f537`
The system SHALL forward HTTP requests to the upstream API using `httpx.AsyncClient`, measure `response_time_ms`, and emit a `TrafficEvent` to the console.

#### Scenario: TASK-02 complete
- **WHEN** `GET /proxy/get` is called
- **THEN** the upstream httpbin.org response SHALL be returned to the client

**TASK-03: Pydantic-Settings Config**
Status: DONE | Priority: P1 | Commit: `a12f7c9`, `c46bbcc`
The system SHALL use `pydantic-settings` `BaseSettings` for typed environment config with `.env` file support.

#### Scenario: TASK-03 complete
- **WHEN** `UPSTREAM_BASE_URL` is set in `.env`
- **THEN** `Settings().upstream_base_url` SHALL reflect that value

**TASK-04: Headers Constants**
Status: DONE | Priority: P1 | Commit: `06bc2b4`
The system SHALL store `EXCLUDED_HEADERS` and `EXCLUDED_RESPONSE_HEADERS` as `frozenset` constants in `proxy/constants.py`.

#### Scenario: TASK-04 complete
- **WHEN** `proxy/constants.py` is imported
- **THEN** `EXCLUDED_HEADERS` and `EXCLUDED_RESPONSE_HEADERS` SHALL be `frozenset` instances

**TASK-05: Docker Compose with Kafka KRaft + Redis**
Status: DONE | Priority: P0 | Commit: `9fa9647`, `aa747aa`
The system SHALL have a `docker-compose.yml` that orchestrates Kafka (KRaft mode, cp-kafka 7.8.0), Redis 7-alpine, and the proxy service with Compose Watch for hot reload.

#### Scenario: TASK-05 complete
- **WHEN** `docker compose watch` is run
- **THEN** all three services SHALL start with healthchecks passing

**TASK-06: Kafka Producer (Fire-and-Forget)**
Status: DONE | Priority: P0 | Commit: `7672198`, `a805789`, `f538390`
The system SHALL emit `TrafficEvent` messages to Kafka topic `http.traffic` using `AIOKafkaProducer` with fire-and-forget pattern. The topic constant SHALL be defined in `shared/topics.py`.

#### Scenario: TASK-06 complete
- **WHEN** a request is proxied
- **THEN** a Kafka message SHALL be emitted to `http.traffic` without blocking the response

**TASK-07: Tests + CI/CD**
Status: DONE | Priority: P1 | Commit: `5493f51`, `942b68a`, `efe753f`, `788a158`
The system SHALL have 10 unit tests (6 in `test_proxy.py`, 4 in `test_schemas.py`) with mocked Kafka and Redis, and a GitHub Actions CI workflow that runs lint and tests on push/PR.

#### Scenario: TASK-07 complete
- **WHEN** `pytest -v` is run
- **THEN** all 10 tests SHALL pass

**TASK-08: Redis-Backed /stats Endpoint**
Status: DONE | Priority: P0 | Commit: `c4ae0e2`, `a32b980`
The system SHALL write aggregated metrics to Redis via `pipeline(transaction=True)` on each proxied request, and expose `GET /stats` that reads all 6 metrics in parallel via `asyncio.gather`.

#### Scenario: TASK-08 complete
- **WHEN** requests are proxied and `GET /stats` is called
- **THEN** `total_requests` SHALL reflect the number of proxied requests

### Requirement: TODO Tasks — Roadmap Items
The task backlog SHALL include the following planned tasks:

**TASK-09: Redis Rate Limiter**
Status: TODO | Priority: P1
The system SHALL implement a sliding window rate limiter in `proxy/rate_limiter.py` using Redis `INCR "rl:{client_ip}"` + `EXPIRE 60`. Requests exceeding `rate_limit_per_minute` (default: 100, configurable in `proxy/config.py`) SHALL return HTTP 429.

#### Scenario: TASK-09 rate limit enforced
- **WHEN** a client sends more than 100 requests in 60 seconds
- **THEN** the 101st request SHALL return HTTP 429

**TASK-10: Kafka Consumer Service**
Status: TODO | Priority: P1
The system SHALL have a separate `consumer/` service with `consumer/main.py`, `consumer/Dockerfile`, and `consumer/__init__.py`. It SHALL use `AIOKafkaConsumer` to read from `http.traffic` and process events. `docker-compose.yml` SHALL be updated to include the consumer service.

**[OPEN QUESTION]** If the consumer writes to Redis, the proxy's direct Redis writes become redundant. Resolve DECISION-01 before implementing.

#### Scenario: TASK-10 consumer reads events
- **WHEN** the consumer service is running and a request is proxied
- **THEN** the consumer SHALL receive and process the Kafka event

**TASK-11: Dashboard Service**
Status: TODO | Priority: P2
The system SHALL have a `dashboard/` service. Phase 1: static `dashboard/index.html` with Chart.js polling `GET /stats` every 3s. Phase 2: FastAPI + Jinja2 + HTMX as a proper service in `docker-compose.yml`.

#### Scenario: TASK-11 dashboard displays stats
- **WHEN** the dashboard is open in a browser
- **THEN** it SHALL display total requests, top endpoints, status code breakdown, and method breakdown

**TASK-12: Expand Test Coverage**
Status: TODO | Priority: P1
The test suite SHALL be expanded to cover: `_emit_safe` failure doesn't affect proxy response; `_update_stats_safe` failure doesn't affect proxy response; Redis unreachable → `/stats` returns 503; stats increment assertions; upstream unreachable → proxy returns 502. Coverage SHALL reach ≥80%.

#### Scenario: TASK-12 coverage threshold
- **WHEN** `pytest --cov` is run
- **THEN** coverage SHALL be ≥80%

**TASK-13: Ruff Configuration**
Status: TODO | Priority: P2
`pyproject.toml` SHALL include a `[tool.ruff]` section with `line-length`, `target-version = "py314"`, and selected rule sets.

#### Scenario: TASK-13 explicit ruff config
- **WHEN** `ruff check .` is run
- **THEN** it SHALL use the explicit config from `pyproject.toml`

**TASK-14: JWT Auth on /stats**
Status: TODO | Priority: P2
`GET /stats` SHALL require a valid JWT token. Unauthenticated requests SHALL return HTTP 401.

#### Scenario: TASK-14 unauthenticated stats
- **WHEN** `GET /stats` is called without a JWT token
- **THEN** the system SHALL return HTTP 401

**TASK-15: Prometheus /metrics Endpoint**
Status: TODO | Priority: P2
The system SHALL expose `GET /metrics` in Prometheus exposition format for scraping by a Prometheus server.

#### Scenario: TASK-15 metrics endpoint
- **WHEN** `GET /metrics` is called
- **THEN** the response SHALL be valid Prometheus exposition format

**TASK-16: Loguru Structured Logging**
Status: TODO | Priority: P2
The system SHALL replace `print` statements with Loguru JSON structured logging.

#### Scenario: TASK-16 structured logs
- **WHEN** a request is proxied
- **THEN** a structured JSON log entry SHALL be emitted

**TASK-17: httpx Connection Pooling**
Status: TODO | Priority: P1
The proxy SHALL create a single `httpx.AsyncClient` in the lifespan context manager and store it on `app.state.http_client`. The current pattern of creating a new client per request SHALL be removed.

#### Scenario: TASK-17 connection pooling
- **WHEN** multiple requests are proxied
- **THEN** they SHALL reuse the same `httpx.AsyncClient` instance

### Requirement: BUG Tasks — Known Issues
The task backlog SHALL include the following bug tasks:

**BUG-01: Duplicate Query Params Lost**
Status: BUG | Priority: P2 | File: `proxy/main.py`
`params=dict(request.query_params)` converts `?tag=a&tag=b` to `?tag=b`. SHALL be fixed to use `params=str(request.query_params)` or `params=request.url.query`.

#### Scenario: BUG-01 duplicate params
- **WHEN** `GET /proxy/get?tag=a&tag=b` is called
- **THEN** both `tag=a` and `tag=b` SHALL be forwarded to the upstream

**BUG-02: New httpx Client Per Request**
Status: BUG | Priority: P1 | File: `proxy/main.py`
`async with httpx.AsyncClient() as client:` creates a new client and TCP connection per request. No connection pooling. Resolved by TASK-17.

#### Scenario: BUG-02 connection reuse
- **WHEN** TASK-17 is implemented
- **THEN** the same `httpx.AsyncClient` SHALL be reused across requests

**BUG-03: HEAD/OPTIONS Not Proxied**
Status: BUG | Priority: P2 | File: `proxy/main.py`
`methods=["GET", "POST", "PUT", "PATCH", "DELETE"]` is missing `HEAD` and `OPTIONS`. A transparent proxy SHALL forward all valid HTTP methods.

#### Scenario: BUG-03 HEAD method
- **WHEN** `HEAD /proxy/get` is called
- **THEN** the proxy SHALL forward it to the upstream

**BUG-04: No Redis Key TTL**
Status: BUG | Priority: P2 | File: `proxy/redis_client.py`
`stats:*` keys accumulate forever with no rolling window. Resolve DECISION-02 before fixing.

#### Scenario: BUG-04 TTL behavior
- **WHEN** DECISION-02 is resolved and TTL is implemented
- **THEN** `stats:*` keys SHALL expire after the configured window

**BUG-05: asyncio.create_task Without Stored Reference**
Status: BUG | Priority: P2 | File: `proxy/main.py`
`asyncio.create_task()` without storing the reference — tasks could be garbage collected before completion in edge cases. The `_safe` wrappers mitigate this but it is not ideal.

#### Scenario: BUG-05 task reference
- **WHEN** `_emit_safe` and `_update_stats_safe` tasks are created
- **THEN** their references SHALL be stored to prevent premature garbage collection

### Requirement: DECISION Tasks — Open Architecture Questions
The task backlog SHALL include the following decision tasks:

**DECISION-01: Direct Redis Writes vs. Kafka Consumer**
Status: DECISION | Priority: P0
Decide whether the proxy should continue writing to Redis directly, or whether the Kafka consumer should handle Redis writes (SRP concern). This decision blocks TASK-10.

#### Scenario: DECISION-01 resolved
- **WHEN** DECISION-01 is resolved
- **THEN** TASK-10 (Kafka Consumer) implementation SHALL follow the chosen architecture

**DECISION-02: Redis Stats Key TTL**
Status: DECISION | Priority: P1
Decide whether `stats:*` keys should have TTL for a rolling window (e.g., last 24h). This decision blocks BUG-04.

#### Scenario: DECISION-02 resolved
- **WHEN** DECISION-02 is resolved
- **THEN** BUG-04 SHALL be implemented or closed accordingly

**DECISION-03: Raw Counters vs. Rates in /stats**
Status: DECISION | Priority: P2
Decide whether `GET /stats` should return raw counters (current) or rates (req/sec). This may require time-series data in Redis.

#### Scenario: DECISION-03 resolved
- **WHEN** DECISION-03 is resolved
- **THEN** the `/stats` response schema SHALL be updated if rates are chosen

**DECISION-04: Kafka Role — Buffer or Source of Truth**
Status: DECISION | Priority: P1
Decide whether Kafka is a transient buffer (events can be lost after processing) or the source of truth (Redis is a read cache derived from Kafka). This decision affects TASK-10 and DECISION-01.

#### Scenario: DECISION-04 resolved
- **WHEN** DECISION-04 is resolved
- **THEN** the consumer service design SHALL reflect the chosen Kafka role

## 1. Resolve Blocking Architecture Decisions

- [ ] 1.1 DECISION-01: Decide whether proxy writes Redis directly or Kafka consumer handles Redis writes (blocks Kafka consumer implementation)
- [ ] 1.2 DECISION-02: Decide whether `stats:*` Redis keys should have TTL for a rolling window (blocks BUG-04 fix)
- [ ] 1.3 DECISION-03: Decide whether `/stats` should return raw counters or rates (req/sec)
- [ ] 1.4 DECISION-04: Decide Kafka's role — transient buffer or source of truth with Redis as read cache

## 2. Bug Fixes (Quick Wins)

- [x] 2.1 BUG-03: Add `HEAD` and `OPTIONS` to the proxy `methods` list in `proxy/main.py`
- [x] 2.2 BUG-01: Fix duplicate query params — replace `params=dict(request.query_params)` with `params=str(request.query_params)` in `proxy/main.py`
- [x] 2.3 BUG-05: Store `asyncio.create_task` references in `proxy/main.py` to prevent premature garbage collection
- [x] 2.4 TASK-13: Add `[tool.ruff]` section to `pyproject.toml` with `line-length`, `target-version = "py314"`, and rule sets

## 3. Connection Pooling (TASK-17 / BUG-02)

- [x] 3.1 Create `app.state.http_client` in the lifespan context manager in `proxy/main.py`
- [x] 3.2 Replace `async with httpx.AsyncClient() as client:` per-request pattern with `app.state.http_client`
- [x] 3.3 Verify all proxy tests still pass after refactor

## 4. Redis Rate Limiter (TASK-09)

- [x] 4.1 Add `rate_limit_per_minute: int = 100` to `Settings` in `proxy/config.py`
- [x] 4.2 Create `proxy/rate_limiter.py` with sliding window counter using `INCR "rl:{client_ip}"` + `EXPIRE 60`
- [x] 4.3 Integrate rate limiter as middleware or FastAPI dependency in `proxy/main.py`
- [x] 4.4 Return HTTP 429 when client exceeds threshold
- [x] 4.5 Add unit tests for rate limiter (under limit, at limit, over limit)

## 5. Expand Test Coverage (TASK-12)

- [x] 5.1 Add test: `_emit_safe` failure does not affect proxy response
- [x] 5.2 Add test: `_update_stats_safe` failure does not affect proxy response
- [x] 5.3 Add test: Redis unreachable → `GET /stats` returns HTTP 503
- [x] 5.4 Add test: stats increment assertions (verify pipeline calls with correct args)
- [x] 5.5 Add test: upstream unreachable → proxy returns HTTP 502
- [x] 5.6 Run `pytest --cov` and verify coverage ≥ 80%

## 6. Kafka Consumer Service (TASK-10)

- [ ] 6.1 Confirm DECISION-01 and DECISION-04 are resolved before starting
- [ ] 6.2 Create `consumer/__init__.py`
- [ ] 6.3 Create `consumer/main.py` with `AIOKafkaConsumer` reading from `http.traffic`
- [ ] 6.4 Implement event processing logic (per DECISION-01 outcome)
- [ ] 6.5 Create `consumer/Dockerfile` (multi-stage, non-root user, mirrors `proxy/Dockerfile` pattern)
- [ ] 6.6 Add `consumer` service to `docker-compose.yml` with `depends_on: kafka`
- [ ] 6.7 Verify consumer starts and reads events when proxy is running

## 7. Redis TTL / Rolling Window (BUG-04)

- [ ] 7.1 Confirm DECISION-02 is resolved before starting
- [ ] 7.2 If TTL chosen: add `EXPIRE` calls to `update_stats` pipeline in `proxy/redis_client.py`
- [ ] 7.3 Update `GET /stats` response if rolling window changes semantics
- [ ] 7.4 Add tests for TTL behavior

## 8. Dashboard — Phase 1 Static Demo (TASK-11)

- [ ] 8.1 Create `dashboard/index.html` with Chart.js CDN
- [ ] 8.2 Implement `fetch('/stats')` polling every 3 seconds
- [ ] 8.3 Render total requests, avg latency, error rate as large numbers
- [ ] 8.4 Render top endpoints as a table
- [ ] 8.5 Render status code breakdown as a pie/bar chart
- [ ] 8.6 Render HTTP method breakdown as a bar chart
- [ ] 8.7 Serve `dashboard/index.html` via FastAPI `StaticFiles` or a minimal nginx service
- [ ] 8.8 Verify dashboard displays live data from running proxy

## 9. Dashboard — Phase 2 HTMX Service (TASK-11 continued)

- [ ] 9.1 Create `dashboard/` FastAPI app with Jinja2 templates
- [ ] 9.2 Add HTMX polling for real-time DOM updates (3s interval)
- [ ] 9.3 Create `dashboard/Dockerfile`
- [ ] 9.4 Add `dashboard` service to `docker-compose.yml` with Compose Watch
- [ ] 9.5 Verify dashboard accessible at `http://localhost:8080/dashboard`

## 10. Stats History Endpoint (for Dashboard Line Chart)

- [ ] 10.1 Add Redis sorted set `stats:history` with `ZADD stats:history {timestamp} {count}` in `proxy/redis_client.py`
- [ ] 10.2 Implement `GET /stats/history` endpoint in `proxy/main.py` returning last N time-series entries
- [ ] 10.3 Wire dashboard line chart to `GET /stats/history`

## 11. Auth and Observability (TASK-14, TASK-15, TASK-16)

- [ ] 11.1 TASK-14: Add JWT auth dependency to `GET /stats`; return HTTP 401 for unauthenticated requests
- [ ] 11.2 TASK-15: Add `GET /metrics` endpoint in Prometheus exposition format
- [ ] 11.3 TASK-16: Replace `print` statements with Loguru JSON structured logging throughout `proxy/`

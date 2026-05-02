## ADDED Requirements

### Requirement: Health Check Endpoint
The system SHALL expose `GET /health` that returns a simple liveness indicator.

- **Method:** GET
- **Path:** `/health`
- **Auth:** None
- **Response 200:**
  ```json
  {"status": "ok"}
  ```

#### Scenario: Health check success
- **WHEN** `GET /health` is called and the proxy process is running
- **THEN** the system SHALL return HTTP 200 with body `{"status": "ok"}`

### Requirement: Proxy Endpoint
The system SHALL expose `ANY /proxy/{path}` that transparently forwards requests to the upstream API.

- **Methods:** GET, POST, PUT, PATCH, DELETE
- **Path:** `/proxy/{path}` where `{path}` is any path segment(s)
- **Auth:** None
- **Path Parameters:**
  - `path` (string, required): The path to forward to the upstream API (e.g., `get`, `post`, `anything/foo`)
- **Query Parameters:** All query parameters are forwarded to the upstream as-is
- **Request Headers:** All headers except those in `EXCLUDED_HEADERS` frozenset are forwarded
- **Request Body:** Forwarded verbatim for POST, PUT, PATCH
- **Response:** Upstream response is returned with filtered headers (headers in `EXCLUDED_RESPONSE_HEADERS` are removed)
- **Response 200–5xx:** Upstream status code is forwarded transparently
- **Response 502:** Upstream is unreachable

**Known Bug:** `params=dict(request.query_params)` loses duplicate query params (e.g., `?tag=a&tag=b` → `?tag=b`). See BUG-04 in task backlog.

**Known Bug:** HEAD and OPTIONS methods are not currently proxied. See BUG-03 in task backlog.

#### Scenario: Proxy GET request
- **WHEN** `GET /proxy/get` is called
- **THEN** the system SHALL forward the request to `{UPSTREAM_BASE_URL}/get` and return the upstream response

#### Scenario: Proxy POST with body
- **WHEN** `POST /proxy/post` is called with a JSON body
- **THEN** the system SHALL forward the body to `{UPSTREAM_BASE_URL}/post` and return the upstream response

#### Scenario: Query parameter forwarding
- **WHEN** `GET /proxy/get?foo=bar` is called
- **THEN** the system SHALL forward `?foo=bar` to the upstream

#### Scenario: Upstream 404 forwarding
- **WHEN** the upstream returns HTTP 404
- **THEN** the proxy SHALL return HTTP 404 to the client

#### Scenario: Upstream unreachable
- **WHEN** the upstream API is unreachable
- **THEN** the proxy SHALL return HTTP 502 to the client

#### Scenario: Traffic event emission
- **WHEN** any request is proxied successfully
- **THEN** a `TrafficEvent` SHALL be emitted to Kafka topic `http.traffic` (fire-and-forget)

#### Scenario: Stats update on proxy
- **WHEN** any request is proxied successfully
- **THEN** Redis `stats:*` keys SHALL be updated atomically via pipeline (fire-and-forget)

**Example request:**
```bash
curl http://localhost:8000/proxy/get
curl -X POST http://localhost:8000/proxy/post \
  -H "Content-Type: application/json" \
  -d '{"hello": "world"}'
curl "http://localhost:8000/proxy/get?foo=bar"
curl -H "x-user-id: user123" http://localhost:8000/proxy/get
```

### Requirement: Stats Endpoint
The system SHALL expose `GET /stats` that returns aggregated traffic metrics from Redis.

- **Method:** GET
- **Path:** `/stats`
- **Auth:** None (🔲 JWT auth planned — see TODO-11 in task backlog)
- **Response 200:**
  ```json
  {
    "total_requests": 12453,
    "status_codes": {
      "200": 11083,
      "404": 996,
      "500": 374
    },
    "methods": {
      "GET": 9714,
      "POST": 2364,
      "PUT": 375
    },
    "avg_response_time_ms": 284.3,
    "top_paths": [
      ["/get", 4231],
      ["/post", 2108],
      ["/anything", 1892]
    ]
  }
  ```
- **Response 503:** Redis is unreachable

#### Scenario: Stats response structure
- **WHEN** `GET /stats` is called and Redis is reachable
- **THEN** the response SHALL include `total_requests` (integer), `status_codes` (object), `methods` (object), `avg_response_time_ms` (float), and `top_paths` (array of [path, count] pairs)

#### Scenario: Stats Redis failure
- **WHEN** `GET /stats` is called and Redis is unreachable
- **THEN** the system SHALL return HTTP 503

#### Scenario: Stats parallel reads
- **WHEN** `GET /stats` is called
- **THEN** all 6 Redis reads SHALL be executed in parallel via `asyncio.gather`

**Example request:**
```bash
curl http://localhost:8000/stats | jq
```

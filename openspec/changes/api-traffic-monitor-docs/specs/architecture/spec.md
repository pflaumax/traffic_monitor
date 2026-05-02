## ADDED Requirements

### Requirement: Component Diagram
The system architecture SHALL be represented by the following ASCII component diagram:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                           │
│                                                                 │
│  ┌──────────┐    ┌─────────────────────────────────────────┐   │
│  │  Client  │───▶│         FastAPI Proxy (proxy/)          │   │
│  └──────────┘    │  proxy/main.py                          │   │
│                  │  proxy/config.py                        │   │
│                  │  proxy/constants.py                     │   │
│                  │  proxy/kafka_producer.py                │   │
│                  │  proxy/redis_client.py                  │   │
│                  └──────────┬──────────────────────────────┘   │
│                             │                                   │
│              ┌──────────────┼──────────────┐                   │
│              ▼              ▼              ▼                   │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │  httpbin.org  │  │  Kafka KRaft │  │  Redis 7-alpine  │    │
│  │  (upstream)   │  │  (cp-kafka   │  │  stats:* keys    │    │
│  │               │  │   7.8.0)     │  │                  │    │
│  └───────────────┘  └──────────────┘  └──────────────────┘    │
│                             │                                   │
│                    ┌────────────────┐                          │
│                    │  consumer/     │  🔲 PLANNED              │
│                    │  (empty)       │                          │
│                    └────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

#### Scenario: Component diagram accuracy
- **WHEN** the architecture diagram is reviewed against the codebase
- **THEN** every component in the diagram SHALL correspond to an actual file or service in the repository

### Requirement: Proxy Request Data Flow
The system SHALL process each proxied request through the following steps:

1. Client sends HTTP request to `FastAPI Proxy /proxy/{path}`
2. Proxy extracts client IP, method, path, headers, body, query params
3. Proxy forwards request to upstream via `httpx.AsyncClient`
4. Upstream returns response; proxy measures `response_time_ms`
5. Proxy fires `asyncio.create_task(_emit_safe)` → `AIOKafkaProducer` → Kafka topic `http.traffic`
6. Proxy fires `asyncio.create_task(_update_stats_safe)` → `redis.pipeline(transaction=True)` → Redis `stats:*` keys
7. Proxy returns upstream response to client (with filtered headers)

Steps 5 and 6 are fire-and-forget; they SHALL NOT block the response to the client.

#### Scenario: Fire-and-forget side effects
- **WHEN** a proxied request completes
- **THEN** the response SHALL be returned to the client before Kafka and Redis operations complete

### Requirement: Stats Read Data Flow
The system SHALL process `GET /stats` requests through the following steps:

1. Client sends `GET /stats`
2. Handler calls `asyncio.gather` with 6 parallel Redis reads
3. Redis returns: `stats:total`, `stats:status_codes` (hash), `stats:methods` (hash), `stats:total_response_time`, `stats:top_paths` (sorted set), `stats:request_count_for_avg`
4. Handler computes `avg_response_time_ms = total_response_time / request_count`
5. Handler returns JSON response
6. If Redis is unreachable, handler returns HTTP 503

#### Scenario: Redis unreachable on stats read
- **WHEN** `GET /stats` is called and Redis is unreachable
- **THEN** the system SHALL return HTTP 503

### Requirement: Component Responsibilities
Each component SHALL have the following responsibilities:

| Component | Responsibility |
|---|---|
| `proxy/main.py` | FastAPI app, lifespan manager, `proxy_handler`, `/health`, `/stats`, `_emit_safe`, `_update_stats_safe` |
| `proxy/config.py` | `Settings(BaseSettings)`: `upstream_base_url`, `kafka_bootstrap_servers`, `redis_url` |
| `proxy/constants.py` | `EXCLUDED_HEADERS`, `EXCLUDED_RESPONSE_HEADERS` (frozensets) |
| `proxy/kafka_producer.py` | `start_producer`, `stop_producer`, `emit_event`, `get_producer` — lifecycle on `app.state` |
| `proxy/redis_client.py` | `start_redis`, `stop_redis`, `update_stats` (pipeline with 6 atomic operations) |
| `shared/schemas.py` | `TrafficEvent` Pydantic model |
| `shared/topics.py` | `TOPIC_HTTP_TRAFFIC = "http.traffic"` |
| `tests/` | Unit tests with mocked Kafka and Redis |
| Kafka (KRaft) | Async event bus for traffic events |
| Redis | In-memory store for aggregated metrics |
| Docker Compose | Orchestrates all services with healthchecks and Compose Watch |

#### Scenario: Responsibility isolation
- **WHEN** a new feature is added to the proxy
- **THEN** HTTP protocol constants SHALL go in `proxy/constants.py`, environment config SHALL go in `proxy/config.py`, and infrastructure state SHALL be stored on `app.state`

### Requirement: Failure Modes
The system SHALL handle the following failure modes gracefully:

| Failure | Behavior |
|---|---|
| Kafka broker unreachable | `_emit_safe` catches exception, logs error, proxy response unaffected |
| Redis unreachable (write) | `_update_stats_safe` catches exception, logs error, proxy response unaffected |
| Redis unreachable (read) | `GET /stats` returns HTTP 503 |
| Upstream API unreachable | Proxy returns HTTP 502 to client |
| Upstream returns error (4xx/5xx) | Proxy forwards the error response transparently |

#### Scenario: Kafka failure isolation
- **WHEN** the Kafka broker is down and a request is proxied
- **THEN** the proxy SHALL return the upstream response with HTTP 200 (or upstream status) and SHALL NOT return a 5xx error due to Kafka failure

#### Scenario: Stats endpoint Redis failure
- **WHEN** Redis is unreachable and `GET /stats` is called
- **THEN** the system SHALL return HTTP 503

### Requirement: Open Architecture Questions
The following architectural questions SHALL be formally documented as unresolved pending team decision:

1. **[OPEN QUESTION]** Should the proxy write to Redis directly, or should a Kafka consumer handle Redis writes? (SRP concern — proxy currently does both forwarding and metrics aggregation)
2. **[OPEN QUESTION]** Should Redis `stats:*` keys have TTL for a rolling window (e.g., last 24h)? Currently stats accumulate forever.
3. **[OPEN QUESTION]** Is `pipeline(transaction=True)` necessary for metrics, or is eventual consistency acceptable?
4. **[OPEN QUESTION]** Should `/stats` return raw counters or rates (req/sec)?
5. **[OPEN QUESTION]** What is the intended role of Kafka — just a buffer, or source of truth with Redis as read cache?
6. **[OPEN QUESTION]** Should `update_stats` stay in `proxy/redis_client.py` or move to a separate `proxy/stats.py`?

#### Scenario: Open question tracking
- **WHEN** a roadmap task depends on an unresolved architectural question
- **THEN** the task SHALL reference the relevant DECISION task in the backlog before implementation begins

### Requirement: Scalability Notes
The system SHALL document the following scalability constraints and requirements for horizontal scaling:

- The proxy is stateless per request; horizontal scaling requires a shared Redis instance (already the case)
- Kafka naturally supports multiple producers; adding proxy replicas requires no Kafka changes
- The `KAFKA_CLUSTER_ID` must be stable across restarts to prevent data loss (set via `.env`)
- Connection pooling (`app.state.http_client`) is required before scaling — currently a known bug (new `httpx.AsyncClient` per request)
- Redis `pipeline(transaction=True)` ensures atomic metric writes; this remains correct under multiple proxy replicas

#### Scenario: Multi-replica correctness
- **WHEN** multiple proxy instances write to the same Redis
- **THEN** `pipeline(transaction=True)` SHALL ensure no partial metric updates occur

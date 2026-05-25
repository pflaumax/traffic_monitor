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
│                  │  proxy/rate_limiter.py                  │   │
│                  │  proxy/redis_client.py (reads only)     │   │
│                  └──────────┬──────────────────────────────┘   │
│                             │                                   │
│              ┌──────────────┼──────────────┐                   │
│              ▼              ▼              ▼                   │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │  httpbin.org  │  │  Kafka KRaft │  │  Redis 7-alpine  │    │
│  │  (upstream)   │  │  (cp-kafka   │  │  rl:*, stats:*   │    │
│  │               │  │   7.8.0)     │  │                  │    │
│  └───────────────┘  └──────┬───────┘  └────────▲─────────┘    │
│                            │                   │               │
│                            ▼                   │               │
│                  ┌──────────────────────┐      │               │
│                  │  Consumer (consumer/)│──────┘               │
│                  │  consumer/main.py    │  writes stats:*      │
│                  │  consumer/config.py  │                      │
│                  │  consumer/redis_client.py                   │
│                  └──────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

#### Scenario: Component diagram accuracy
- **WHEN** the architecture diagram is reviewed against the codebase
- **THEN** every component in the diagram SHALL correspond to an actual file or service in the repository

### Requirement: Proxy Request Data Flow
The system SHALL process each proxied request through the following steps:

1. Client sends HTTP request to `FastAPI Proxy /proxy/{path}`
2. Proxy enforces rate limit via `check_rate_limit` (Redis `rl:*`); over-limit clients receive HTTP 429
3. Proxy extracts client IP, method, path, headers, body, query params
4. Proxy forwards request to upstream via the shared `app.state.http_client` (`httpx.AsyncClient`)
5. Upstream returns response; proxy measures `response_time_ms`
6. Proxy fires `asyncio.create_task(_emit_safe)` → `AIOKafkaProducer` → Kafka topic `http.traffic`
7. Proxy returns upstream response to client (with filtered headers)

Step 6 is fire-and-forget; it SHALL NOT block the response to the client. Per DECISION-01, the proxy SHALL NOT write aggregated metrics to Redis directly; the Kafka consumer owns all `stats:*` writes.

#### Scenario: Fire-and-forget Kafka emit
- **WHEN** a proxied request completes
- **THEN** the response SHALL be returned to the client before the Kafka emit completes

#### Scenario: Proxy does not write stats to Redis
- **WHEN** a request is proxied
- **THEN** the proxy SHALL NOT call any Redis write command against `stats:*` keys

### Requirement: Consumer Event Processing Flow
The system SHALL include a standalone `consumer/` service that owns all `stats:*` aggregation in Redis. Per DECISION-01, Redis writes have been moved out of the proxy. Per DECISION-04, Kafka is a transient buffer and Redis is the source of truth for aggregated stats.

The consumer SHALL process each event through the following steps:

1. `AIOKafkaConsumer` polls topic `http.traffic` with `group_id=traffic-consumer-group` and `enable_auto_commit=False`
2. For each message, the consumer deserializes the `TrafficEvent` payload; malformed JSON or events missing required fields SHALL be sent to the Redis dead-letter list `stats:dead_letter` and the offset SHALL be committed so the partition makes progress
3. The consumer calls `update_stats(redis, event)` which updates the 6 `stats:*` keys atomically via `redis.pipeline(transaction=True)`
4. On success, the consumer commits the Kafka offset (at-least-once semantics)
5. On transient processing failure (e.g. Redis unreachable), the consumer SHALL NOT commit; the message will be redelivered on the next poll. After `KAFKA_MAX_MESSAGE_RETRIES` redeliveries of the same `(partition, offset)`, the message SHALL be routed to the dead-letter list and the offset SHALL be committed to prevent poison-pill stalls
6. On `SIGTERM` / `SIGINT`, the consumer SHALL stop the Kafka consumer and close the Redis client without logging the clean shutdown as an error

#### Scenario: Consumer aggregates stats
- **WHEN** a traffic event is published to `http.traffic`
- **THEN** the consumer SHALL update the `stats:*` Redis keys exactly once under normal operation

#### Scenario: At-least-once processing
- **WHEN** the consumer crashes after reading but before committing an offset
- **THEN** the message SHALL be redelivered on the next startup

#### Scenario: Poison-pill isolation
- **WHEN** a structurally invalid event is received, or processing fails more than `KAFKA_MAX_MESSAGE_RETRIES` times for the same `(partition, offset)`
- **THEN** the consumer SHALL route the message to the Redis dead-letter list `stats:dead_letter` and commit the offset so the partition is not blocked

### Requirement: Stats Read Data Flow
The system SHALL process `GET /stats` requests through the following steps:

1. Client sends `GET /stats`
2. Handler calls `asyncio.gather` with 6 parallel Redis reads
3. Redis returns: `stats:total_requests`, `stats:status_codes` (hash), `stats:methods` (hash), `stats:response_time_sum`, `stats:response_time_count`, `stats:top_paths` (sorted set)
4. Handler computes `avg_response_time_ms = stats:response_time_sum / stats:response_time_count`
5. Handler returns JSON response
6. If Redis is unreachable, handler returns HTTP 503

#### Scenario: Redis unreachable on stats read
- **WHEN** `GET /stats` is called and Redis is unreachable
- **THEN** the system SHALL return HTTP 503

### Requirement: Component Responsibilities
Each component SHALL have the following responsibilities:

| Component | Responsibility |
|---|---|
| `proxy/main.py` | FastAPI app, lifespan manager, `proxy_handler`, `/health`, `/stats`, `_emit_safe` |
| `proxy/config.py` | `Settings(BaseSettings)`: `upstream_base_url`, `kafka_bootstrap_servers`, `redis_url`, `rate_limit_per_minute` |
| `proxy/constants.py` | `EXCLUDED_HEADERS`, `EXCLUDED_RESPONSE_HEADERS` (frozensets) |
| `proxy/kafka_producer.py` | `start_producer`, `stop_producer`, `emit_event`, `get_producer` — lifecycle on `app.state` |
| `proxy/rate_limiter.py` | `check_rate_limit` — per-IP sliding window via `INCR rl:{ip}` + `EXPIRE 60` |
| `proxy/redis_client.py` | `start_redis`, `stop_redis` — **reads only**; no `stats:*` writes |
| `consumer/main.py` | `ConsumerService` — `AIOKafkaConsumer` loop, manual offset commit, signal-driven shutdown |
| `consumer/config.py` | `Settings(BaseSettings)`: `kafka_bootstrap_servers`, `redis_url`, `kafka_group_id`, `kafka_auto_offset_reset` |
| `consumer/redis_client.py` | `start_redis`, `stop_redis`, `update_stats` (pipeline with 6 atomic operations) |
| `shared/schemas.py` | `TrafficEvent`, `PathCount`, `StatsResponse` Pydantic models |
| `shared/topics.py` | `TOPIC_HTTP_TRAFFIC = "http.traffic"` |
| `tests/` | Unit tests with mocked Kafka and Redis |
| Kafka (KRaft) | Async event bus for traffic events |
| Redis | In-memory store for aggregated metrics and rate-limit counters |
| Docker Compose | Orchestrates all services with healthchecks and Compose Watch |

#### Scenario: Responsibility isolation
- **WHEN** a new feature is added to the proxy
- **THEN** HTTP protocol constants SHALL go in `proxy/constants.py`, environment config SHALL go in `proxy/config.py`, and infrastructure state SHALL be stored on `app.state`

#### Scenario: Redis write isolation
- **WHEN** a change introduces a new `stats:*` aggregation
- **THEN** the write SHALL live in `consumer/redis_client.py`, not in the proxy

### Requirement: Failure Modes
The system SHALL handle the following failure modes gracefully:

| Failure | Behavior |
|---|---|
| Kafka broker unreachable (producer) | `_emit_safe` catches exception, logs error, proxy response unaffected |
| Kafka broker unreachable (consumer) | Consumer retries connection per aiokafka defaults; offsets remain uncommitted |
| Redis unreachable (consumer write) | `update_stats` raises, offset is NOT committed, message will be redelivered |
| Redis unreachable (proxy read) | `GET /stats` returns HTTP 503 |
| Upstream API unreachable | Proxy returns HTTP 502 to client |
| Upstream returns error (4xx/5xx) | Proxy forwards the error response transparently |
| Rate limit exceeded | Proxy returns HTTP 429 |

#### Scenario: Kafka failure isolation on write path
- **WHEN** the Kafka broker is down and a request is proxied
- **THEN** the proxy SHALL return the upstream response with its original status and SHALL NOT return a 5xx error due to Kafka failure

#### Scenario: Stats endpoint Redis failure
- **WHEN** Redis is unreachable and `GET /stats` is called
- **THEN** the system SHALL return HTTP 503

#### Scenario: Consumer Redis failure redelivery
- **WHEN** Redis is unreachable during consumer event processing
- **THEN** the Kafka offset SHALL NOT be committed and the message SHALL be retried on the next poll

### Requirement: Open Architecture Questions
The following architectural questions SHALL be formally documented as unresolved pending team decision:

1. **[RESOLVED DECISION-01]** Proxy writes to Kafka only; the consumer owns Redis writes.
2. **[OPEN QUESTION]** Should Redis `stats:*` keys have TTL for a rolling window (e.g., last 24h)? Tracked as DECISION-02.
3. **[OPEN QUESTION]** Is `pipeline(transaction=True)` necessary for metrics, or is eventual consistency acceptable?
4. **[RESOLVED DECISION-03]** `/stats` returns raw counters for MVP.
5. **[RESOLVED DECISION-04]** Kafka is a transient buffer; Redis is the source of truth for aggregated stats.
6. **[OPEN QUESTION]** Should `update_stats` grow beyond `consumer/redis_client.py` (e.g., dedicated `consumer/stats.py` as the surface expands)?

#### Scenario: Open question tracking
- **WHEN** a roadmap task depends on an unresolved architectural question
- **THEN** the task SHALL reference the relevant DECISION task in the backlog before implementation begins

### Requirement: Scalability Notes
The system SHALL document the following scalability constraints and requirements for horizontal scaling:

- The proxy is stateless per request; horizontal scaling requires a shared Redis instance (already the case)
- Kafka naturally supports multiple producers; adding proxy replicas requires no Kafka changes
- The `KAFKA_CLUSTER_ID` must be stable across restarts to prevent data loss (set via `.env`)
- Connection pooling (`app.state.http_client`) is in place; a single `httpx.AsyncClient` is shared across requests
- Consumer replicas SHALL share `group_id=traffic-consumer-group` so Kafka distributes `http.traffic` partitions across them; additional analytics services SHALL use distinct group ids
- Redis `pipeline(transaction=True)` ensures atomic metric writes; this remains correct under multiple consumer replicas

#### Scenario: Multi-replica correctness
- **WHEN** multiple consumer instances write to the same Redis
- **THEN** `pipeline(transaction=True)` SHALL ensure no partial metric updates occur

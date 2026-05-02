## ADDED Requirements

### Requirement: TrafficEvent Pydantic Model
The system SHALL define a `TrafficEvent` Pydantic v2 model in `shared/schemas.py` with the following fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `client_ip` | `str` | required | IP address of the requesting client |
| `method` | `str` | required | HTTP method (GET, POST, PUT, PATCH, DELETE) |
| `path` | `str` | required | Request path forwarded to upstream (e.g., `/get`) |
| `status_code` | `int` | required | HTTP status code returned by upstream |
| `response_time_ms` | `float` | required | Round-trip latency in milliseconds |
| `timestamp` | `datetime` | `datetime.utcnow()` | UTC timestamp of the request |
| `user_id` | `str \| None` | `None` | Optional user identifier from `x-user-id` header |

The model SHALL use `.model_dump(mode="json")` for serialization to ensure datetime fields are JSON-serializable.

#### Scenario: Default timestamp
- **WHEN** a `TrafficEvent` is created without a `timestamp` argument
- **THEN** `timestamp` SHALL default to the current UTC datetime

#### Scenario: Optional user_id
- **WHEN** a `TrafficEvent` is created without a `user_id` argument
- **THEN** `user_id` SHALL be `None`

#### Scenario: JSON serialization
- **WHEN** `.model_dump(mode="json")` is called on a `TrafficEvent`
- **THEN** the result SHALL be a JSON-serializable dict with `timestamp` as an ISO 8601 string

### Requirement: Redis Key Schema
The system SHALL use the following Redis key schema under the `stats:` namespace:

| Key | Redis Type | What It Stores | How Updated | Example Value |
|---|---|---|---|---|
| `stats:total` | String (counter) | Total number of proxied requests | `INCR` on each request | `"12453"` |
| `stats:status_codes` | Hash | Count per HTTP status code | `HINCRBY stats:status_codes {status_code} 1` | `{"200": "11083", "404": "996"}` |
| `stats:methods` | Hash | Count per HTTP method | `HINCRBY stats:methods {method} 1` | `{"GET": "9714", "POST": "2364"}` |
| `stats:total_response_time` | String (float counter) | Sum of all response times in ms | `INCRBYFLOAT` on each request | `"3537219.4"` |
| `stats:top_paths` | Sorted Set | Request count per path (score = count) | `ZINCRBY stats:top_paths 1 {path}` | `[("/get", 4231), ("/post", 2108)]` |
| `stats:request_count_for_avg` | String (counter) | Count of requests with response time recorded (denominator for avg) | `INCR` on each request | `"12453"` |

All 6 write operations SHALL be executed atomically in a single `pipeline(transaction=True)` call.

**[OPEN QUESTION]** Should `stats:*` keys have TTL for a rolling window (e.g., last 24h)? Currently they accumulate forever.

#### Scenario: Atomic pipeline write
- **WHEN** a request is proxied
- **THEN** all 6 Redis write operations SHALL be executed in a single atomic pipeline

#### Scenario: Stats key types
- **WHEN** `stats:status_codes` is read
- **THEN** it SHALL be a Redis Hash with status code strings as fields and count strings as values

### Requirement: Kafka Message Format
The system SHALL publish messages to Kafka using the following format:

- **Topic:** `http.traffic` (defined in `shared/topics.py` as `TOPIC_HTTP_TRAFFIC`)
- **Message format:** JSON bytes, serialized from `TrafficEvent.model_dump(mode="json")` using `orjson.dumps`
- **Producer config:** `AIOKafkaProducer` with built-in aiokafka retries; no manual retry logic
- **Delivery guarantee:** Fire-and-forget (no `await` on send confirmation)
- **Compression:** Default (none explicitly configured)

**Example message payload:**
```json
{
  "client_ip": "127.0.0.1",
  "method": "GET",
  "path": "/get",
  "status_code": 200,
  "response_time_ms": 284.3,
  "timestamp": "2026-05-02T10:30:00.123456",
  "user_id": null
}
```

#### Scenario: Kafka message serialization
- **WHEN** a `TrafficEvent` is emitted to Kafka
- **THEN** the message SHALL be JSON bytes produced by `orjson.dumps(event.model_dump(mode="json"))`

#### Scenario: Topic constant reuse
- **WHEN** the Kafka consumer service is implemented
- **THEN** it SHALL import `TOPIC_HTTP_TRAFFIC` from `shared/topics.py` (not hardcode the topic name)

### Requirement: Pydantic Settings Model
The system SHALL define a `Settings(BaseSettings)` model in `proxy/config.py` with the following fields:

| Field | Type | Default | Source |
|---|---|---|---|
| `upstream_base_url` | `str` | `"https://httpbin.org"` | `UPSTREAM_BASE_URL` env var |
| `kafka_bootstrap_servers` | `str` | `"kafka:9092"` | `KAFKA_BOOTSTRAP_SERVERS` env var |
| `redis_url` | `str` | `"redis://redis:6379"` | `REDIS_URL` env var |

The model SHALL use `extra="ignore"` to silently discard unknown environment variables.

#### Scenario: Default config values
- **WHEN** no environment variables are set
- **THEN** `Settings()` SHALL use the defaults above

#### Scenario: Environment override
- **WHEN** `UPSTREAM_BASE_URL=https://example.com` is set
- **THEN** `Settings().upstream_base_url` SHALL equal `"https://example.com"`

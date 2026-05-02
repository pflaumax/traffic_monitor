## ADDED Requirements

### Requirement: Environment Variables Reference
The system SHALL document all environment variables used across all services:

| Variable | Purpose | Default | Used By | Required |
|---|---|---|---|---|
| `UPSTREAM_BASE_URL` | Target API to proxy requests to | `https://httpbin.org` | `proxy/config.py` | No (has default) |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker address | `kafka:9092` | `proxy/config.py` | No (has default) |
| `REDIS_URL` | Redis connection URL | `redis://redis:6379` | `proxy/config.py` | No (has default) |
| `KAFKA_CLUSTER_ID` | Stable KRaft cluster ID (prevents data loss on restart) | None — must generate | Kafka (`docker-compose.yml`) | **Yes** |
| `KAFKA_NODE_ID` | Kafka broker node ID | `1` (hardcoded in compose) | Kafka | No |
| `KAFKA_PROCESS_ROLES` | KRaft roles | `broker,controller` (hardcoded) | Kafka | No |

#### Scenario: Missing KAFKA_CLUSTER_ID
- **WHEN** `docker compose watch` is run without `KAFKA_CLUSTER_ID` set in `.env`
- **THEN** Kafka SHALL fail to start or generate a new cluster ID on each restart (causing data loss)

#### Scenario: Default proxy config
- **WHEN** no environment variables are set
- **THEN** the proxy SHALL connect to `https://httpbin.org`, `kafka:9092`, and `redis://redis:6379`

### Requirement: KAFKA_CLUSTER_ID Generation
The system SHALL document how to generate a stable `KAFKA_CLUSTER_ID`:

```bash
python3 -c "import uuid, base64; print(base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip('='))"
```

Copy the output into `.env`:
```
KAFKA_CLUSTER_ID=<generated-value>
```

This value SHALL remain stable across container restarts to prevent Kafka data loss.

#### Scenario: Cluster ID generation
- **WHEN** the above command is run
- **THEN** it SHALL produce a URL-safe base64-encoded UUID string suitable for use as `KAFKA_CLUSTER_ID`

### Requirement: .env.example Contents
The repository SHALL include a `.env.example` file with the following contents:

```env
UPSTREAM_BASE_URL=https://httpbin.org
KAFKA_CLUSTER_ID=your-generated-id-here
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
REDIS_URL=redis://redis:6379
```

#### Scenario: .env.example present
- **WHEN** the repository is cloned
- **THEN** `.env.example` SHALL exist and contain all required environment variable keys

### Requirement: Docker Compose Services
The `docker-compose.yml` SHALL define the following services:

| Service | Image | Ports | Healthcheck | Notes |
|---|---|---|---|---|
| `kafka` | `confluentinc/cp-kafka:7.8.0` | `29092:29092` (external), `9092:9092` (internal) | TCP check on port 9092 | KRaft mode; `KAFKA_CLUSTER_ID` required |
| `redis` | `redis:7-alpine` | `6379:6379` | `redis-cli ping` | Persistent data via volume |
| `proxy` | Built from `proxy/Dockerfile` | `8000:8000` | `GET /health` | Depends on kafka + redis; Compose Watch enabled |

Compose Watch SHALL be configured for the `proxy` service to sync `./proxy` → `/app/proxy` on file changes.

#### Scenario: All services start
- **WHEN** `docker compose watch` is run with a valid `.env`
- **THEN** all three services SHALL start with healthchecks passing within 60 seconds

### Requirement: Local Development Setup
The system SHALL document the following local development setup steps:

1. Clone the repository: `git clone https://github.com/pflaumax/traffic_monitor`
2. Switch to development branch: `git checkout development`
3. Copy `.env.example` to `.env`: `cp .env.example .env`
4. Generate and set `KAFKA_CLUSTER_ID` in `.env`
5. Install dependencies: `uv sync --all-groups`
6. Start all services: `docker compose watch`
7. Verify: `curl http://localhost:8000/health`

#### Scenario: Fresh setup
- **WHEN** the setup steps are followed on a clean machine with Docker and uv installed
- **THEN** `curl http://localhost:8000/health` SHALL return `{"status": "ok"}`

### Requirement: Development Commands Reference
The system SHALL document all development commands:

**Local Development:**
```bash
# Install all dependencies (including dev)
uv sync --all-groups

# Run proxy locally (needs Kafka + Redis running)
KAFKA_BOOTSTRAP_SERVERS=localhost:29092 REDIS_URL=redis://localhost:6379 uvicorn proxy.main:app --reload
```

**Docker:**
```bash
# Start everything (Kafka + Redis + proxy with hot reload)
docker compose watch

# Start only infrastructure
docker compose up -d kafka redis

# Rebuild proxy image
docker compose build proxy

# Verify container runs as non-root
docker compose run --rm proxy whoami  # → appuser

# Check image size
docker images | grep traffic  # → ~50MB
```

**Testing:**
```bash
# Run all tests
pytest -v

# Run with uv
uv run pytest -v
```

**Linting:**
```bash
# Check lint
ruff check .

# Check formatting
ruff format --check .

# Auto-fix
ruff check --fix .
ruff format .
```

**Manual API Testing:**
```bash
# Healthcheck
curl http://localhost:8000/health

# Proxy GET
curl http://localhost:8000/proxy/get

# Query params
curl "http://localhost:8000/proxy/get?foo=bar"

# Custom headers
curl -H "x-forwarded-for: 1.2.3.4" http://localhost:8000/proxy/get
curl -H "x-user-id: user123" http://localhost:8000/proxy/get

# POST with body
curl -X POST http://localhost:8000/proxy/post \
  -H "Content-Type: application/json" \
  -d '{"hello": "world"}'

# Traffic stats
curl http://localhost:8000/stats | jq
```

#### Scenario: Test suite passes
- **WHEN** `uv run pytest -v` is run
- **THEN** all 10 tests SHALL pass with zero failures

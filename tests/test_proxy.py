from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from proxy.main import app


@pytest.fixture
def mock_kafka():
    """Mock Kafka producer so tests don't need a running broker."""
    with (
        patch("proxy.kafka_producer.start_producer", new_callable=AsyncMock),
        patch("proxy.kafka_producer.stop_producer", new_callable=AsyncMock),
        patch("proxy.kafka_producer.emit_event", new_callable=AsyncMock) as mock_emit,
    ):
        yield mock_emit


@pytest.fixture
def mock_redis():
    """Mock Redis client so tests don't need a running Redis."""
    redis = AsyncMock()
    redis.aclose = AsyncMock()

    # Use a function instead of a consumed list — never exhausts between tests.
    async def _get(key: str):
        return {
            "stats:total_requests": "10",
            "stats:response_time_sum": "500.0",
            "stats:response_time_count": "10",
        }.get(key)

    redis.get = AsyncMock(side_effect=_get)
    redis.hgetall = AsyncMock(
        side_effect=lambda key: {
            "stats:status_codes": {"200": "10"},
            "stats:methods": {"GET": "10"},
        }.get(key, {})
    )
    redis.zrevrange = AsyncMock(return_value=[("/get", 10.0)])
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    pipeline_cm = MagicMock()
    pipe = MagicMock()  # pipeline commands (incr, hincrby, etc) are sync queuing calls
    pipe.execute = AsyncMock(return_value=[])
    pipeline_cm.__aenter__ = AsyncMock(return_value=pipe)
    pipeline_cm.__aexit__ = AsyncMock(return_value=False)
    redis.pipeline = MagicMock(return_value=pipeline_cm)
    with (
        patch("proxy.redis_client.start_redis", new_callable=AsyncMock),
        patch("proxy.redis_client.stop_redis", new_callable=AsyncMock),
    ):
        yield redis


def _make_response(status_code: int, content: bytes) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.headers = {}
    return r


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient for upstream requests."""

    async def _request(method, url, **kwargs):
        if "/status/404" in url:
            return _make_response(404, b"")
        return _make_response(
            200,
            b'{"args": {"foo": "bar"}, "json": {"hello": "world"}}',
        )

    client = AsyncMock()
    client.request = AsyncMock(side_effect=_request)
    client.aclose = AsyncMock()
    return client


@pytest.fixture
async def client(mock_kafka, mock_redis, mock_http_client):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        app.state.redis = mock_redis
        app.state.http_client = mock_http_client
        yield ac


@pytest.fixture
async def auth_headers(client):
    """Obtain a valid JWT by logging in with the default admin credentials."""
    resp = await client.post(
        "/auth/token",
        data={"username": "admin", "password": "admin"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_healthcheck(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_stats_requires_auth(client):
    """GET /stats without a token SHALL return HTTP 401."""
    resp = await client.get("/stats")
    assert resp.status_code == 401


async def test_stats_with_valid_token(client, auth_headers, mock_redis):
    """GET /stats with a valid JWT SHALL return 200 and the expected shape."""
    resp = await client.get("/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "status_codes" in data
    assert "methods" in data
    assert "avg_response_time_ms" in data
    assert "top_paths" in data


async def test_stats_invalid_token(client):
    """GET /stats with a bad token SHALL return HTTP 401."""
    resp = await client.get("/stats", headers={"Authorization": "Bearer bad.token.here"})
    assert resp.status_code == 401


async def test_login_success(client):
    """POST /auth/token with correct credentials SHALL return an access token."""
    resp = await client.post(
        "/auth/token",
        data={"username": "admin", "password": "admin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_login_wrong_password(client):
    """POST /auth/token with wrong password SHALL return HTTP 401."""
    resp = await client.post(
        "/auth/token",
        data={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


async def test_login_wrong_username(client):
    """POST /auth/token with unknown username SHALL return HTTP 401."""
    resp = await client.post(
        "/auth/token",
        data={"username": "hacker", "password": "admin"},
    )
    assert resp.status_code == 401


async def test_proxy_get(client):
    """Proxy GET should return 200 from upstream (httpbin)."""
    resp = await client.get("/proxy/get")
    assert resp.status_code == 200


async def test_proxy_post(client):
    resp = await client.post(
        "/proxy/post",
        json={"hello": "world"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["json"] == {"hello": "world"}


async def test_proxy_query_params(client):
    resp = await client.get("/proxy/get", params={"foo": "bar"})
    assert resp.status_code == 200
    assert resp.json()["args"]["foo"] == "bar"


async def test_proxy_not_found(client):
    resp = await client.get("/proxy/status/404")
    assert resp.status_code == 404


async def test_metrics_endpoint(client):
    """GET /metrics SHALL return Prometheus exposition text."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "proxy_requests_total" in resp.text
    assert "proxy_request_duration_seconds" in resp.text


async def test_stats_history_requires_auth(client):
    """GET /stats/history without a token SHALL return HTTP 401."""
    resp = await client.get("/stats/history")
    assert resp.status_code == 401


async def test_stats_history_empty(client, auth_headers, mock_redis):
    """GET /stats/history SHALL return an empty list when Redis has no history data."""
    mock_redis.zrevrange.return_value = []

    resp = await client.get("/stats/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"history": []}


async def test_stats_history_respects_limit(client, auth_headers, mock_redis):
    """GET /stats/history?limit=N SHALL call Redis with the correct range and return
    entries in chronological (ascending) order."""
    # zrevrange returns newest-first; simulate 5 minute buckets
    fake_entries = [(str(1700000000 + i * 60), float(i + 1)) for i in range(4, -1, -1)]
    mock_redis.zrevrange.return_value = fake_entries

    resp = await client.get("/stats/history?limit=5", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    # Redis was called with the correct key and limit bounds
    mock_redis.zrevrange.assert_called_once_with("stats:history", 0, 4, withscores=True)

    # Response must be chronological (ascending timestamp)
    assert len(data["history"]) == 5
    timestamps = [p["timestamp"] for p in data["history"]]
    assert timestamps == sorted(timestamps)


async def test_stats_history_redis_unavailable(client, auth_headers, mock_redis):
    """GET /stats/history SHALL return HTTP 503 when Redis is unreachable."""
    mock_redis.zrevrange.side_effect = Exception("Redis connection refused")

    resp = await client.get("/stats/history", headers=auth_headers)
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()

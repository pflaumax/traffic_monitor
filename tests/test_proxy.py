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
    # gather() calls: total, status_codes, methods, time_sum, time_count, top_paths
    redis.get = AsyncMock(side_effect=[b"10", b"500.0", b"10"])
    redis.hgetall = AsyncMock(side_effect=[{b"200": b"10"}, {b"GET": b"10"}])
    redis.zrevrange = AsyncMock(return_value=[(b"/get", 10.0)])
    pipeline_cm = MagicMock()
    pipe = MagicMock()  # pipeline commands (incr, hincrby, etc.) are sync queuing calls
    pipe.execute = AsyncMock(return_value=[])
    pipeline_cm.__aenter__ = AsyncMock(return_value=pipe)
    pipeline_cm.__aexit__ = AsyncMock(return_value=False)
    redis.pipeline = MagicMock(return_value=pipeline_cm)
    with (
        patch("proxy.redis_client.start_redis", new_callable=AsyncMock),
        patch("proxy.redis_client.stop_redis", new_callable=AsyncMock),
    ):
        yield redis


@pytest.fixture
async def client(mock_kafka, mock_redis):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        app.state.redis = mock_redis
        yield ac


async def test_healthcheck(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_stats(client):
    resp = await client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "status_codes" in data
    assert "methods" in data
    assert "avg_response_time_ms" in data
    assert "top_paths" in data


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

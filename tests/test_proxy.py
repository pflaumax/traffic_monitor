from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from proxy.main import app


@pytest.fixture(scope="module")
def mock_kafka():
    """Mock Kafka producer so tests don't need a running broker.

    Module-scoped since Kafka mock is stateless and can be safely reused.
    """
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
    redis.incr = AsyncMock(side_effect=lambda key: 1)
    redis.expire = AsyncMock(side_effect=lambda key, ttl: True)
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
        import httpx

        app.state.http_client = httpx.AsyncClient()
        yield ac
        await app.state.http_client.aclose()


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


async def test_emit_safe_failure_does_not_affect_response(mock_kafka, mock_redis):
    """Test that Kafka emit failures don't break the proxy response."""
    mock_kafka.side_effect = Exception("Kafka connection failed")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        app.state.redis = mock_redis
        import httpx

        app.state.http_client = httpx.AsyncClient()
        resp = await ac.get("/proxy/get")
        assert resp.status_code == 200

        await app.state.http_client.aclose()


async def test_update_stats_safe_failure_does_not_affect_response(mock_kafka, mock_redis):
    """Test that Redis stats update failures don't break the proxy response."""
    mock_redis.pipeline.side_effect = Exception("Redis connection failed")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        app.state.redis = mock_redis
        import httpx

        app.state.http_client = httpx.AsyncClient()
        resp = await ac.get("/proxy/get")
        assert resp.status_code == 200

        await app.state.http_client.aclose()


async def test_stats_redis_unreachable_returns_503(mock_kafka):
    """Test that /stats returns 503 when Redis is unreachable."""
    redis = AsyncMock()
    redis.get.side_effect = Exception("Redis connection failed")

    with (
        patch("proxy.redis_client.start_redis", new_callable=AsyncMock),
        patch("proxy.redis_client.stop_redis", new_callable=AsyncMock),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            ac.app = app
            app.state.redis = redis
            import httpx

            app.state.http_client = httpx.AsyncClient()
            resp = await ac.get("/stats")
            assert resp.status_code == 503
            assert "Stats unavailable" in resp.json()["detail"]

            await app.state.http_client.aclose()


async def test_stats_increment_assertions(mock_kafka, mock_redis):
    """Test that stats are incremented with correct Redis pipeline calls."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        app.state.redis = mock_redis
        import httpx

        app.state.http_client = httpx.AsyncClient()
        resp = await ac.get("/proxy/get")
        assert resp.status_code == 200

        import asyncio

        await asyncio.sleep(0.1)
        mock_redis.pipeline.assert_called()
        await app.state.http_client.aclose()


async def test_upstream_unreachable_returns_502(mock_kafka, mock_redis):
    """Test that proxy returns 502 when upstream is unreachable."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.app = app
        app.state.redis = mock_redis
        import httpx

        failing_client = AsyncMock()
        failing_client.request.side_effect = httpx.RequestError("Connection refused")
        app.state.http_client = failing_client

        resp = await ac.get("/proxy/get")
        assert resp.status_code == 502
        assert "Upstream unreachable" in resp.json()["detail"]

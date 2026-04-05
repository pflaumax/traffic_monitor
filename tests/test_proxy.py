from unittest.mock import AsyncMock, patch

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
async def client(mock_kafka):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_healthcheck(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_stats(client):
    resp = await client.get("/stats")
    assert resp.status_code == 200
    assert "message" in resp.json()


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

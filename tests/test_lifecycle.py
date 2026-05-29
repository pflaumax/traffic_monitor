from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consumer import main as consumer_main
from consumer import redis_client as consumer_redis_client
from proxy import kafka_producer as proxy_kafka_producer
from proxy import redis_client as proxy_redis_client


async def test_proxy_start_redis_sets_app_state(monkeypatch):
    """start_redis SHALL attach a Redis client to app.state.redis."""
    fake_client = MagicMock()
    monkeypatch.setattr(
        proxy_redis_client.aioredis,
        "from_url",
        MagicMock(return_value=fake_client),
    )
    app = SimpleNamespace(state=SimpleNamespace())

    await proxy_redis_client.start_redis(app)

    assert app.state.redis is fake_client


async def test_proxy_stop_redis_closes_client():
    """stop_redis SHALL await aclose() on the attached Redis client."""
    fake_client = MagicMock()
    fake_client.aclose = AsyncMock()
    app = SimpleNamespace(state=SimpleNamespace(redis=fake_client))

    await proxy_redis_client.stop_redis(app)

    fake_client.aclose.assert_awaited_once()


async def test_proxy_stop_redis_is_a_noop_without_state():
    """stop_redis SHALL tolerate a missing app.state.redis (partial startup)."""
    app = SimpleNamespace(state=SimpleNamespace())
    # Must not raise
    await proxy_redis_client.stop_redis(app)


async def test_proxy_start_producer_creates_and_starts(monkeypatch):
    """start_producer SHALL instantiate AIOKafkaProducer and await start()."""
    fake_producer = MagicMock()
    fake_producer.start = AsyncMock()
    ctor = MagicMock(return_value=fake_producer)
    monkeypatch.setattr(proxy_kafka_producer, "AIOKafkaProducer", ctor)
    app = SimpleNamespace(state=SimpleNamespace())

    await proxy_kafka_producer.start_producer(app)

    ctor.assert_called_once()
    fake_producer.start.assert_awaited_once()
    assert app.state.producer is fake_producer


async def test_proxy_stop_producer_stops_when_set():
    """stop_producer SHALL call producer.stop() when one is attached."""
    fake_producer = MagicMock()
    fake_producer.stop = AsyncMock()
    app = SimpleNamespace(state=SimpleNamespace(producer=fake_producer))

    await proxy_kafka_producer.stop_producer(app)

    fake_producer.stop.assert_awaited_once()


async def test_proxy_stop_producer_noop_without_producer():
    """stop_producer SHALL tolerate missing app.state.producer."""
    app = SimpleNamespace(state=SimpleNamespace())
    # Must not raise
    await proxy_kafka_producer.stop_producer(app)


async def test_proxy_emit_event_sends_to_topic():
    """emit_event SHALL forward the payload to TOPIC_HTTP_TRAFFIC via producer.send()."""
    fake_producer = MagicMock()
    fake_producer.send = AsyncMock()
    app = SimpleNamespace(state=SimpleNamespace(producer=fake_producer))

    await proxy_kafka_producer.emit_event(app, {"hello": "world"})

    fake_producer.send.assert_awaited_once()
    args, kwargs = fake_producer.send.call_args
    assert args[0] == proxy_kafka_producer.TOPIC_HTTP_TRAFFIC
    assert kwargs.get("value") == {"hello": "world"}


async def test_consumer_start_redis_returns_client(monkeypatch):
    """consumer.start_redis SHALL build and return a Redis client."""
    fake_client = MagicMock()
    monkeypatch.setattr(
        consumer_redis_client.aioredis,
        "from_url",
        MagicMock(return_value=fake_client),
    )

    result = await consumer_redis_client.start_redis()

    assert result is fake_client


async def test_consumer_stop_redis_closes():
    """consumer.stop_redis SHALL aclose() the passed Redis client."""
    fake_client = MagicMock()
    fake_client.aclose = AsyncMock()

    await consumer_redis_client.stop_redis(fake_client)

    fake_client.aclose.assert_awaited_once()


async def test_consumer_service_start_wires_redis_and_kafka(monkeypatch):
    """ConsumerService.start SHALL create both Redis and Kafka clients."""
    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()
    fake_kafka = MagicMock()
    fake_kafka.start = AsyncMock()
    fake_kafka.stop = AsyncMock()

    monkeypatch.setattr(consumer_main, "start_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(consumer_main, "AIOKafkaConsumer", MagicMock(return_value=fake_kafka))

    service = consumer_main.ConsumerService()
    await service.start()

    assert service.redis is fake_redis
    assert service.consumer is fake_kafka
    fake_kafka.start.assert_awaited_once()


async def test_consumer_service_stop_logs_but_does_not_raise_on_error(monkeypatch):
    """stop() SHALL log warnings and continue when consumer/redis teardown raises."""
    service = consumer_main.ConsumerService()

    failing_consumer = MagicMock()
    failing_consumer.stop = AsyncMock(side_effect=Exception("kafka boom"))
    service.consumer = failing_consumer

    failing_redis = MagicMock()
    service.redis = failing_redis
    monkeypatch.setattr(
        consumer_main,
        "stop_redis",
        AsyncMock(side_effect=Exception("redis boom")),
    )

    # Must not raise
    await service.stop()
    assert service._stop_event.is_set()


async def test_consumer_service_run_invokes_start_process_stop(monkeypatch):
    """run() SHALL call start(), process_events(), then stop() in order."""
    service = consumer_main.ConsumerService()
    order: list[str] = []

    async def fake_start():
        order.append("start")

    async def fake_process():
        order.append("process")

    async def fake_stop():
        order.append("stop")

    monkeypatch.setattr(service, "start", fake_start)
    monkeypatch.setattr(service, "process_events", fake_process)
    monkeypatch.setattr(service, "stop", fake_stop)

    await service.run()

    assert order == ["start", "process", "stop"]


async def test_consumer_service_run_stops_even_on_process_failure(monkeypatch):
    """run() SHALL stop() even if process_events raises."""
    service = consumer_main.ConsumerService()
    stopped = {"v": False}

    async def fake_start():
        pass

    async def fake_process():
        raise RuntimeError("boom")

    async def fake_stop():
        stopped["v"] = True

    monkeypatch.setattr(service, "start", fake_start)
    monkeypatch.setattr(service, "process_events", fake_process)
    monkeypatch.setattr(service, "stop", fake_stop)

    with pytest.raises(RuntimeError, match="boom"):
        await service.run()
    assert stopped["v"] is True


async def test_consumer_commit_logs_warning_on_failure():
    """_commit SHALL swallow commit exceptions (next successful commit covers)."""
    service = consumer_main.ConsumerService()
    service.consumer = MagicMock()
    service.consumer.commit = AsyncMock(side_effect=Exception("rebalance"))

    # Must not raise
    await service._commit()
    service.consumer.commit.assert_awaited_once()


async def test_consumer_send_to_dlq_best_effort_on_redis_failure(monkeypatch):
    """_send_to_dlq SHALL log and continue when the Redis write fails."""
    service = consumer_main.ConsumerService()

    failing_pipe = MagicMock()
    failing_pipe.execute = AsyncMock(side_effect=Exception("redis gone"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=failing_pipe)
    cm.__aexit__ = AsyncMock(return_value=False)

    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=cm)
    service.redis = redis

    message = SimpleNamespace(
        topic="http.traffic",
        partition=0,
        offset=42,
        value={"method": "GET"},
    )

    # Must not raise
    await service._send_to_dlq(message, reason="test")


async def test_consumer_main_runs_service(monkeypatch):
    """main() SHALL construct a ConsumerService, install signal handlers, and run it."""

    class _FakeLoop:
        def __init__(self):
            self.handlers: dict = {}
            self.tasks: list = []

        def add_signal_handler(self, sig, cb):
            self.handlers[sig] = cb

        def create_task(self, coro):
            # Schedule but don't execute; close coroutine to avoid warnings.
            coro.close()
            self.tasks.append(coro)

    ran = {"v": False}

    class _FakeService:
        async def run(self):
            ran["v"] = True

        async def stop(self):
            pass

    fake_loop = _FakeLoop()

    with (
        patch.object(consumer_main, "ConsumerService", return_value=_FakeService()),
        patch.object(consumer_main.asyncio, "get_running_loop", return_value=fake_loop),
    ):
        await consumer_main.main()

    assert ran["v"] is True
    import signal

    assert signal.SIGTERM in fake_loop.handlers
    assert signal.SIGINT in fake_loop.handlers

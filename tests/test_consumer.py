from unittest.mock import AsyncMock, MagicMock

import pytest

from consumer.config import settings
from consumer.main import ConsumerService
from consumer.redis_client import update_stats


@pytest.fixture
def mock_pipeline():
    """Build a mocked redis.asyncio pipeline used as an async context manager."""
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=pipe)
    cm.__aexit__ = AsyncMock(return_value=False)
    return pipe, cm


@pytest.fixture
def mock_redis(mock_pipeline):
    _pipe, cm = mock_pipeline
    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=cm)
    return redis


@pytest.fixture
def sample_event() -> dict:
    return {
        "client_ip": "127.0.0.1",
        "method": "GET",
        "path": "/get",
        "status_code": 200,
        "response_time_ms": 42.5,
        "timestamp": "2026-05-10T00:00:00Z",
        "user_id": None,
    }


async def test_update_stats_calls_pipeline_with_six_ops(mock_redis, mock_pipeline, sample_event):
    """update_stats SHALL issue the six aggregation commands atomically."""
    pipe, _cm = mock_pipeline

    await update_stats(mock_redis, sample_event)

    mock_redis.pipeline.assert_called_once_with(transaction=True)
    pipe.incr.assert_any_call("stats:total_requests")
    pipe.hincrby.assert_any_call("stats:status_codes", "200", 1)
    pipe.hincrby.assert_any_call("stats:methods", "GET", 1)
    pipe.incrbyfloat.assert_called_once_with("stats:response_time_sum", 42.5)
    pipe.incr.assert_any_call("stats:response_time_count")
    pipe.zincrby.assert_called_once_with("stats:top_paths", 1, "/get")
    pipe.execute.assert_awaited_once()


async def test_update_stats_sets_ttl_on_all_keys(mock_redis, mock_pipeline, sample_event):
    """update_stats SHALL set TTL on all six stats keys for rolling window."""
    pipe, _cm = mock_pipeline

    await update_stats(mock_redis, sample_event)

    # Verify EXPIRE is called for all 6 stats keys with the configured TTL
    expected_ttl = settings.stats_ttl_seconds
    pipe.expire.assert_any_call("stats:total_requests", expected_ttl)
    pipe.expire.assert_any_call("stats:status_codes", expected_ttl)
    pipe.expire.assert_any_call("stats:methods", expected_ttl)
    pipe.expire.assert_any_call("stats:response_time_sum", expected_ttl)
    pipe.expire.assert_any_call("stats:response_time_count", expected_ttl)
    pipe.expire.assert_any_call("stats:top_paths", expected_ttl)
    assert pipe.expire.call_count == 6


async def test_update_stats_ttl_uses_configured_value(
    mock_redis, mock_pipeline, sample_event, monkeypatch
):
    """TTL SHALL be configurable via settings.stats_ttl_seconds."""
    pipe, _cm = mock_pipeline
    custom_ttl = 3600  # 1 hour
    monkeypatch.setattr(settings, "stats_ttl_seconds", custom_ttl)

    await update_stats(mock_redis, sample_event)

    # All EXPIRE calls should use the custom TTL
    for call in pipe.expire.call_args_list:
        assert call[0][1] == custom_ttl


async def test_update_stats_propagates_redis_errors(mock_redis, mock_pipeline, sample_event):
    """Redis failures SHALL propagate so the consumer can skip the offset commit."""
    pipe, _cm = mock_pipeline
    pipe.execute.side_effect = Exception("Redis connection failed")

    with pytest.raises(Exception, match="Redis connection failed"):
        await update_stats(mock_redis, sample_event)


class _FakeConsumer:
    """Minimal async-iterable stand-in for AIOKafkaConsumer."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.commit = AsyncMock()
        self.stop = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def _msg(value, offset: int = 0, partition: int = 0, topic: str = "http.traffic"):
    """Build a stand-in ConsumerRecord with primitive fields.

    We deliberately avoid MagicMock here so orjson.dumps works when the code
    under test writes the message to the DLQ.
    """
    m = MagicMock()
    m.value = value
    m.offset = offset
    m.partition = partition
    m.topic = topic
    return m


async def test_process_events_commits_on_success(mock_redis, sample_event):
    """A successful update_stats SHALL be followed by a manual offset commit."""
    service = ConsumerService()
    service.redis = mock_redis
    service.consumer = _FakeConsumer([_msg(sample_event, offset=1)])

    await service.process_events()

    service.consumer.commit.assert_awaited_once()


async def test_process_events_does_not_commit_on_failure(mock_redis, mock_pipeline, sample_event):
    """Transient update_stats failure SHALL NOT commit the offset (at-least-once).

    With `kafka_max_message_retries > 1`, a single failure increments the
    retry counter but does not trigger the DLQ path.
    """
    pipe, _cm = mock_pipeline
    pipe.execute.side_effect = Exception("Redis down")

    service = ConsumerService()
    service.redis = mock_redis
    service.consumer = _FakeConsumer([_msg(sample_event, offset=2)])

    await service.process_events()

    service.consumer.commit.assert_not_called()
    assert service._retry_counts[(0, 2)] == 1


async def test_process_events_routes_malformed_to_dlq(mock_redis, mock_pipeline):
    """Structurally invalid payloads SHALL go straight to the DLQ and commit."""
    pipe, _cm = mock_pipeline

    service = ConsumerService()
    service.redis = mock_redis
    service.consumer = _FakeConsumer([_msg(None, offset=5)])

    await service.process_events()

    # DLQ pipeline write: lpush + ltrim
    pipe.lpush.assert_called_once()
    pipe.ltrim.assert_called_once_with(
        settings.dead_letter_key, 0, settings.dead_letter_max_len - 1
    )
    service.consumer.commit.assert_awaited_once()


async def test_process_events_routes_missing_field_to_dlq(mock_redis, mock_pipeline):
    """Events missing required fields SHALL go to the DLQ."""
    pipe, _cm = mock_pipeline
    bad_event = {"method": "GET"}

    service = ConsumerService()
    service.redis = mock_redis
    service.consumer = _FakeConsumer([_msg(bad_event, offset=7)])

    await service.process_events()

    pipe.lpush.assert_called_once()
    service.consumer.commit.assert_awaited_once()


async def test_process_events_dlq_after_max_retries(
    mock_redis, mock_pipeline, sample_event, monkeypatch
):
    """After kafka_max_message_retries failures the message SHALL go to DLQ + commit."""
    pipe, _cm = mock_pipeline
    monkeypatch.setattr(settings, "kafka_max_message_retries", 2)
    call_count = {"n": 0}

    async def flaky_execute(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            raise Exception("Redis down")
        return []

    pipe.execute.side_effect = flaky_execute

    service = ConsumerService()
    service.redis = mock_redis
    offset = 10
    service.consumer = _FakeConsumer([_msg(sample_event, offset=offset) for _ in range(3)])

    await service.process_events()

    pipe.lpush.assert_called_once()
    service.consumer.commit.assert_awaited_once()
    assert (0, offset) not in service._retry_counts


def test_safe_deserialize_returns_none_on_bad_json():
    """_safe_deserialize SHALL return None for invalid JSON instead of raising."""
    assert ConsumerService._safe_deserialize(b"not json {") is None


def test_safe_deserialize_parses_valid_json():
    """_safe_deserialize SHALL parse valid JSON into a dict."""
    assert ConsumerService._safe_deserialize(b'{"a": 1}') == {"a": 1}


async def test_stop_is_idempotent(mock_redis):
    """Calling stop() twice SHALL NOT raise even after both paths run cleanup."""
    service = ConsumerService()
    service.redis = mock_redis
    fake = _FakeConsumer([])
    service.consumer = fake

    await service.stop()
    await service.stop()

    fake.stop.assert_awaited_once()

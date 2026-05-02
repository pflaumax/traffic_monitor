from unittest.mock import AsyncMock

import pytest

from proxy.rate_limiter import check_rate_limit


@pytest.fixture
def mock_redis():
    """Mock Redis client for rate limiter tests."""
    return AsyncMock()


async def test_rate_limiter_under_limit(mock_redis):
    """Test that requests under the limit are allowed."""
    mock_redis.incr.return_value = 50
    mock_redis.expire.return_value = True

    allowed = await check_rate_limit(mock_redis, "192.168.1.1", limit=100)

    assert allowed is True
    mock_redis.incr.assert_called_once_with("rl:192.168.1.1")


async def test_rate_limiter_at_limit(mock_redis):
    """Test that requests at exactly the limit are allowed."""
    mock_redis.incr.return_value = 100
    mock_redis.expire.return_value = True

    allowed = await check_rate_limit(mock_redis, "192.168.1.1", limit=100)

    assert allowed is True
    mock_redis.incr.assert_called_once_with("rl:192.168.1.1")


async def test_rate_limiter_over_limit(mock_redis):
    """Test that requests over the limit are blocked."""
    mock_redis.incr.return_value = 101
    mock_redis.expire.return_value = True

    allowed = await check_rate_limit(mock_redis, "192.168.1.1", limit=100)

    assert allowed is False
    mock_redis.incr.assert_called_once_with("rl:192.168.1.1")


async def test_rate_limiter_first_request_sets_expiry(mock_redis):
    """Test that the first request sets TTL on the key."""
    mock_redis.incr.return_value = 1
    mock_redis.expire.return_value = True

    allowed = await check_rate_limit(mock_redis, "192.168.1.1", limit=100)

    assert allowed is True
    mock_redis.incr.assert_called_once_with("rl:192.168.1.1")
    mock_redis.expire.assert_called_once_with("rl:192.168.1.1", 60)


async def test_rate_limiter_subsequent_request_no_expiry(mock_redis):
    """Test that subsequent requests don't reset TTL."""
    mock_redis.incr.return_value = 50
    mock_redis.expire.return_value = True

    allowed = await check_rate_limit(mock_redis, "192.168.1.1", limit=100)

    assert allowed is True
    mock_redis.incr.assert_called_once_with("rl:192.168.1.1")
    mock_redis.expire.assert_not_called()


async def test_rate_limiter_redis_failure_fails_open(mock_redis):
    """Test that Redis failures allow requests (fail open)."""
    mock_redis.incr.side_effect = Exception("Redis connection error")

    allowed = await check_rate_limit(mock_redis, "192.168.1.1", limit=100)

    assert allowed is True
    mock_redis.incr.assert_called_once_with("rl:192.168.1.1")


async def test_rate_limiter_different_ips_independent(mock_redis):
    """Test that different IPs have independent rate limits."""
    mock_redis.incr.return_value = 1

    await check_rate_limit(mock_redis, "192.168.1.1", limit=100)
    await check_rate_limit(mock_redis, "192.168.1.2", limit=100)

    assert mock_redis.incr.call_count == 2
    mock_redis.incr.assert_any_call("rl:192.168.1.1")
    mock_redis.incr.assert_any_call("rl:192.168.1.2")

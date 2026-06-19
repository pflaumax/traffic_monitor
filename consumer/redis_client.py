import logging
import time

import redis.asyncio as aioredis

from consumer.config import settings

logger = logging.getLogger(__name__)


async def start_redis() -> aioredis.Redis:
    """Initialize and return a Redis async client."""
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Redis client started")
    return redis


async def stop_redis(redis: aioredis.Redis) -> None:
    """Close the Redis client."""
    await redis.aclose()
    logger.info("Redis client closed")


async def update_stats(redis: aioredis.Redis, event: dict) -> None:
    """Update Redis stats from a traffic event with TTL refresh."""
    path = event["path"]
    status = str(event["status_code"])
    method = event["method"]
    response_time_ms = event["response_time_ms"]

    ttl = settings.stats_ttl_seconds
    timestamp = int(time.time())

    try:
        async with redis.pipeline(transaction=True) as pipe:
            # Update all stats atomically
            pipe.incr("stats:total_requests")
            pipe.hincrby("stats:status_codes", status, 1)
            pipe.hincrby("stats:methods", method, 1)
            pipe.incrbyfloat("stats:response_time_sum", response_time_ms)
            pipe.incr("stats:response_time_count")
            pipe.zincrby("stats:top_paths", 1, path)

            minute_timestamp = (timestamp // 60) * 60
            pipe.zincrby("stats:history", 1, str(minute_timestamp))

            # Refresh TTL on all stats keys (24h rolling window)
            pipe.expire("stats:total_requests", ttl)
            pipe.expire("stats:status_codes", ttl)
            pipe.expire("stats:methods", ttl)
            pipe.expire("stats:response_time_sum", ttl)
            pipe.expire("stats:response_time_count", ttl)
            pipe.expire("stats:top_paths", ttl)
            pipe.expire("stats:history", ttl)

            result = await pipe.execute()
            logger.debug("Pipeline executed: %s commands", len(result))
    except Exception as e:
        logger.error("Failed to update stats: %s", e, exc_info=True)
        raise

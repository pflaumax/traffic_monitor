import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


async def check_rate_limit(redis: Redis, client_ip: str, limit: int) -> bool:
    """Check if client has exceeded rate limit using sliding window counter"""
    key = f"rl:{client_ip}"

    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 60)
        return current <= limit

    except Exception as e:
        logger.error("Rate limiter error for %s: %s", client_ip, e)
        return True

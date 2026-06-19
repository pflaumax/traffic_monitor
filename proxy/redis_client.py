import logging

import redis.asyncio as aioredis

from proxy.config import settings

logger = logging.getLogger(__name__)


async def start_redis(app) -> None:
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Redis client started")


async def stop_redis(app) -> None:
    if hasattr(app.state, "redis"):
        await app.state.redis.aclose()
        logger.info("Redis client closed")

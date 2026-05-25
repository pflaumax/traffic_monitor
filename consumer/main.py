import asyncio
import logging
import signal
import sys

import orjson
import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import ConsumerStoppedError

from consumer.config import settings
from consumer.redis_client import start_redis, stop_redis, update_stats
from shared.topics import TOPIC_HTTP_TRAFFIC

logger = logging.getLogger(__name__)

# Fields that every TrafficEvent payload must contain for update_stats to work
_REQUIRED_EVENT_FIELDS = ("method", "path", "status_code", "response_time_ms")


class ConsumerService:
    """Kafka consumer service that processes traffic events and updates Redis stats."""

    def __init__(self) -> None:
        self.consumer: AIOKafkaConsumer | None = None
        self.redis: aioredis.Redis | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._retry_counts: dict[tuple[int, int], int] = {}

    async def start(self) -> None:
        """Initialize Kafka consumer and Redis client."""
        logger.info("Starting consumer service...")

        self.redis = await start_redis()

        self.consumer = AIOKafkaConsumer(
            TOPIC_HTTP_TRAFFIC,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_group_id,
            auto_offset_reset=settings.kafka_auto_offset_reset,
            enable_auto_commit=False,
            session_timeout_ms=settings.kafka_session_timeout_ms,
            heartbeat_interval_ms=settings.kafka_heartbeat_interval_ms,
            max_poll_interval_ms=settings.kafka_max_poll_interval_ms,
            fetch_min_bytes=settings.kafka_fetch_min_bytes,
            fetch_max_wait_ms=settings.kafka_fetch_max_wait_ms,
            max_partition_fetch_bytes=settings.kafka_max_partition_fetch_bytes,
            value_deserializer=self._safe_deserialize,
        )
        await self.consumer.start()
        logger.info("Kafka consumer started, subscribed to topic: %s", TOPIC_HTTP_TRAFFIC)

    async def stop(self) -> None:
        """Gracefully shutdown consumer and Redis client (idempotent)."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        logger.info("Stopping consumer service...")

        if self.consumer is not None:
            try:
                await self.consumer.stop()
                logger.info("Kafka consumer stopped")
            except Exception as e:
                logger.warning("Error while stopping Kafka consumer: %s", e)

        if self.redis is not None:
            try:
                await stop_redis(self.redis)
            except Exception as e:
                logger.warning("Error while closing Redis client: %s", e)

    @staticmethod
    def _safe_deserialize(raw: bytes) -> dict | None:
        """Deserialize a Kafka message value; return None on decode failure."""
        try:
            return orjson.loads(raw)
        except orjson.JSONDecodeError:
            return None

    def _is_structurally_valid(self, event: object) -> bool:
        """Return True if `event` has the minimum shape required by update_stats."""
        if not isinstance(event, dict):
            return False
        return all(field in event for field in _REQUIRED_EVENT_FIELDS)

    async def _send_to_dlq(self, message, reason: str) -> None:
        """Push a message to the Redis dead-letter list, capped at max length."""
        assert self.redis is not None
        payload = {
            "topic": message.topic,
            "partition": message.partition,
            "offset": message.offset,
            "reason": reason,
            "value": message.value,
        }
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpush(settings.dead_letter_key, orjson.dumps(payload))
                pipe.ltrim(settings.dead_letter_key, 0, settings.dead_letter_max_len - 1)
                await pipe.execute()
            logger.warning(
                "Sent message to DLQ (partition=%s, offset=%s, reason=%s)",
                message.partition,
                message.offset,
                reason,
            )
        except Exception as e:
            logger.error(
                "Failed to write DLQ entry (partition=%s, offset=%s, reason=%s): %s",
                message.partition,
                message.offset,
                reason,
                e,
            )

    async def _commit(self) -> None:
        """Commit the current consumer position, logging but not raising on failure."""
        assert self.consumer is not None
        try:
            await self.consumer.commit()
        except Exception as e:
            logger.warning("Offset commit failed: %s", e)

    async def process_events(self) -> None:
        """Main event processing loop with manual offset commit + DLQ fallback."""
        assert self.consumer is not None, "start() must be called before process_events()"
        assert self.redis is not None, "start() must be called before process_events()"
        logger.info("Starting event processing loop...")

        try:
            async for message in self.consumer:
                if self._stop_event.is_set():
                    break

                if not self._is_structurally_valid(message.value):
                    await self._send_to_dlq(message, reason="malformed_event")
                    await self._commit()
                    continue

                key = (message.partition, message.offset)
                try:
                    event = message.value
                    logger.debug(
                        "Processing event: %s %s -> %s (%sms)",
                        event["method"],
                        event["path"],
                        event["status_code"],
                        event["response_time_ms"],
                    )
                    await update_stats(self.redis, event)
                except Exception as e:
                    retries = self._retry_counts.get(key, 0) + 1
                    self._retry_counts[key] = retries
                    if retries > settings.kafka_max_message_retries:
                        logger.error(
                            "Exceeded max retries (%s) for partition=%s offset=%s; "
                            "routing to DLQ: %s",
                            settings.kafka_max_message_retries,
                            message.partition,
                            message.offset,
                            e,
                        )
                        await self._send_to_dlq(message, reason=f"max_retries: {e!r}")
                        await self._commit()
                        self._retry_counts.pop(key, None)
                    else:
                        logger.error(
                            "Transient error processing partition=%s offset=%s "
                            "(attempt %s/%s); skipping commit for redelivery: %s",
                            message.partition,
                            message.offset,
                            retries,
                            settings.kafka_max_message_retries,
                            e,
                            exc_info=True,
                        )
                    continue

                await self._commit()
                self._retry_counts.pop(key, None)

        except ConsumerStoppedError:
            logger.info("Kafka consumer iterator stopped (clean shutdown)")
        except asyncio.CancelledError:
            logger.info("Event processing cancelled")
            raise
        except Exception:
            logger.exception("Fatal error in event processing loop")
            raise

    async def run(self) -> None:
        """Run the consumer service."""
        await self.start()
        try:
            await self.process_events()
        finally:
            await self.stop()


async def main() -> None:
    """Main entry point for the consumer service."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    service = ConsumerService()
    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        loop.create_task(service.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await service.run()
    except Exception:
        logger.exception("Consumer service failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

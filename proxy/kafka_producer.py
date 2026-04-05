import logging

import orjson
from aiokafka import AIOKafkaProducer

from proxy.config import settings
from shared.topics import TOPIC_HTTP_TRAFFIC

logger = logging.getLogger(__name__)


def get_producer(app) -> AIOKafkaProducer:
    return app.state.producer


async def start_producer(app) -> None:
    app.state.producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: orjson.dumps(v),
        compression_type="gzip",
        linger_ms=5,
        request_timeout_ms=10000,
        retry_backoff_ms=200,
    )
    await app.state.producer.start()
    logger.info("Kafka producer started")


async def stop_producer(app) -> None:
    if hasattr(app.state, "producer"):
        await app.state.producer.stop()
        logger.info("Kafka producer stopped")


async def emit_event(app, event_dict: dict) -> None:
    producer = get_producer(app)
    await producer.send(TOPIC_HTTP_TRAFFIC, value=event_dict)

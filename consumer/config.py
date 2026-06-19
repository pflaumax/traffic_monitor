from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Consumer service configuration"""

    kafka_bootstrap_servers: str = "kafka:9092"
    redis_url: str = "redis://redis:6379"

    kafka_group_id: str = "traffic-consumer-group"
    kafka_auto_offset_reset: str = "earliest"

    # Session
    kafka_session_timeout_ms: int = 10_000
    kafka_heartbeat_interval_ms: int = 3_000
    kafka_max_poll_interval_ms: int = 300_000

    # Fetch batching
    kafka_fetch_min_bytes: int = 1
    kafka_fetch_max_wait_ms: int = 500
    kafka_max_partition_fetch_bytes: int = 1_048_576

    # Poison-pill handling
    kafka_max_message_retries: int = 3
    dead_letter_key: str = "stats:dead_letter"
    dead_letter_max_len: int = 1_000

    # Redis TTL for stats keys (rolling window)
    stats_ttl_seconds: int = 60 * 60 * 24  # 24h
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

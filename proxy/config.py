from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upstream_base_url: str = "https://httpbin.org"
    kafka_bootstrap_servers: str = "kafka:9092"
    redis_url: str = "redis://redis:6379"
    rate_limit_per_minute: int = 100

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

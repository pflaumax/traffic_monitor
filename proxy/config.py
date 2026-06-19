from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "change-me-in-production-use-a-long-random-secret"
_MIN_SECRET_LEN = 32


class Settings(BaseSettings):
    upstream_base_url: str = "https://httpbin.org"
    kafka_bootstrap_servers: str = "kafka:9092"
    redis_url: str = "redis://redis:6379"
    rate_limit_per_minute: int = 100

    jwt_secret_key: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    admin_username: str = "admin"
    admin_password: str = "admin"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _check_secrets(self) -> Self:
        if self.jwt_secret_key == _DEFAULT_SECRET or len(self.jwt_secret_key) < _MIN_SECRET_LEN:
            raise ValueError(
                "JWT_SECRET_KEY is insecure. "
                f"Set a random secret of at least {_MIN_SECRET_LEN} characters in your .env file. "
                'Generate one with:  python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
        return self


settings = Settings()

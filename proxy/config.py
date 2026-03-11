from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upstream_base_url: str = "https://httpbin.org"

    model_config = {"env_file": ".env"}


settings = Settings()

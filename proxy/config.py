from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upstream_base_url: str = "https://httpbin.org"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

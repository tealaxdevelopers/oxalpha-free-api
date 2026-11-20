from functools import lru_cache
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    app_name: str = "oxalpha-gateway"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server binding
    host: str = "0.0.0.0"
    port: int = 8000

    # API Keys for client gateway authentication (empty = open/dev bypass)
    api_keys: List[str] = Field(default_factory=list)

    @field_validator("api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [k.strip() for k in v.split(",") if k.strip()]
        return v or []

    # OxAlpha Upstream Configuration
    oxalpha_base_url: str = "https://oxalpha.com"
    oxalpha_model: str = "z-ai/glm-5.3-flash"
    oxalpha_turnstile_token: Optional[str] = None
    gateway_model_name: str = "oxalpha"
    gateway_model_aliases: List[str] = Field(
        default_factory=lambda: ["oxalpha", "ox-alpha", "z-ai/glm-5.3-flash"]
    )

    # HTTP Client & Resilience
    upstream_timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 15.0
    max_concurrent_requests: int = 10
    rate_limit_per_minute: int = 30
    max_retries: int = 3
    backoff_factor: float = 0.5
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_api_key: SecretStr
    database_url: str = "postgresql+psycopg://devops:devops@localhost:5432/devops_platform"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "devops_knowledge"
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:3b"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "http://localhost:11434/v1"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

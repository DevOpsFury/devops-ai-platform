from functools import lru_cache

from pydantic import Field, SecretStr
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
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=32768)
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    kubernetes_namespace: str = "devops-lab"
    kubernetes_kubeconfig: str | None = Field(
        default=None,
        validation_alias="KUBECONFIG",
    )
    kubernetes_logs_tail_lines: int = Field(default=100, ge=1, le=500)
    kubernetes_max_pods_with_logs: int = Field(default=20, ge=1, le=100)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

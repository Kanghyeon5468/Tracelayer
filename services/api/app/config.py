from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "tracelayer"
    log_level: str = "INFO"
    use_mock_data: bool = True
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    firestore_database: str = "(default)"
    bigquery_dataset: str = "fraud_investigations"
    pubsub_topic_investigations: str = "tracelayer-investigations"
    pubsub_topic_approvals: str = "tracelayer-approvals"
    security_mode: str = "permissive"
    demo_analyst_api_key: str = "local-demo-key"
    allowed_origins: str = "http://localhost:8080,http://localhost:5173,file://"
    audit_ledger_path: str | None = None
    memory_bank_path: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

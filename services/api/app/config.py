from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "tracelayer"
    log_level: str = "INFO"
    use_mock_data: bool = True
    ai_provider: str = "mock"
    adk_enabled: bool = True
    adk_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    firestore_database: str = "(default)"
    firestore_case_collection: str = "tracelayer_cases"
    firestore_job_collection: str = "tracelayer_investigation_jobs"
    firestore_policy_collection: str = "tracelayer_policy_settings"
    bigquery_dataset: str = "fraud_investigations"
    bigquery_transactions_table: str = (
        "project-6ecbea1e-e0c3-4325-a63.fraud_investigations.transactions"
    )
    network_search_backend: str = "auto"
    network_search_limit: int = 50
    network_search_timeout_seconds: int = 3
    pubsub_topic_investigations: str = "tracelayer-investigations"
    pubsub_topic_approvals: str = "tracelayer-approvals"
    security_mode: str = "permissive"
    demo_analyst_api_key: str = "local-demo-key"
    allowed_origins: str = "http://localhost:8080,http://localhost:5173,file://"
    audit_ledger_path: str | None = None
    memory_backend: str = "local"
    memory_bank_path: str | None = None
    investigation_job_path: str | None = None
    risk_policy_path: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def resolved_ai_provider(self) -> str:
        if self.ai_provider != "auto":
            return self.ai_provider
        if self.gemini_api_key:
            return "gemini_api"
        if self.google_cloud_project:
            return "vertex_ai"
        return "mock"

    @property
    def resolved_adk_model(self) -> str:
        return self.adk_model or self.gemini_model


@lru_cache
def get_settings() -> Settings:
    return Settings()

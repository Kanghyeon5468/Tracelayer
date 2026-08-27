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
    gemini_model: str = "gemini-3.5-flash"
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    public_service_url: str | None = None
    model_armor_backend: str = "auto"
    model_armor_project: str | None = None
    model_armor_location: str = "us-central1"
    model_armor_template_id: str | None = None
    model_armor_fail_closed: bool = False
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
    pubsub_backend: str = "auto"
    pubsub_topic_investigations: str = "tracelayer-investigations"
    pubsub_topic_approvals: str = "tracelayer-approvals"
    pubsub_push_subscription: str = "tracelayer-investigation-worker"
    pubsub_push_invoker_service_account: str | None = None
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

    @property
    def resolved_pubsub_backend(self) -> str:
        if self.pubsub_backend != "auto":
            return self.pubsub_backend
        if self.app_env == "cloud" and self.google_cloud_project:
            return "google"
        return "local"

    @property
    def resolved_model_armor_project(self) -> str | None:
        return self.model_armor_project or self.google_cloud_project

    @property
    def resolved_model_armor_backend(self) -> str:
        if self.model_armor_backend != "auto":
            return self.model_armor_backend
        if self.resolved_model_armor_project and self.model_armor_template_id:
            return "google"
        return "local"

    @property
    def model_armor_template_name(self) -> str | None:
        project = self.resolved_model_armor_project
        if not project or not self.model_armor_template_id:
            return None
        return (
            f"projects/{project}/locations/{self.model_armor_location}/"
            f"templates/{self.model_armor_template_id}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

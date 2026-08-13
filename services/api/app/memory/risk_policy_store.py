from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.models import RiskPolicy


class LocalRiskPolicyStore:
    """Stores the active risk threshold policy for local demos."""

    def __init__(self, settings: Settings, path: Path | None = None) -> None:
        self.path = path or self._resolve_path(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_policy(self) -> RiskPolicy:
        if not self.path.exists():
            return RiskPolicy()
        return RiskPolicy.model_validate(json.loads(self.path.read_text(encoding="utf-8")))

    def save_policy(self, policy: RiskPolicy) -> RiskPolicy:
        payload = json.loads(policy.model_dump_json())
        self.path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        return policy

    @staticmethod
    def _resolve_path(settings: Settings) -> Path:
        if settings.risk_policy_path:
            return Path(settings.risk_policy_path).resolve()

        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data"
            if candidate.exists():
                return candidate / "memory" / "risk-policy.json"

        return Path("/tmp/tracelayer-risk-policy.json")


class FirestoreRiskPolicyStore:
    """Firestore-backed risk threshold policy store for deployed demos."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not settings.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore risk policy.")

        self.settings = settings
        self.client = client or self._build_client(settings)
        self.collection_name = settings.firestore_policy_collection

    def load_policy(self) -> RiskPolicy:
        document = self.client.collection(self.collection_name).document("default").get()
        if not document.exists:
            return RiskPolicy()
        payload = document.to_dict() or {}
        return RiskPolicy.model_validate(payload)

    def save_policy(self, policy: RiskPolicy) -> RiskPolicy:
        payload = json.loads(policy.model_dump_json())
        self.client.collection(self.collection_name).document(policy.policy_id).set(payload)
        return policy

    @staticmethod
    def _build_client(settings: Settings):
        try:
            from google.cloud import firestore
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-firestore is required for Firestore risk policy storage. "
                "Install the cloud extra."
            ) from exc

        return firestore.Client(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )


def create_risk_policy_store(
    settings: Settings,
) -> LocalRiskPolicyStore | FirestoreRiskPolicyStore:
    if settings.memory_backend == "firestore":
        return FirestoreRiskPolicyStore(settings)
    if settings.memory_backend == "local":
        return LocalRiskPolicyStore(settings)
    if settings.memory_backend == "auto":
        if settings.app_env == "cloud":
            return FirestoreRiskPolicyStore(settings)
        return LocalRiskPolicyStore(settings)
    raise ValueError(f"Unsupported MEMORY_BACKEND: {settings.memory_backend}")

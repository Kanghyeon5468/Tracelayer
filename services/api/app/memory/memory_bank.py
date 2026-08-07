from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.domain.models import InvestigationCase


class MemoryBank:
    """Append-only local memory bank for cross-session case context."""

    def __init__(self, settings: Settings, memory_path: Path | None = None) -> None:
        self.memory_path = memory_path or self._resolve_memory_path(settings)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)

    def save_case(self, case: InvestigationCase) -> str:
        snapshot_id = f"mem-{uuid4().hex}"
        payload = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(UTC).isoformat(),
            "case": json.loads(case.model_dump_json()),
        }
        with self.memory_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, sort_keys=True) + "\n")
        return snapshot_id

    def load_case(self, case_id: str) -> InvestigationCase | None:
        latest: dict | None = None
        if not self.memory_path.exists():
            return None

        with self.memory_path.open("r", encoding="utf-8") as file:
            for line in file:
                payload = json.loads(line)
                if payload["case"]["case_id"] == case_id:
                    latest = payload

        if latest is None:
            return None

        case = InvestigationCase.model_validate(latest["case"])
        return case.model_copy(update={"memory_snapshot_id": latest["snapshot_id"]})

    @staticmethod
    def _resolve_memory_path(settings: Settings) -> Path:
        if settings.memory_bank_path:
            return Path(settings.memory_bank_path).resolve()

        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data"
            if candidate.exists():
                return candidate / "memory" / "case-memory.jsonl"

        return Path("/tmp/tracelayer-case-memory.jsonl")


class FirestoreMemoryBank:
    """Firestore-backed memory bank for deployed cross-session case state."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not settings.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore memory.")

        self.settings = settings
        self.client = client or self._build_client(settings)
        self.collection_name = settings.firestore_case_collection

    def save_case(self, case: InvestigationCase) -> str:
        snapshot_id = f"mem-{uuid4().hex}"
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "snapshot_id": snapshot_id,
            "case_id": case.case_id,
            "created_at": now,
            "case": json.loads(case.model_dump_json()),
        }

        case_ref = self.client.collection(self.collection_name).document(case.case_id)
        snapshot_ref = case_ref.collection("snapshots").document(snapshot_id)
        snapshot_ref.set(payload)
        case_ref.set(
            {
                "case_id": case.case_id,
                "latest_snapshot_id": snapshot_id,
                "updated_at": now,
                "status": str(case.status),
                "priority": str(case.priority),
                "risk_score": case.risk_score,
                "trigger_transaction_id": case.trigger_transaction_id,
                "customer_id": case.customer_id,
                "case": payload["case"],
            },
            merge=True,
        )
        return snapshot_id

    def load_case(self, case_id: str) -> InvestigationCase | None:
        case_ref = self.client.collection(self.collection_name).document(case_id)
        document = case_ref.get()
        if not document.exists:
            return None

        payload = document.to_dict() or {}
        case_payload = payload.get("case")
        snapshot_id = payload.get("latest_snapshot_id")
        if not case_payload:
            return None

        case = InvestigationCase.model_validate(case_payload)
        return case.model_copy(update={"memory_snapshot_id": snapshot_id})

    @staticmethod
    def _build_client(settings: Settings):
        try:
            from google.cloud import firestore
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-firestore is required for MEMORY_BACKEND=firestore. "
                "Install the cloud extra."
            ) from exc

        return firestore.Client(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )


def create_memory_bank(settings: Settings) -> MemoryBank | FirestoreMemoryBank:
    if settings.memory_backend == "firestore":
        return FirestoreMemoryBank(settings)
    if settings.memory_backend == "local":
        return MemoryBank(settings)
    if settings.memory_backend == "auto":
        if settings.app_env == "cloud":
            return FirestoreMemoryBank(settings)
        return MemoryBank(settings)
    raise ValueError(f"Unsupported MEMORY_BACKEND: {settings.memory_backend}")

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.models import InvestigationJob


class LocalInvestigationJobStore:
    """Append-only job store for async demo state."""

    def __init__(self, settings: Settings, path: Path | None = None) -> None:
        self.path = path or self._resolve_path(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_job(self, job: InvestigationJob) -> InvestigationJob:
        payload = json.loads(job.model_dump_json())
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, sort_keys=True) + "\n")
        return job

    def load_job(self, job_id: str) -> InvestigationJob | None:
        latest: dict[str, Any] | None = None
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                payload = json.loads(line)
                if payload["job_id"] == job_id:
                    latest = payload
        return InvestigationJob.model_validate(latest) if latest else None

    @staticmethod
    def _resolve_path(settings: Settings) -> Path:
        if settings.investigation_job_path:
            return Path(settings.investigation_job_path).resolve()

        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data"
            if candidate.exists():
                return candidate / "memory" / "investigation-jobs.jsonl"

        return Path("/tmp/tracelayer-investigation-jobs.jsonl")


class FirestoreInvestigationJobStore:
    """Firestore-backed job store for Cloud Run async demo state."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not settings.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore job state.")
        self.settings = settings
        self.client = client or self._build_client(settings)
        self.collection_name = settings.firestore_job_collection

    def save_job(self, job: InvestigationJob) -> InvestigationJob:
        self.client.collection(self.collection_name).document(job.job_id).set(
            json.loads(job.model_dump_json()),
            merge=True,
        )
        return job

    def load_job(self, job_id: str) -> InvestigationJob | None:
        document = self.client.collection(self.collection_name).document(job_id).get()
        if not document.exists:
            return None
        return InvestigationJob.model_validate(document.to_dict() or {})

    @staticmethod
    def _build_client(settings: Settings):
        from google.cloud import firestore

        return firestore.Client(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )


def touch_job(job: InvestigationJob, **updates: Any) -> InvestigationJob:
    return job.model_copy(update={**updates, "updated_at": datetime.now(UTC)})


def create_job_store(settings: Settings) -> LocalInvestigationJobStore | FirestoreInvestigationJobStore:
    if settings.memory_backend == "firestore" or (
        settings.memory_backend == "auto" and settings.app_env == "cloud"
    ):
        return FirestoreInvestigationJobStore(settings)
    return LocalInvestigationJobStore(settings)

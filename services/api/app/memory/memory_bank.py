from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
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

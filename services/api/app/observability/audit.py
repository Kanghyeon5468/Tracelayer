from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.domain.models import AuditEvent, RequestContext


GENESIS_HASH = "0" * 64


class AuditLedger:
    """Append-only JSONL audit ledger with a simple hash chain."""

    def __init__(self, settings: Settings, ledger_path: Path | None = None) -> None:
        self.ledger_path = ledger_path or self._resolve_ledger_path(settings)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        request: RequestContext,
        action: str,
        resource: str,
        decision: str,
        reason: str,
        case_id: str | None = None,
        actor_type: str = "human",
        metadata: dict | None = None,
    ) -> AuditEvent:
        previous_hash = self.latest_hash()
        event_payload = {
            "event_id": f"audit-{uuid4().hex}",
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "case_id": case_id,
            "actor_id": request.actor_id,
            "actor_type": actor_type,
            "action": action,
            "resource": resource,
            "decision": decision,
            "reason": reason,
            "metadata": metadata or {},
            "previous_hash": previous_hash,
        }
        event_hash = self._hash_payload(event_payload)
        event = AuditEvent.model_validate(event_payload | {"event_hash": event_hash})

        with self.ledger_path.open("a", encoding="utf-8") as file:
            file.write(event.model_dump_json() + "\n")

        return event

    def latest_hash(self) -> str:
        if not self.ledger_path.exists():
            return GENESIS_HASH

        last_line = ""
        with self.ledger_path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    last_line = line

        if not last_line:
            return GENESIS_HASH

        return json.loads(last_line)["event_hash"]

    def read_case_events(self, case_id: str) -> list[AuditEvent]:
        if not self.ledger_path.exists():
            return []

        events: list[AuditEvent] = []
        with self.ledger_path.open("r", encoding="utf-8") as file:
            for line in file:
                payload = json.loads(line)
                if payload.get("case_id") == case_id:
                    events.append(AuditEvent.model_validate(payload))
        return events

    def verify_chain(self) -> bool:
        previous_hash = GENESIS_HASH
        if not self.ledger_path.exists():
            return True

        with self.ledger_path.open("r", encoding="utf-8") as file:
            for line in file:
                payload = json.loads(line)
                event_hash = payload.pop("event_hash")
                if payload["previous_hash"] != previous_hash:
                    return False
                if not self._matches_hash(payload, event_hash):
                    return False
                previous_hash = event_hash
        return True

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _matches_hash(self, payload: dict, event_hash: str) -> bool:
        if self._hash_payload(payload) == event_hash:
            return True

        legacy_payload = dict(payload)
        timestamp = legacy_payload.get("timestamp")
        if isinstance(timestamp, str) and timestamp.endswith("Z"):
            legacy_payload["timestamp"] = timestamp.removesuffix("Z") + "+00:00"
            return self._hash_payload(legacy_payload) == event_hash

        return False

    @staticmethod
    def _resolve_ledger_path(settings: Settings) -> Path:
        if settings.audit_ledger_path:
            return Path(settings.audit_ledger_path).resolve()

        for parent in Path(__file__).resolve().parents:
            candidate = parent / "data"
            if candidate.exists():
                return candidate / "audit" / "audit-ledger.jsonl"

        return Path("/tmp/tracelayer-audit-ledger.jsonl")

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.domain.models import RequestContext


class CloudTraceLogger:
    """Writes Cloud Logging-compatible structured JSON to stdout."""

    def emit(
        self,
        *,
        message: str,
        severity: str = "INFO",
        request: RequestContext | None = None,
        case_id: str | None = None,
        agent_id: str | None = None,
        agent_version: str | None = None,
        tool: str | None = None,
        latency_ms: float | None = None,
        status: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "severity": severity,
            "message": message,
            "component": "tracelayer",
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if request:
            payload["request_id"] = request.request_id
            payload["actor_id"] = request.actor_id
            payload["trace_id"] = request.trace_id
            if request.cloud_trace:
                payload["logging.googleapis.com/trace"] = request.cloud_trace
        if case_id:
            payload["case_id"] = case_id
        if agent_id:
            payload["agent_id"] = agent_id
        if agent_version:
            payload["agent_version"] = agent_version
        if tool:
            payload["tool"] = tool
        if latency_ms is not None:
            payload["latency_ms"] = round(latency_ms, 2)
        if metadata:
            payload.update(metadata)

        print(json.dumps(payload, sort_keys=True), flush=True)

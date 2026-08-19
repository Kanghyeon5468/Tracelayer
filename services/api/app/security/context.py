from __future__ import annotations

from uuid import uuid4

from app.config import get_settings
from app.domain.models import ActorRole, RequestContext


def build_service_context(
    actor_id: str = "local-service-runtime",
    trace_id: str | None = None,
) -> RequestContext:
    settings = get_settings()
    resolved_trace_id = trace_id or uuid4().hex
    return RequestContext(
        actor_id=actor_id,
        role=ActorRole.SERVICE,
        scopes=["*"],
        request_id=f"req-{uuid4().hex}",
        trace_id=resolved_trace_id,
        cloud_trace=(
            f"projects/{settings.google_cloud_project}/traces/{resolved_trace_id}"
            if settings.google_cloud_project
            else None
        ),
    )

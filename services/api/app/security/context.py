from __future__ import annotations

from uuid import uuid4

from app.domain.models import ActorRole, RequestContext


def build_service_context(actor_id: str = "local-service-runtime") -> RequestContext:
    return RequestContext(
        actor_id=actor_id,
        role=ActorRole.SERVICE,
        scopes=["*"],
        request_id=f"req-{uuid4().hex}",
    )

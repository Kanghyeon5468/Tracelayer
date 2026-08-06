from __future__ import annotations

from uuid import uuid4

from app.domain.models import ActorRole, RequestContext


def build_service_context() -> RequestContext:
    return RequestContext(
        actor_id="local-service-runtime",
        role=ActorRole.SERVICE,
        scopes=["*"],
        request_id=f"req-{uuid4().hex}",
    )

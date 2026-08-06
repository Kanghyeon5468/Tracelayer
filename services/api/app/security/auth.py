from __future__ import annotations

from uuid import uuid4

from fastapi import Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.domain.models import ActorRole, RequestContext


def get_request_context(
    request: Request,
    x_tracelayer_user: str | None = Header(default=None),
    x_tracelayer_role: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> RequestContext:
    settings = get_settings()
    role = _parse_role(x_tracelayer_role)

    if settings.security_mode == "enforcing":
        _require_api_key(settings, x_api_key)

    return RequestContext(
        actor_id=x_tracelayer_user or "local-demo-analyst",
        role=role,
        scopes=[],
        request_id=f"req-{uuid4().hex}",
        source_ip=request.client.host if request.client else None,
    )


def _parse_role(value: str | None) -> ActorRole:
    if not value:
        return ActorRole.SUPERVISOR
    try:
        return ActorRole(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown TraceLayer role: {value}",
        ) from exc


def _require_api_key(settings: Settings, api_key: str | None) -> None:
    if api_key != settings.demo_analyst_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
        )

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
    trace_id = _trace_id_from_header(request.headers.get("X-Cloud-Trace-Context"))

    if settings.security_mode == "enforcing":
        _require_api_key(settings, x_api_key)

    return RequestContext(
        actor_id=x_tracelayer_user or "local-demo-analyst",
        role=role,
        scopes=[],
        request_id=f"req-{uuid4().hex}",
        trace_id=trace_id,
        cloud_trace=(
            f"projects/{settings.google_cloud_project}/traces/{trace_id}"
            if trace_id and settings.google_cloud_project
            else None
        ),
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


def _trace_id_from_header(header: str | None) -> str | None:
    if not header:
        return None
    trace_id = header.split("/", maxsplit=1)[0].strip()
    return trace_id or None

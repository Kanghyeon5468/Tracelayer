from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.registry import AgentRegistry
from app.config import get_settings
from app.domain.models import (
    AgentIdentity,
    ApprovalDecisionRequest,
    AuditEvent,
    InvestigationCase,
    InvestigationRequest,
    RequestContext,
)
from app.fleet import FraudInvestigationFleet
from app.observability.audit import AuditLedger
from app.security.auth import get_request_context
from app.security.policy import PolicyEngine
from app.security.redaction import redact_case_for_role

settings = get_settings()
app = FastAPI(
    title="TraceLayer API",
    description="Fraud investigation agent fleet demo for Gemini and Google Cloud.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.security_mode == "permissive" else settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/runtime/config")
def runtime_config() -> dict[str, str | bool | None]:
    return {
        "app": settings.app_name,
        "env": settings.app_env,
        "security_mode": settings.security_mode,
        "ai_provider": settings.resolved_ai_provider,
        "gemini_model": settings.gemini_model,
        "google_cloud_project": settings.google_cloud_project,
        "google_cloud_location": settings.google_cloud_location,
        "secrets_in_browser": False,
    }


@app.get("/agents", response_model=list[AgentIdentity])
def list_agents(request: RequestContext = Depends(get_request_context)) -> list[AgentIdentity]:
    _require_scope(request, "agents.read")
    return AgentRegistry().list_agents()


@app.post("/cases/demo", response_model=InvestigationCase)
def run_demo_case(request: RequestContext = Depends(get_request_context)) -> InvestigationCase:
    case = _run_or_raise(lambda: FraudInvestigationFleet(settings).investigate("tx-9001", request))
    return redact_case_for_role(case, request.role)


@app.post("/cases/investigate", response_model=InvestigationCase)
def investigate_case(
    investigation: InvestigationRequest,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    case = _run_or_raise(
        lambda: FraudInvestigationFleet(settings).investigate(
            investigation.transaction_id,
            request,
        )
    )
    return redact_case_for_role(case, request.role)


@app.get("/cases/{case_id}", response_model=InvestigationCase)
def get_case(
    case_id: str,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    case = _run_or_raise(lambda: FraudInvestigationFleet(settings).get_case(case_id, request))
    return redact_case_for_role(case, request.role)


@app.post("/cases/{case_id}/approval", response_model=InvestigationCase)
def decide_approval(
    case_id: str,
    decision: ApprovalDecisionRequest,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    case = _run_or_raise(
        lambda: FraudInvestigationFleet(settings).decide_approval(case_id, decision, request)
    )
    return redact_case_for_role(case, request.role)


@app.get("/cases/{case_id}/audit", response_model=list[AuditEvent])
def get_case_audit(
    case_id: str,
    request: RequestContext = Depends(get_request_context),
) -> list[AuditEvent]:
    _require_scope(request, "audit.read")
    return AuditLedger(settings).read_case_events(case_id)


@app.get("/audit/verify")
def verify_audit_chain(request: RequestContext = Depends(get_request_context)) -> dict[str, bool]:
    _require_scope(request, "audit.read")
    return {"valid": AuditLedger(settings).verify_chain()}


def _require_scope(request: RequestContext, scope: str) -> None:
    decision = PolicyEngine().actor_can(request, scope)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


def _run_or_raise(handler):
    try:
        return handler()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

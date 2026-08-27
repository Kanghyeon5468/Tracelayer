from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.adk_runtime import AdkAgentRuntime
from app.agents.registry import AgentRegistry
from app.config import get_settings
from app.connectors.repository import InvestigationRepository
from app.connectors.scenario_builder import SyntheticScenarioBuilder
from app.domain.models import (
    AgentIdentity,
    ApprovalDecisionRequest,
    ApprovalLogEntry,
    AuditEvent,
    InvestigationCase,
    InvestigationJob,
    InvestigationRequest,
    LongRunningAdvanceRequest,
    MissingDataRequest,
    PendingApprovalSummary,
    PubSubPushEnvelope,
    RequestContext,
    RegisteredAgentInvokeRequest,
    RiskPolicy,
    ScenarioInvestigationRequest,
)
from app.fleet import FraudInvestigationFleet
from app.observability.audit import AuditLedger
from app.security.auth import get_request_context
from app.security.policy import PolicyEngine
from app.security.redaction import redact_case_for_role
from app.security.context import build_service_context


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


def _find_dashboard_path() -> str | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "apps" / "dashboard"
        if candidate.exists():
            return str(candidate)
    return None


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

dashboard_path = _find_dashboard_path()
if dashboard_path:
    app.mount("/console", NoCacheStaticFiles(directory=dashboard_path, html=True), name="console")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/runtime/config")
def runtime_config() -> dict[str, str | bool | None]:
    adk = AdkAgentRuntime(settings).runtime_config()
    return {
        "app": settings.app_name,
        "env": settings.app_env,
        "security_mode": settings.security_mode,
        "ai_provider": settings.resolved_ai_provider,
        "gemini_model": settings.gemini_model,
        "adk_enabled": adk["enabled"],
        "adk_available": adk["available"],
        "adk_framework": adk["framework"],
        "adk_model": adk["model"],
        "adk_runner_available": adk["runner_available"],
        "adk_error": adk["error"],
        "adk_runner_error": adk["runner_error"],
        "pubsub_backend": settings.resolved_pubsub_backend,
        "pubsub_topic_investigations": settings.pubsub_topic_investigations,
        "pubsub_push_subscription": settings.pubsub_push_subscription,
        "model_armor_backend": settings.resolved_model_armor_backend,
        "model_armor_location": settings.model_armor_location,
        "model_armor_template_configured": bool(settings.model_armor_template_name),
        "google_cloud_project": settings.google_cloud_project,
        "google_cloud_location": settings.google_cloud_location,
        "public_service_url": settings.public_service_url,
        "triage_agent_engine_resource": settings.triage_agent_engine_resource,
        "triage_agent_runtime_principal_configured": bool(
            settings.triage_agent_runtime_principal
        ),
        "agent_registry_location": (
            settings.google_cloud_location
            if settings.google_cloud_location != "global"
            else "us-central1"
        ),
        "secrets_in_browser": False,
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> RedirectResponse:
    return RedirectResponse(url="/console/index.html")


@app.get("/admin", include_in_schema=False)
def admin_console() -> RedirectResponse:
    return RedirectResponse(url="/console/admin.html")


@app.get("/demo", include_in_schema=False)
def prompt_demo_console() -> RedirectResponse:
    return RedirectResponse(url="/console/demo.html")


@app.get("/agents", response_model=list[AgentIdentity])
def list_agents(
    q: str = Query(default=""),
    request: RequestContext = Depends(get_request_context),
) -> list[AgentIdentity]:
    _require_scope(request, "agents.read")
    registry = _agent_registry()
    return registry.search(q) if q else registry.list_agents()


@app.get("/agents/{agent_id}", response_model=AgentIdentity)
def get_agent(
    agent_id: str,
    request: RequestContext = Depends(get_request_context),
) -> AgentIdentity:
    _require_scope(request, "agents.read")
    return _agent_registry().get(agent_id)


@app.get("/a2a/{agent_id}/agent-card.json")
def get_agent_card(agent_id: str, request: Request) -> dict[str, Any]:
    return _agent_registry(request).a2a_agent_card(agent_id)


@app.get("/agents/{agent_id}/agent-card.json")
def get_agent_card_alias(agent_id: str, request: Request) -> dict[str, Any]:
    return _agent_registry(request).a2a_agent_card(agent_id)


@app.post("/agents/{agent_id}/invoke")
def invoke_registered_agent(
    agent_id: str,
    invocation: RegisteredAgentInvokeRequest | None = None,
    request: RequestContext = Depends(get_request_context),
) -> dict[str, Any]:
    _require_scope(request, "cases.investigate")
    agent = _agent_registry().get(agent_id)
    invocation = invocation or RegisteredAgentInvokeRequest()
    case = None
    if agent_id == "triage-agent" and invocation.include_case:
        case = _run_or_raise(
            lambda: FraudInvestigationFleet(settings).investigate(
                invocation.transaction_id,
                request,
            )
        )
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "status": "registered_endpoint_ready",
        "message": (
            "This endpoint is the Agent Registry invocation surface. "
            "TraceLayer runs the actual tool through the internal AgentGateway and ADK Runner."
        ),
        "transaction_id": invocation.transaction_id,
        "case_id": case.case_id if case else None,
        "risk_score": case.risk_score if case else None,
        "priority": case.priority if case else None,
        "allowed_tools": agent.allowed_tools,
        "managed_gateway_policy": agent.managed_gateway_policy,
        "identity_provider": agent.identity_provider,
        "identity_status": agent.identity_status,
        "runtime_resource": agent.runtime_resource,
        "agent_principal": agent.agent_principal,
    }


@app.get("/agent-registry/bootstrap")
def agent_registry_bootstrap(request: Request) -> dict[str, Any]:
    return _agent_registry(request).registry_bootstrap_manifest()


@app.post("/cases/demo", response_model=InvestigationCase)
def run_demo_case(request: RequestContext = Depends(get_request_context)) -> InvestigationCase:
    case = _run_or_raise(lambda: FraudInvestigationFleet(settings).investigate_random_demo(request))
    return redact_case_for_role(case, request.role)


@app.post("/cases/demo/async", response_model=InvestigationJob)
def enqueue_demo_case(
    request: RequestContext = Depends(get_request_context),
) -> InvestigationJob:
    return _run_or_raise(lambda: FraudInvestigationFleet(settings).enqueue_random_demo(request))


@app.post("/cases/long-running-demo", response_model=InvestigationCase)
def start_long_running_demo(
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    case = _run_or_raise(lambda: FraudInvestigationFleet(settings).start_long_running_demo(request))
    return redact_case_for_role(case, request.role)


@app.post("/cases/{case_id}/long-running/advance", response_model=InvestigationCase)
def advance_long_running_demo(
    case_id: str,
    advance: LongRunningAdvanceRequest,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    case = _run_or_raise(
        lambda: FraudInvestigationFleet(settings).advance_long_running_demo(
            case_id,
            advance,
            request,
        )
    )
    return redact_case_for_role(case, request.role)


@app.post("/cases/scenario", response_model=InvestigationCase)
def run_prompt_scenario(
    scenario: ScenarioInvestigationRequest,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    synthetic = SyntheticScenarioBuilder().build(
        prompt=scenario.prompt,
        scenario_name=scenario.scenario_name,
    )
    repository = InvestigationRepository(
        transactions=synthetic.transactions,
        customers=[synthetic.customer],
    )
    fleet = FraudInvestigationFleet(settings, repository=repository)
    case = _run_or_raise(
        lambda: fleet.investigate(
            synthetic.trigger_transaction_id,
            request,
            create_case_run=True,
        )
    )
    case = case.model_copy(
        update={"agent_outputs": [synthetic.to_agent_output(), *case.agent_outputs]}
    )
    memory_snapshot_id = fleet.memory_bank.save_case(case)
    case = case.model_copy(update={"memory_snapshot_id": memory_snapshot_id})
    fleet.report_writer.write_markdown(case)
    return redact_case_for_role(case, request.role)


@app.get("/jobs/{job_id}", response_model=InvestigationJob)
def get_investigation_job(
    job_id: str,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationJob:
    return _run_or_raise(lambda: FraudInvestigationFleet(settings).get_job(job_id, request))


@app.post("/jobs/{job_id}/run", response_model=InvestigationJob)
def run_investigation_job(
    job_id: str,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationJob:
    return _run_or_raise(lambda: FraudInvestigationFleet(settings).run_investigation_job(job_id, request))


@app.post("/pubsub/investigations", response_model=InvestigationJob)
def run_pubsub_investigation_worker(
    envelope: PubSubPushEnvelope,
    request: Request,
) -> InvestigationJob:
    trace_id = _trace_id_from_header(request.headers.get("X-Cloud-Trace-Context"))
    worker_context = build_service_context(
        actor_id="pubsub-worker@tracelayer",
        trace_id=trace_id,
    )
    return _run_or_raise(
        lambda: FraudInvestigationFleet(settings).run_pubsub_investigation_worker(
            envelope,
            worker_context,
        )
    )


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


@app.get("/approvals/pending", response_model=list[PendingApprovalSummary])
def list_pending_approvals(
    request: RequestContext = Depends(get_request_context),
) -> list[PendingApprovalSummary]:
    return _run_or_raise(lambda: FraudInvestigationFleet(settings).list_pending_approvals(request))


@app.get("/approvals/log", response_model=list[ApprovalLogEntry])
def list_approval_log(
    request: RequestContext = Depends(get_request_context),
) -> list[ApprovalLogEntry]:
    return _run_or_raise(lambda: FraudInvestigationFleet(settings).list_approval_log(request))


@app.get("/risk-policy", response_model=RiskPolicy)
def get_risk_policy(request: RequestContext = Depends(get_request_context)) -> RiskPolicy:
    return _run_or_raise(lambda: FraudInvestigationFleet(settings).get_risk_policy(request))


@app.put("/risk-policy", response_model=RiskPolicy)
def update_risk_policy(
    policy: RiskPolicy,
    request: RequestContext = Depends(get_request_context),
) -> RiskPolicy:
    return _run_or_raise(
        lambda: FraudInvestigationFleet(settings).update_risk_policy(policy, request)
    )


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


@app.post("/cases/{case_id}/missing-data", response_model=InvestigationCase)
def provide_missing_data(
    case_id: str,
    missing_data: MissingDataRequest,
    request: RequestContext = Depends(get_request_context),
) -> InvestigationCase:
    case = _run_or_raise(
        lambda: FraudInvestigationFleet(settings).provide_missing_data(
            case_id,
            missing_data,
            request,
        )
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


def _agent_registry(request: Request | None = None) -> AgentRegistry:
    service_url = settings.public_service_url
    if not service_url and request:
        service_url = str(request.base_url).rstrip("/")
    region = settings.google_cloud_location
    if region == "global":
        region = "us-central1"
    return AgentRegistry(
        project_id=settings.google_cloud_project,
        region=region,
        service_url=service_url,
        triage_agent_engine_resource=settings.triage_agent_engine_resource,
        triage_agent_runtime_principal=settings.triage_agent_runtime_principal,
    )


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


def _trace_id_from_header(header: str | None) -> str | None:
    if not header:
        return None
    trace_id = header.split("/", maxsplit=1)[0].strip()
    return trace_id or None

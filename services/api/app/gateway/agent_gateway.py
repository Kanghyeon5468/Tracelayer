from __future__ import annotations

from time import perf_counter

from app.agents.base import BaseInvestigationAgent
from app.domain.models import InvestigationContext, RequestContext
from app.observability.audit import AuditLedger
from app.observability.cloud_logging import CloudTraceLogger
from app.security.guardrails import ModelArmorGuardrail
from app.security.policy import PolicyEngine


class AgentGateway:
    """Runs agents through authorization, guardrails, and audit controls."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        guardrail: ModelArmorGuardrail,
        audit_ledger: AuditLedger,
        trace_logger: CloudTraceLogger | None = None,
    ) -> None:
        self.policy_engine = policy_engine
        self.guardrail = guardrail
        self.audit_ledger = audit_ledger
        self.trace_logger = trace_logger or CloudTraceLogger()

    def run_agent(
        self,
        agent: BaseInvestigationAgent,
        context: InvestigationContext,
        request: RequestContext,
    ) -> None:
        started_at = perf_counter()
        decision = self.policy_engine.agent_can_run(
            agent.identity,
            agent.required_permissions,
        )
        self.audit_ledger.record(
            request=request,
            actor_type="agent",
            action="agent.authorize",
            resource=agent.identity.agent_id,
            decision="allow" if decision.allowed else "deny",
            reason=decision.reason,
            case_id=context.case_id,
            metadata={
                "service_account": agent.identity.service_account,
                "required_permissions": agent.required_permissions,
            },
        )

        if not decision.allowed:
            self.trace_logger.emit(
                message="Agent authorization denied.",
                severity="WARNING",
                request=request,
                case_id=context.case_id,
                agent_id=agent.identity.agent_id,
                agent_version=agent.identity.version,
                tool="agent_gateway.authorize",
                latency_ms=(perf_counter() - started_at) * 1000,
                status="denied",
                metadata={"reason": decision.reason},
            )
            raise PermissionError(decision.reason)

        raw_output = agent.run(context)
        sanitized_output = self.guardrail.sanitize_output(raw_output)
        context.agent_outputs[-1] = sanitized_output

        output_findings = self.guardrail.inspect_text(
            sanitized_output.summary,
            f"{agent.identity.agent_id}-gateway",
        )
        context.guardrail_findings = self.guardrail.merge_findings(
            [context.guardrail_findings, output_findings]
        )
        context.audit_chain_tip = self.audit_ledger.record(
            request=request,
            actor_type="agent",
            action="agent.run",
            resource=agent.identity.agent_id,
            decision="allow",
            reason="Agent completed through gateway controls.",
            case_id=context.case_id,
            metadata={
                "confidence": sanitized_output.confidence,
                "guardrail_findings": sanitized_output.guardrail_findings,
            },
        ).event_hash
        self.trace_logger.emit(
            message="Agent completed through gateway controls.",
            severity="INFO",
            request=request,
            case_id=context.case_id,
            agent_id=agent.identity.agent_id,
            agent_version=agent.identity.version,
            tool=agent.__class__.__name__,
            latency_ms=(perf_counter() - started_at) * 1000,
            status="succeeded",
            metadata={
                "confidence": sanitized_output.confidence,
                "guardrail_finding_count": len(context.guardrail_findings),
            },
        )

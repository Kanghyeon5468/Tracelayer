from __future__ import annotations

from app.agents.base import BaseInvestigationAgent
from app.domain.models import InvestigationContext, RequestContext
from app.observability.audit import AuditLedger
from app.security.guardrails import ModelArmorGuardrail
from app.security.policy import PolicyEngine


class AgentGateway:
    """Runs agents through authorization, guardrails, and audit controls."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        guardrail: ModelArmorGuardrail,
        audit_ledger: AuditLedger,
    ) -> None:
        self.policy_engine = policy_engine
        self.guardrail = guardrail
        self.audit_ledger = audit_ledger

    def run_agent(
        self,
        agent: BaseInvestigationAgent,
        context: InvestigationContext,
        request: RequestContext,
    ) -> None:
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

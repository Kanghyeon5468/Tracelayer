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
        # The gateway is the policy boundary before any agent can touch tools or case state.
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
                "agent_principal": agent.identity.agent_principal,
                "registry_resource": agent.identity.registry_resource,
                "managed_gateway_policy": agent.identity.managed_gateway_policy,
                "identity_provider": agent.identity.identity_provider,
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

        raw_output = self._run_agent(agent, context, request)
        # Outputs are sanitized after every agent step before they enter shared memory.
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
                "service_account": agent.identity.service_account,
                "agent_principal": agent.identity.agent_principal,
                "registry_resource": agent.identity.registry_resource,
                "managed_gateway_policy": agent.identity.managed_gateway_policy,
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

    @staticmethod
    def _run_agent(
        agent: BaseInvestigationAgent,
        context: InvestigationContext,
        request: RequestContext,
    ):
        adk_runtime = getattr(agent, "adk_runtime", None)
        if not adk_runtime:
            return agent.run(context)

        return adk_runtime.run_agent_tool(
            identity=agent.identity,
            context=context,
            request=request,
            tool_name=agent.__class__.__name__,
            description=getattr(agent, "adk_description", agent.identity.display_name),
            instruction=getattr(
                agent,
                "adk_instruction",
                (
                    f"You are {agent.identity.display_name}. Run the approved "
                    "TraceLayer investigation tool and return structured evidence."
                ),
            ),
            tool_callback=lambda: agent.run(context),
        ).output

from __future__ import annotations

from datetime import UTC, datetime

from app.agents import (
    AgentRegistry,
    CaseManagerAgent,
    ComplianceAgent,
    EvidenceAgent,
    NetworkAgent,
    TriageAgent,
)
from app.config import Settings
from app.connectors.pubsub import LocalPubSubBus
from app.connectors.reasoner import GeminiReasoner
from app.connectors.report_writer import ReportWriter
from app.connectors.repository import InvestigationRepository
from app.domain.models import (
    ApprovalDecisionRequest,
    CaseStatus,
    InvestigationCase,
    InvestigationContext,
    RequestContext,
)
from app.federation.engine import VeritasFederatedRiskEngine
from app.gateway.agent_gateway import AgentGateway
from app.memory.memory_bank import MemoryBank
from app.observability.audit import AuditLedger
from app.security.context import build_service_context
from app.security.guardrails import ModelArmorGuardrail
from app.security.policy import PolicyEngine


class FraudInvestigationFleet:
    """Coordinates the local agent fleet for one investigation case."""

    def __init__(
        self,
        settings: Settings,
        repository: InvestigationRepository | None = None,
        report_writer: ReportWriter | None = None,
        bus: LocalPubSubBus | None = None,
        memory_bank: MemoryBank | None = None,
        audit_ledger: AuditLedger | None = None,
        policy_engine: PolicyEngine | None = None,
        guardrail: ModelArmorGuardrail | None = None,
        federated_engine: VeritasFederatedRiskEngine | None = None,
    ) -> None:
        self.settings = settings
        self.registry = AgentRegistry()
        self.repository = repository or InvestigationRepository()
        self.report_writer = report_writer or ReportWriter()
        self.bus = bus or LocalPubSubBus()
        self.memory_bank = memory_bank or MemoryBank(settings)
        self.audit_ledger = audit_ledger or AuditLedger(settings)
        self.policy_engine = policy_engine or PolicyEngine()
        self.guardrail = guardrail or ModelArmorGuardrail()
        self.gateway = AgentGateway(self.policy_engine, self.guardrail, self.audit_ledger)
        self.reasoner = GeminiReasoner(settings, self.guardrail)
        self.federated_engine = federated_engine or VeritasFederatedRiskEngine()

    def investigate(
        self,
        transaction_id: str,
        request: RequestContext | None = None,
    ) -> InvestigationCase:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "cases.investigate")
        self.audit_ledger.record(
            request=request,
            action="cases.investigate",
            resource=transaction_id,
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        trigger = self.repository.get_transaction(transaction_id)
        customer = self.repository.get_customer(trigger.customer_id)
        related_transactions = self.repository.find_related_transactions(trigger)

        context = InvestigationContext(
            case_id=f"case-{trigger.transaction_id}",
            trigger_transaction=trigger,
            customer=customer,
            related_transactions=related_transactions,
        )

        self.bus.publish(
            self.settings.pubsub_topic_investigations,
            {"case_id": context.case_id, "transaction_id": transaction_id},
        )

        policy_text = self.repository.read_policy_text()
        agents = [
            TriageAgent(
                self.registry.get("triage-agent"),
                self.reasoner,
                self.federated_engine,
            ),
            NetworkAgent(self.registry.get("network-agent")),
            EvidenceAgent(self.registry.get("evidence-agent"), policy_text),
            ComplianceAgent(self.registry.get("compliance-agent")),
            CaseManagerAgent(self.registry.get("case-manager-agent")),
        ]

        for agent in agents:
            self.gateway.run_agent(agent, context, request)

        case = InvestigationCase(
            case_id=context.case_id,
            status=context.status,
            trigger_transaction_id=trigger.transaction_id,
            customer_id=customer.customer_id,
            risk_score=context.risk_score,
            priority=context.priority,
            agent_outputs=context.agent_outputs,
            network_links=context.network_links,
            evidence_timeline=context.evidence_timeline,
            compliance_findings=context.compliance_findings,
            approval_request=context.approval_request,
            guardrail_findings=context.guardrail_findings,
            federated_risk_signal=context.federated_risk_signal,
            audit_chain_tip=context.audit_chain_tip,
        )

        report_path = self.report_writer.path_for(case.case_id)
        case = case.model_copy(update={"report_path": str(report_path)})
        memory_snapshot_id = self.memory_bank.save_case(case)
        case = case.model_copy(update={"memory_snapshot_id": memory_snapshot_id})
        self.report_writer.write_markdown(case)

        if case.approval_request:
            self.bus.publish(
                self.settings.pubsub_topic_approvals,
                {
                    "case_id": case.case_id,
                    "approval_id": case.approval_request.approval_id,
                    "action": case.approval_request.action,
                },
            )

        final_event = self.audit_ledger.record(
            request=request,
            action="cases.persist",
            resource=case.case_id,
            decision="allow",
            reason="Case report and memory snapshot persisted.",
            case_id=case.case_id,
            metadata={
                "report_path": case.report_path,
                "memory_snapshot_id": memory_snapshot_id,
            },
        )
        case = case.model_copy(update={"audit_chain_tip": final_event.event_hash})
        self.report_writer.write_markdown(case)
        return case

    def get_case(self, case_id: str, request: RequestContext | None = None) -> InvestigationCase:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "cases.read")
        self.audit_ledger.record(
            request=request,
            action="cases.read",
            resource=case_id,
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
            case_id=case_id,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        case = self.memory_bank.load_case(case_id)
        if not case:
            raise KeyError(f"Case not found: {case_id}")
        return case

    def decide_approval(
        self,
        case_id: str,
        decision_request: ApprovalDecisionRequest,
        request: RequestContext | None = None,
    ) -> InvestigationCase:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "approvals.decide")
        self.audit_ledger.record(
            request=request,
            action="approvals.decide",
            resource=decision_request.approval_id,
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
            case_id=case_id,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        case = self.memory_bank.load_case(case_id)
        if not case:
            raise KeyError(f"Case not found: {case_id}")
        if not case.approval_request:
            raise ValueError(f"Case does not have a pending approval request: {case_id}")
        if case.approval_request.approval_id != decision_request.approval_id:
            raise ValueError("Approval ID does not match the case approval request.")

        approval = case.approval_request.model_copy(
            update={
                "status": decision_request.decision,
                "decided_by": request.actor_id,
                "decision_reason": decision_request.reason,
                "decided_at": datetime.now(UTC),
            }
        )
        updated_status = (
            CaseStatus.CLOSED if decision_request.decision == "approved" else CaseStatus.OPEN
        )
        updated_case = case.model_copy(
            update={
                "approval_request": approval,
                "status": updated_status,
            }
        )
        report_path = self.report_writer.path_for(updated_case.case_id)
        updated_case = updated_case.model_copy(update={"report_path": str(report_path)})
        memory_snapshot_id = self.memory_bank.save_case(updated_case)
        event = self.audit_ledger.record(
            request=request,
            action="approvals.persist_decision",
            resource=decision_request.approval_id,
            decision="allow",
            reason="Approval decision persisted to the case memory bank.",
            case_id=case_id,
            metadata={"memory_snapshot_id": memory_snapshot_id},
        )
        updated_case = updated_case.model_copy(
            update={
                "memory_snapshot_id": memory_snapshot_id,
                "audit_chain_tip": event.event_hash,
            }
        )
        self.report_writer.write_markdown(updated_case)
        return updated_case

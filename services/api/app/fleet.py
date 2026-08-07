from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import uuid4

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
    ApprovalLogEntry,
    CaseStatus,
    InvestigationCase,
    InvestigationContext,
    PendingApprovalSummary,
    RequestContext,
)
from app.federation.engine import VeritasFederatedRiskEngine
from app.gateway.agent_gateway import AgentGateway
from app.memory.memory_bank import MemoryBank, create_memory_bank
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
        self.memory_bank = memory_bank or create_memory_bank(settings)
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
        create_case_run: bool = False,
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

        case_id = f"case-{trigger.transaction_id}"
        if create_case_run:
            case_id = f"{case_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"

        context = InvestigationContext(
            case_id=case_id,
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

    def investigate_random_demo(
        self,
        request: RequestContext | None = None,
    ) -> InvestigationCase:
        transaction_ids = self.repository.list_demo_transaction_ids()
        if not transaction_ids:
            raise ValueError("No flagged demo transactions are configured.")
        return self.investigate(
            self._choose_demo_transaction_id(transaction_ids),
            request,
            create_case_run=True,
        )

    def _choose_demo_transaction_id(self, transaction_ids: list[str]) -> str:
        recent_transaction_ids: list[str] = []
        for case in self.memory_bank.list_cases():
            transaction_id = case.trigger_transaction_id
            if transaction_id not in transaction_ids or transaction_id in recent_transaction_ids:
                continue
            recent_transaction_ids.append(transaction_id)
            if len(recent_transaction_ids) >= max(len(transaction_ids) - 1, 1):
                break

        excluded = set(recent_transaction_ids)
        candidates = [transaction_id for transaction_id in transaction_ids if transaction_id not in excluded]
        if not candidates:
            candidates = transaction_ids

        return random.choice(candidates)

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

    def list_pending_approvals(
        self,
        request: RequestContext | None = None,
    ) -> list[PendingApprovalSummary]:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "approvals.decide")
        self.audit_ledger.record(
            request=request,
            action="approvals.list_pending",
            resource="pending-approvals",
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        summaries: list[PendingApprovalSummary] = []
        for case in self.memory_bank.list_pending_approval_cases():
            if not case.approval_request:
                continue
            summaries.append(
                PendingApprovalSummary(
                    case_id=case.case_id,
                    approval_id=case.approval_request.approval_id,
                    action=case.approval_request.action,
                    reason=case.approval_request.reason,
                    risk_score=case.risk_score,
                    priority=case.priority,
                    trigger_transaction_id=case.trigger_transaction_id,
                    customer_id=case.customer_id,
                    requested_by_agent_id=case.approval_request.requested_by_agent_id,
                    memory_snapshot_id=case.memory_snapshot_id,
                )
            )
        return summaries

    def list_approval_log(
        self,
        request: RequestContext | None = None,
    ) -> list[ApprovalLogEntry]:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "approvals.decide")
        self.audit_ledger.record(
            request=request,
            action="approvals.list_log",
            resource="approval-log",
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        log_entries: list[ApprovalLogEntry] = []
        for case in self.memory_bank.list_cases():
            if not case.approval_request:
                continue
            approval = case.approval_request
            log_entries.append(
                ApprovalLogEntry(
                    case_id=case.case_id,
                    approval_id=approval.approval_id,
                    approval_status=approval.status,
                    case_status=case.status,
                    action=approval.action,
                    reason=approval.reason,
                    risk_score=case.risk_score,
                    priority=case.priority,
                    trigger_transaction_id=case.trigger_transaction_id,
                    customer_id=case.customer_id,
                    requested_by_agent_id=approval.requested_by_agent_id,
                    decided_by=approval.decided_by,
                    decision_reason=approval.decision_reason,
                    decided_at=approval.decided_at,
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                    memory_snapshot_id=case.memory_snapshot_id,
                )
            )
        return log_entries

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
                "updated_at": datetime.now(UTC),
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

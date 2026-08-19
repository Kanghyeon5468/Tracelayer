from __future__ import annotations

import base64
import json
import random
from datetime import UTC, datetime
from uuid import uuid4

from app.adk_runtime import AdkAgentRuntime
from app.agents import (
    AgentRegistry,
    CaseManagerAgent,
    CaseManagerPlanningAgent,
    CampaignTraceAgent,
    ComplianceAgent,
    EvidenceAgent,
    NetworkAgent,
    TriageAgent,
)
from app.config import Settings
from app.connectors.bigquery_network import BigQueryNetworkSearch
from app.connectors.pubsub import PubSubBus, create_pubsub_bus
from app.connectors.reasoner import GeminiReasoner
from app.connectors.report_writer import ReportWriter
from app.connectors.repository import InvestigationRepository
from app.domain.models import (
    ApprovalDecisionRequest,
    ApprovalLogEntry,
    CaseStatus,
    EvidenceEvent,
    InvestigationCase,
    InvestigationContext,
    InvestigationJob,
    InvestigationJobStatus,
    PendingApprovalSummary,
    PlanStepStatus,
    PubSubPushEnvelope,
    RequestContext,
    RiskPolicy,
    Transaction,
)
from app.federation.engine import VeritasFederatedRiskEngine
from app.gateway.agent_gateway import AgentGateway
from app.memory.job_store import (
    FirestoreInvestigationJobStore,
    LocalInvestigationJobStore,
    create_job_store,
    touch_job,
)
from app.memory.memory_bank import FirestoreMemoryBank, MemoryBank, create_memory_bank
from app.memory.risk_policy_store import (
    FirestoreRiskPolicyStore,
    LocalRiskPolicyStore,
    create_risk_policy_store,
)
from app.observability.audit import AuditLedger
from app.observability.cloud_logging import CloudTraceLogger
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
        bus: PubSubBus | None = None,
        memory_bank: MemoryBank | FirestoreMemoryBank | None = None,
        job_store: LocalInvestigationJobStore | FirestoreInvestigationJobStore | None = None,
        risk_policy_store: LocalRiskPolicyStore | FirestoreRiskPolicyStore | None = None,
        audit_ledger: AuditLedger | None = None,
        policy_engine: PolicyEngine | None = None,
        guardrail: ModelArmorGuardrail | None = None,
        federated_engine: VeritasFederatedRiskEngine | None = None,
        adk_runtime: AdkAgentRuntime | None = None,
    ) -> None:
        self.settings = settings
        self.registry = AgentRegistry()
        self.repository = repository or InvestigationRepository()
        self.report_writer = report_writer or ReportWriter()
        self.bus = bus or create_pubsub_bus(settings)
        self.memory_bank = memory_bank or create_memory_bank(settings)
        self.job_store = job_store or create_job_store(settings)
        self.risk_policy_store = risk_policy_store or create_risk_policy_store(settings)
        self.audit_ledger = audit_ledger or AuditLedger(settings)
        self.trace_logger = CloudTraceLogger()
        self.policy_engine = policy_engine or PolicyEngine()
        self.guardrail = guardrail or ModelArmorGuardrail()
        self.gateway = AgentGateway(self.policy_engine, self.guardrail, self.audit_ledger)
        self.reasoner = GeminiReasoner(settings, self.guardrail)
        self.federated_engine = federated_engine or VeritasFederatedRiskEngine()
        self.adk_runtime = adk_runtime or AdkAgentRuntime(settings)

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
        self.trace_logger.emit(
            message="Investigation started.",
            request=request,
            case_id=None,
            tool="FraudInvestigationFleet.investigate",
            status="running",
            metadata={"transaction_id": transaction_id},
        )

        trigger = self.repository.get_transaction(transaction_id)
        customer = self.repository.get_customer(trigger.customer_id)
        case_id = f"case-{trigger.transaction_id}"
        if create_case_run:
            case_id = f"{case_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"

        context = InvestigationContext(
            case_id=case_id,
            trigger_transaction=trigger,
            customer=customer,
        )

        policy_text = self.repository.read_policy_text()
        risk_policy = self.risk_policy_store.load_policy()
        network_search = BigQueryNetworkSearch(self.settings, self.repository)
        planned_action_handlers = {
            "score_transaction": TriageAgent(
                self.registry.get("triage-agent"),
                self.reasoner,
                self.federated_engine,
                risk_policy,
                self.adk_runtime,
            ),
            "search_related_transactions": NetworkAgent(
                self.registry.get("network-agent"),
                network_search,
                self.adk_runtime,
            ),
            "build_evidence_timeline": EvidenceAgent(
                self.registry.get("evidence-agent"),
                policy_text,
            ),
            "check_policy_and_pii": ComplianceAgent(self.registry.get("compliance-agent")),
            "trace_cluster_funds": CampaignTraceAgent(
                self.registry.get("network-agent"),
                self.adk_runtime,
            ),
        }
        case_manager_agent = CaseManagerAgent(
            self.registry.get("case-manager-agent"),
            self.adk_runtime,
        )
        planned_action_handlers.update(
            {
                "request_manual_review": case_manager_agent,
                "request_supervisor_approval": case_manager_agent,
                "request_more_data": case_manager_agent,
                "pause_case": case_manager_agent,
                "close_case": case_manager_agent,
            }
        )
        planning_agent = CaseManagerPlanningAgent(
            self.registry.get("case-manager-agent"),
            self.adk_runtime,
        )

        self.gateway.run_agent(planning_agent, context, request)
        self._execute_investigation_plan(
            planned_action_handlers,
            context,
            request,
            allowed_actions={"score_transaction"},
            planning_agent=planning_agent,
        )
        self.gateway.run_agent(planning_agent, context, request)
        self._execute_investigation_plan(
            planned_action_handlers,
            context,
            request,
            planning_agent=planning_agent,
        )

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
            investigation_plan=context.investigation_plan,
            approval_request=context.approval_request,
            approval_history=context.approval_history,
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
            self._publish_event(
                self.settings.pubsub_topic_approvals,
                {
                    "event_type": "approval_requested",
                    "case_id": case.case_id,
                    "approval_id": case.approval_request.approval_id,
                    "action": case.approval_request.action,
                },
                case.case_id,
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
        self.trace_logger.emit(
            message="Investigation persisted.",
            request=request,
            case_id=case.case_id,
            tool="FraudInvestigationFleet.investigate",
            status="succeeded",
            metadata={
                "risk_score": case.risk_score,
                "priority": case.priority,
                "agent_count": len(case.agent_outputs),
            },
        )
        return case

    def _execute_investigation_plan(
        self,
        planned_action_handlers: dict[str, object],
        context: InvestigationContext,
        request: RequestContext,
        allowed_actions: set[str] | None = None,
        planning_agent: CaseManagerPlanningAgent | None = None,
    ) -> None:
        if not context.investigation_plan:
            raise ValueError("Case Manager did not produce an investigation plan.")

        while True:
            replanned = False
            for step in context.investigation_plan.steps:
                if allowed_actions is not None and step.action not in allowed_actions:
                    continue
                if step.status != PlanStepStatus.PLANNED:
                    continue
                agent = planned_action_handlers.get(step.action)
                if not agent:
                    step.status = PlanStepStatus.SKIPPED
                    continue
                self.gateway.run_agent(agent, context, request)
                step.status = PlanStepStatus.COMPLETED
                if (
                    planning_agent
                    and allowed_actions is None
                    and step.action == "search_related_transactions"
                    and self._should_replan_after_network(context)
                ):
                    self.trace_logger.emit(
                        message="Network findings triggered adaptive replanning.",
                        request=request,
                        case_id=context.case_id,
                        agent_id=planning_agent.identity.agent_id,
                        agent_version=planning_agent.identity.version,
                        tool="CaseManagerPlanningAgent.adaptive_replan",
                        status="running",
                        metadata={
                            "previous_strategy": context.investigation_plan.strategy,
                            "trigger_action": step.action,
                        },
                    )
                    self.gateway.run_agent(planning_agent, context, request)
                    replanned = True
                    break
            if not replanned:
                break

    @staticmethod
    def _should_replan_after_network(context: InvestigationContext) -> bool:
        if not context.investigation_plan:
            return False
        if context.investigation_plan.strategy == "campaign_escalation_replan":
            return False
        if any(step.action == "trace_cluster_funds" for step in context.investigation_plan.steps):
            return False
        latest_network_output = next(
            (
                output
                for output in reversed(context.agent_outputs)
                if output.agent_id == "network-agent"
                and output.data.get("campaign_detection")
            ),
            None,
        )
        if not latest_network_output:
            return False
        campaign = latest_network_output.data.get("campaign_detection") or {}
        return bool(
            campaign.get("detected")
            and (
                campaign.get("severity") in {"high", "critical"}
                or campaign.get("network_link_count", 0) >= 6
                or campaign.get("linked_transaction_count", 0) >= 4
            )
        )

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

    def enqueue_random_demo(
        self,
        request: RequestContext | None = None,
    ) -> InvestigationJob:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "cases.investigate")
        self.audit_ledger.record(
            request=request,
            action="jobs.enqueue_demo",
            resource="random-demo",
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        transaction_ids = self.repository.list_demo_transaction_ids()
        if not transaction_ids:
            raise ValueError("No flagged demo transactions are configured.")

        transaction_id = self._choose_demo_transaction_id(transaction_ids)
        job_id = f"job-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        job = InvestigationJob(
            job_id=job_id,
            status=InvestigationJobStatus.QUEUED,
            transaction_id=transaction_id,
            pubsub_topic=self.settings.pubsub_topic_investigations,
            pubsub_message_id="pending-publish",
        )
        job = self.job_store.save_job(job)

        try:
            message = self.bus.publish(
                self.settings.pubsub_topic_investigations,
                {
                    "job_id": job_id,
                    "transaction_id": transaction_id,
                    "requested_by": request.actor_id,
                    "requested_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            failed = touch_job(
                job,
                status=InvestigationJobStatus.FAILED,
                error=f"Pub/Sub publish failed: {exc}",
            )
            return self.job_store.save_job(failed)

        queued = touch_job(
            job,
            pubsub_topic=message.topic,
            pubsub_message_id=message.message_id,
        )
        self.trace_logger.emit(
            message="Investigation job published to Pub/Sub.",
            request=request,
            tool="PubSub.publish",
            status="queued",
            metadata={
                "job_id": job_id,
                "transaction_id": transaction_id,
                "pubsub_topic": message.topic,
                "pubsub_message_id": message.message_id,
            },
        )
        return self.job_store.save_job(queued)

    def run_investigation_job(
        self,
        job_id: str,
        request: RequestContext | None = None,
    ) -> InvestigationJob:
        request = request or build_service_context()
        job = self.job_store.load_job(job_id)
        if not job:
            raise KeyError(f"Investigation job not found: {job_id}")
        if job.status == InvestigationJobStatus.SUCCEEDED:
            return job
        if not job.transaction_id:
            failed = touch_job(
                job,
                status=InvestigationJobStatus.FAILED,
                error="Missing transaction id.",
            )
            return self.job_store.save_job(failed)

        running = self.job_store.save_job(touch_job(job, status=InvestigationJobStatus.RUNNING))
        self.trace_logger.emit(
            message="Investigation job running.",
            request=request,
            tool="FraudInvestigationFleet.run_investigation_job",
            status="running",
            metadata={"job_id": job_id, "transaction_id": running.transaction_id},
        )
        try:
            case = self.investigate(running.transaction_id, request, create_case_run=True)
        except Exception as exc:
            failed = touch_job(running, status=InvestigationJobStatus.FAILED, error=str(exc))
            self.trace_logger.emit(
                message="Investigation job failed.",
                severity="ERROR",
                request=request,
                tool="FraudInvestigationFleet.run_investigation_job",
                status="failed",
                metadata={"job_id": job_id, "error": str(exc)},
            )
            return self.job_store.save_job(failed)

        succeeded = touch_job(
            running,
            status=InvestigationJobStatus.SUCCEEDED,
            case_id=case.case_id,
            error=None,
        )
        self.trace_logger.emit(
            message="Investigation job succeeded.",
            request=request,
            case_id=case.case_id,
            tool="FraudInvestigationFleet.run_investigation_job",
            status="succeeded",
            metadata={"job_id": job_id, "transaction_id": running.transaction_id},
        )
        return self.job_store.save_job(succeeded)

    def run_pubsub_investigation_worker(
        self,
        envelope: PubSubPushEnvelope,
        request: RequestContext | None = None,
    ) -> InvestigationJob:
        request = request or build_service_context(actor_id="pubsub-worker@tracelayer")
        payload = self._decode_pubsub_payload(envelope)
        job_id = payload.get("job_id")
        if not job_id:
            raise ValueError("Pub/Sub investigation payload must include job_id.")

        self.audit_ledger.record(
            request=request,
            action="jobs.pubsub_push_received",
            resource=job_id,
            decision="allow",
            reason="Authenticated Pub/Sub push delivered an investigation job.",
            metadata={
                "subscription": envelope.subscription,
                "pubsub_message_id": envelope.message.message_id,
            },
        )
        self.trace_logger.emit(
            message="Pub/Sub push received by Cloud Run worker.",
            request=request,
            tool="CloudRunPubSubWorker",
            status="received",
            metadata={
                "job_id": job_id,
                "subscription": envelope.subscription,
                "pubsub_message_id": envelope.message.message_id,
            },
        )
        return self.run_investigation_job(job_id, request)

    def get_job(
        self,
        job_id: str,
        request: RequestContext | None = None,
    ) -> InvestigationJob:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "cases.read")
        self.audit_ledger.record(
            request=request,
            action="jobs.read",
            resource=job_id,
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        job = self.job_store.load_job(job_id)
        if not job:
            raise KeyError(f"Investigation job not found: {job_id}")
        return job

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
            approvals = [*case.approval_history]
            if case.approval_request:
                approvals.append(case.approval_request)

            for approval in approvals:
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
        return sorted(
            self._deduplicate_approval_log(log_entries),
            key=lambda entry: entry.decided_at or entry.updated_at,
            reverse=True,
        )

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

        if decision_request.decision == "more_evidence":
            return self._request_more_evidence(case, decision_request, request)

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
        self.trace_logger.emit(
            message="Human approval decision persisted.",
            request=request,
            case_id=case_id,
            tool="FraudInvestigationFleet.decide_approval",
            status=decision_request.decision,
            metadata={
                "approval_id": decision_request.approval_id,
                "decision": decision_request.decision,
            },
        )
        return updated_case

    def _request_more_evidence(
        self,
        case: InvestigationCase,
        decision_request: ApprovalDecisionRequest,
        request: RequestContext,
    ) -> InvestigationCase:
        if not case.approval_request:
            raise ValueError(f"Case does not have a pending approval request: {case.case_id}")

        superseded_approval = case.approval_request.model_copy(
            update={
                "status": "more_evidence",
                "decided_by": request.actor_id,
                "decision_reason": decision_request.reason,
                "decided_at": datetime.now(UTC),
            }
        )
        context = self._context_from_case(
            case.model_copy(
                update={
                    "approval_request": superseded_approval,
                    "approval_history": [*case.approval_history, superseded_approval],
                    "status": CaseStatus.OPEN,
                }
            )
        )

        policy_text = self.repository.read_policy_text()
        self.gateway.run_agent(
            EvidenceAgent(self.registry.get("evidence-agent"), policy_text),
            context,
            request,
        )
        context.evidence_timeline.append(
            EvidenceEvent(
                timestamp=datetime.now(UTC),
                event_type="human_feedback",
                description=f"Reviewer requested more evidence: {decision_request.reason}",
                source="human_approval",
                related_transaction_id=context.trigger_transaction.transaction_id,
            )
        )
        context.evidence_timeline = sorted(
            context.evidence_timeline,
            key=lambda event: event.timestamp,
        )
        self.gateway.run_agent(
            ComplianceAgent(self.registry.get("compliance-agent")),
            context,
            request,
        )
        self.gateway.run_agent(
            CaseManagerAgent(self.registry.get("case-manager-agent"), self.adk_runtime),
            context,
            request,
        )

        updated_case = self._case_from_context(context, case.created_at)
        report_path = self.report_writer.path_for(updated_case.case_id)
        updated_case = updated_case.model_copy(update={"report_path": str(report_path)})
        memory_snapshot_id = self.memory_bank.save_case(updated_case)
        event = self.audit_ledger.record(
            request=request,
            action="approvals.request_more_evidence",
            resource=decision_request.approval_id,
            decision="allow",
            reason="Human feedback reran Evidence, Compliance, and Case Manager agents.",
            case_id=case.case_id,
            metadata={
                "memory_snapshot_id": memory_snapshot_id,
                "new_approval_id": (
                    updated_case.approval_request.approval_id
                    if updated_case.approval_request
                    else None
                ),
            },
        )
        updated_case = updated_case.model_copy(
            update={
                "memory_snapshot_id": memory_snapshot_id,
                "audit_chain_tip": event.event_hash,
            }
        )
        self.report_writer.write_markdown(updated_case)
        self.trace_logger.emit(
            message="Human feedback requested more evidence and agents reran.",
            request=request,
            case_id=case.case_id,
            tool="FraudInvestigationFleet.request_more_evidence",
            status="more_evidence",
            metadata={
                "superseded_approval_id": decision_request.approval_id,
                "new_approval_id": (
                    updated_case.approval_request.approval_id
                    if updated_case.approval_request
                    else None
                ),
            },
        )
        return updated_case

    def get_risk_policy(self, request: RequestContext | None = None) -> RiskPolicy:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "risk_policy.read")
        self.audit_ledger.record(
            request=request,
            action="risk_policy.read",
            resource="default",
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)
        return self.risk_policy_store.load_policy()

    def update_risk_policy(
        self,
        policy: RiskPolicy,
        request: RequestContext | None = None,
    ) -> RiskPolicy:
        request = request or build_service_context()
        actor_decision = self.policy_engine.actor_can(request, "risk_policy.update")
        self.audit_ledger.record(
            request=request,
            action="risk_policy.update",
            resource=policy.policy_id,
            decision="allow" if actor_decision.allowed else "deny",
            reason=actor_decision.reason,
            metadata={
                "medium_threshold": policy.medium_threshold,
                "high_threshold": policy.high_threshold,
                "critical_threshold": policy.critical_threshold,
            },
        )
        if not actor_decision.allowed:
            raise PermissionError(actor_decision.reason)

        saved_policy = policy.model_copy(
            update={
                "policy_id": "default",
                "updated_by": request.actor_id,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.risk_policy_store.save_policy(saved_policy)

    def _context_from_case(self, case: InvestigationCase) -> InvestigationContext:
        trigger = self.repository.get_transaction(case.trigger_transaction_id)
        customer = self.repository.get_customer(case.customer_id)
        return InvestigationContext(
            case_id=case.case_id,
            trigger_transaction=trigger,
            customer=customer,
            related_transactions=self._related_transactions_from_case(case, trigger),
            risk_score=case.risk_score,
            priority=case.priority,
            evidence_timeline=list(case.evidence_timeline),
            network_links=list(case.network_links),
            compliance_findings=list(case.compliance_findings),
            approval_request=case.approval_request,
            approval_history=list(case.approval_history),
            investigation_plan=case.investigation_plan,
            agent_outputs=list(case.agent_outputs),
            guardrail_findings=list(case.guardrail_findings),
            federated_risk_signal=case.federated_risk_signal,
            status=case.status,
            memory_snapshot_id=case.memory_snapshot_id,
            audit_chain_tip=case.audit_chain_tip,
        )

    def _case_from_context(
        self,
        context: InvestigationContext,
        created_at: datetime,
    ) -> InvestigationCase:
        return InvestigationCase(
            case_id=context.case_id,
            status=context.status,
            trigger_transaction_id=context.trigger_transaction.transaction_id,
            customer_id=context.customer.customer_id,
            risk_score=context.risk_score,
            priority=context.priority,
            agent_outputs=context.agent_outputs,
            network_links=context.network_links,
            evidence_timeline=context.evidence_timeline,
            compliance_findings=context.compliance_findings,
            investigation_plan=context.investigation_plan,
            approval_request=context.approval_request,
            approval_history=context.approval_history,
            guardrail_findings=context.guardrail_findings,
            federated_risk_signal=context.federated_risk_signal,
            memory_snapshot_id=context.memory_snapshot_id,
            audit_chain_tip=context.audit_chain_tip,
            created_at=created_at,
            updated_at=datetime.now(UTC),
        )

    def _related_transactions_from_case(
        self,
        case: InvestigationCase,
        trigger: Transaction,
    ) -> list[Transaction]:
        transaction_ids = {
            link.evidence_transaction_id
            for link in case.network_links
            if link.evidence_transaction_id != trigger.transaction_id
        }
        for event in case.evidence_timeline:
            if event.related_transaction_id and event.related_transaction_id != trigger.transaction_id:
                transaction_ids.add(event.related_transaction_id)

        related_transactions: list[Transaction] = []
        for transaction_id in sorted(transaction_ids):
            try:
                related_transactions.append(self.repository.get_transaction(transaction_id))
            except KeyError:
                continue
        return related_transactions

    def _publish_event(
        self,
        topic: str,
        payload: dict,
        case_id: str | None = None,
    ) -> None:
        try:
            message = self.bus.publish(topic, payload)
        except Exception as exc:
            self.audit_ledger.record(
                request=build_service_context(actor_id="pubsub-publisher@tracelayer"),
                action="pubsub.publish",
                resource=topic,
                decision="deny",
                reason=f"Pub/Sub publish failed: {exc}",
                case_id=case_id,
                metadata={"payload_type": payload.get("event_type")},
            )
            return

        self.audit_ledger.record(
            request=build_service_context(actor_id="pubsub-publisher@tracelayer"),
            action="pubsub.publish",
            resource=topic,
            decision="allow",
            reason="Event published to Pub/Sub.",
            case_id=case_id,
            metadata={
                "message_id": message.message_id,
                "payload_type": payload.get("event_type"),
            },
        )

    @staticmethod
    def _decode_pubsub_payload(envelope: PubSubPushEnvelope) -> dict:
        try:
            decoded = base64.b64decode(envelope.message.data).decode("utf-8")
            payload = json.loads(decoded)
        except Exception as exc:
            raise ValueError("Invalid Pub/Sub push payload.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Pub/Sub push payload must decode to a JSON object.")
        return payload

    @staticmethod
    def _deduplicate_approval_log(entries: list[ApprovalLogEntry]) -> list[ApprovalLogEntry]:
        latest_by_key: dict[tuple[str, str, str], ApprovalLogEntry] = {}
        for entry in entries:
            latest_by_key[(entry.case_id, entry.approval_id, entry.approval_status)] = entry
        return list(latest_by_key.values())

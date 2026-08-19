from __future__ import annotations

from app.adk_runtime import AdkAgentRuntime
from app.agents.base import BaseInvestigationAgent
from app.domain.models import (
    AgentIdentity,
    AgentOutput,
    ApprovalRequest,
    CaseStatus,
    InvestigationPlan,
    InvestigationPlanStep,
    InvestigationContext,
    PlanStepStatus,
    Priority,
)


class CaseManagerPlanningAgent(BaseInvestigationAgent):
    required_permissions = ["case.write", "reports.write"]

    def __init__(
        self,
        identity: AgentIdentity,
        adk_runtime: AdkAgentRuntime | None = None,
    ) -> None:
        self.identity = identity
        self.adk_runtime = adk_runtime

    def run(self, context: InvestigationContext) -> AgentOutput:
        plan = self._build_plan(context)
        context.investigation_plan = plan
        plan_phase = (
            "post_triage_replan" if self._triage_was_completed(context) else "initial_plan"
        )

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Created {plan.strategy} {plan_phase.replace('_', ' ')} with "
                f"{len(plan.steps)} steps. {plan.rationale}"
            ),
            confidence=0.9,
            data={
                "planning_action": "dynamic_investigation_plan",
                "plan_phase": plan_phase,
                "strategy": plan.strategy,
                "planned_agents": [step.agent_id for step in plan.steps],
                "planned_actions": [step.action for step in plan.steps],
                "step_count": len(plan.steps),
                "adk_runtime": self._adk_binding(),
            },
        )
        context.agent_outputs.append(output)
        return output

    def _adk_binding(self) -> dict:
        if not self.adk_runtime:
            return {"enabled": False, "available": False, "framework": "google_adk"}
        return self.adk_runtime.bind_agent(
            self.identity,
            description="Creates adaptive fraud investigation plans for agent fleets.",
            instruction=(
                "You are TraceLayer's Case Manager Agent. Create a case-specific "
                "investigation plan after triage. Choose only the agents needed for "
                "the current priority, missing-data state, and approval policy."
            ),
        ).as_dict()

    def _build_plan(self, context: InvestigationContext) -> InvestigationPlan:
        if not self._triage_was_completed(context):
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}-initial",
                strategy="triage_first_routing",
                rationale=(
                    "The Case Manager starts the case by asking Triage to score the "
                    "transaction, then replans after risk, federated signal, and missing-data "
                    "state are known."
                ),
                steps=[
                    InvestigationPlanStep(
                        step_id="triage",
                        agent_id="triage-agent",
                        action="score_transaction",
                        reason="Score the transaction before selecting deeper investigation agents.",
                    ),
                    InvestigationPlanStep(
                        step_id="adaptive-replan",
                        agent_id="case-manager-agent",
                        action="replan_after_triage",
                        reason="Use triage output to choose the remaining agent path.",
                    ),
                ],
            )

        completed_triage = InvestigationPlanStep(
            step_id="triage",
            agent_id="triage-agent",
            action="score_transaction",
            reason="Triage must score and classify every flagged transaction.",
            status=PlanStepStatus.COMPLETED,
        )

        if self._requires_more_data(context):
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}",
                strategy="pause_for_more_data",
                rationale=(
                    "The trigger record is missing enough risk evidence for automated "
                    "investigation. The fleet pauses instead of overreaching."
                ),
                steps=[
                    completed_triage,
                    InvestigationPlanStep(
                        step_id="request-more-data",
                        agent_id="case-manager-agent",
                        action="request_more_data",
                        reason="Ask an analyst or upstream system for additional records.",
                    ),
                    InvestigationPlanStep(
                        step_id="pause",
                        agent_id="case-manager-agent",
                        action="pause_case",
                        reason="Pause the investigation until additional evidence is supplied.",
                    ),
                ],
            )

        if context.priority == Priority.LOW:
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}",
                strategy="lightweight_review",
                rationale="Low-risk cases only need compliance checks before closure.",
                steps=[
                    completed_triage,
                    InvestigationPlanStep(
                        step_id="compliance",
                        agent_id="compliance-agent",
                        action="check_policy_and_pii",
                        reason="Confirm the low-risk case can be closed without deeper discovery.",
                    ),
                    InvestigationPlanStep(
                        step_id="close",
                        agent_id="case-manager-agent",
                        action="close_case",
                        reason="Close the case without requesting human approval.",
                    ),
                ],
            )

        if context.priority == Priority.MEDIUM:
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}",
                strategy="manual_review",
                rationale=(
                    "Medium-risk cases need local evidence and compliance review before "
                    "a human analyst decides closure."
                ),
                steps=[
                    completed_triage,
                    InvestigationPlanStep(
                        step_id="evidence",
                        agent_id="evidence-agent",
                        action="build_evidence_timeline",
                        reason="Collect trigger and federated evidence for manual review.",
                    ),
                    InvestigationPlanStep(
                        step_id="compliance",
                        agent_id="compliance-agent",
                        action="check_policy_and_pii",
                        reason="Verify the evidence can be shown to authorized reviewers.",
                    ),
                    InvestigationPlanStep(
                        step_id="approval",
                        agent_id="case-manager-agent",
                        action="request_manual_review",
                        reason="Create a human review request before closure.",
                    ),
                ],
            )

        if self._network_campaign_requires_replan(context):
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}-campaign-escalation",
                strategy="campaign_escalation_replan",
                rationale=(
                    "The Network Agent found a clustered campaign pattern after the "
                    "post-triage plan. The Case Manager adds a focused fund-tracing "
                    "step before evidence, compliance, and approval."
                ),
                steps=[
                    completed_triage,
                    InvestigationPlanStep(
                        step_id="federated-intelligence",
                        agent_id="triage-agent",
                        action="compute_federated_intelligence",
                        reason=(
                            "Use the privacy-preserving Veritas signal already computed "
                            "during triage before selecting network depth."
                        ),
                        status=PlanStepStatus.COMPLETED,
                    ),
                    InvestigationPlanStep(
                        step_id="network",
                        agent_id="network-agent",
                        action="search_related_transactions",
                        reason="Network discovery already found a campaign cluster.",
                        status=PlanStepStatus.COMPLETED,
                    ),
                    InvestigationPlanStep(
                        step_id="trace-cluster-funds",
                        agent_id="network-agent",
                        action="trace_cluster_funds",
                        reason=(
                            "Trace clustered fund movement and counterparties before "
                            "writing the evidence timeline."
                        ),
                    ),
                    InvestigationPlanStep(
                        step_id="evidence",
                        agent_id="evidence-agent",
                        action="build_evidence_timeline",
                        reason="Build a timeline from trigger, network, campaign, and federated evidence.",
                    ),
                    InvestigationPlanStep(
                        step_id="compliance",
                        agent_id="compliance-agent",
                        action="check_policy_and_pii",
                        reason="Check PII exposure and enforcement policy boundaries.",
                    ),
                    InvestigationPlanStep(
                        step_id="approval",
                        agent_id="case-manager-agent",
                        action="request_supervisor_approval",
                        reason="Require supervisor approval before any outbound hold.",
                    ),
                ],
            )

        completed_federated_intelligence = InvestigationPlanStep(
            step_id="federated-intelligence",
            agent_id="triage-agent",
            action="compute_federated_intelligence",
            reason=(
                "Use the privacy-preserving Veritas signal already computed during "
                "triage before selecting network depth."
            ),
            status=PlanStepStatus.COMPLETED,
        )

        return InvestigationPlan(
            plan_id=f"plan-{context.case_id}",
            strategy="deep_network_investigation",
            rationale=(
                "High-risk cases require network discovery, evidence collection, "
                "compliance review, and supervisor approval."
            ),
            steps=[
                completed_triage,
                completed_federated_intelligence,
                InvestigationPlanStep(
                    step_id="network",
                    agent_id="network-agent",
                    action="search_related_transactions",
                    reason="Find shared accounts, devices, IPs, emails, and counterparties.",
                ),
                InvestigationPlanStep(
                    step_id="evidence",
                    agent_id="evidence-agent",
                    action="build_evidence_timeline",
                    reason="Build a timeline from trigger, network, and federated evidence.",
                ),
                InvestigationPlanStep(
                    step_id="compliance",
                    agent_id="compliance-agent",
                    action="check_policy_and_pii",
                    reason="Check PII exposure and enforcement policy boundaries.",
                ),
                InvestigationPlanStep(
                    step_id="approval",
                    agent_id="case-manager-agent",
                    action="request_supervisor_approval",
                    reason="Require supervisor approval before any outbound hold.",
                ),
            ],
        )

    @staticmethod
    def _requires_more_data(context: InvestigationContext) -> bool:
        return "missing_data" in context.trigger_transaction.risk_flags

    @staticmethod
    def _triage_was_completed(context: InvestigationContext) -> bool:
        return any(output.agent_id == "triage-agent" for output in context.agent_outputs)

    @staticmethod
    def _network_campaign_requires_replan(context: InvestigationContext) -> bool:
        if not context.investigation_plan:
            return False
        if context.investigation_plan.strategy == "campaign_escalation_replan":
            return False
        if any(
            output.data.get("trace_action") == "trace_cluster_funds"
            for output in context.agent_outputs
        ):
            return False

        network_output = next(
            (
                output
                for output in reversed(context.agent_outputs)
                if output.agent_id == "network-agent"
                and output.data.get("campaign_detection")
            ),
            None,
        )
        if not network_output:
            return False

        campaign = network_output.data.get("campaign_detection") or {}
        return bool(
            campaign.get("detected")
            and (
                campaign.get("severity") in {"high", "critical"}
                or campaign.get("network_link_count", 0) >= 6
                or campaign.get("linked_transaction_count", 0) >= 4
            )
        )


class CaseManagerAgent(BaseInvestigationAgent):
    required_permissions = ["case.write", "approvals.request", "reports.write"]

    def __init__(
        self,
        identity: AgentIdentity,
        adk_runtime: AdkAgentRuntime | None = None,
    ) -> None:
        self.identity = identity
        self.adk_runtime = adk_runtime

    def run(self, context: InvestigationContext) -> AgentOutput:
        if (
            context.investigation_plan
            and context.investigation_plan.strategy == "pause_for_more_data"
        ):
            context.status = CaseStatus.OPEN
            context.approval_request = None
            summary = "Case paused for more data before continuing investigation."
        else:
            summary = ""

        if summary:
            pass
        elif (
            context.investigation_plan
            and context.investigation_plan.strategy == "lightweight_review"
        ):
            context.status = CaseStatus.CLOSED
            context.approval_request = None
            summary = "Low-risk case closed after planned compliance review."
        elif context.priority in {Priority.HIGH, Priority.CRITICAL}:
            context.status = CaseStatus.NEEDS_APPROVAL
            context.approval_request = ApprovalRequest(
                approval_id=self._next_approval_id(context),
                action="review_outbound_transfer_hold",
                reason=(
                    "The case contains a high-value overseas transfer with shared "
                    "device or IP signals. A human reviewer must approve any hold."
                ),
            )
        elif context.priority == Priority.MEDIUM:
            context.status = CaseStatus.NEEDS_APPROVAL
            context.approval_request = ApprovalRequest(
                approval_id=self._next_approval_id(context),
                action="manual_case_review",
                reason=(
                    "The case contains medium-risk anomaly signals. A human analyst "
                    "must review the case before it is closed; no autonomous hold is requested."
                ),
            )
        else:
            context.status = CaseStatus.OPEN

        if not summary:
            if context.approval_request:
                summary = (
                    f"Case moved to {context.status}. "
                    "Generated a human review request for analyst or supervisor decision."
                )
            else:
                summary = f"Case remains {context.status} for analyst review."

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=summary,
            confidence=0.9,
            data={
                "case_status": context.status,
                "approval_id": (
                    context.approval_request.approval_id if context.approval_request else None
                ),
                "adk_runtime": self._adk_binding(),
            },
        )
        context.agent_outputs.append(output)
        return output

    @staticmethod
    def _next_approval_id(context: InvestigationContext) -> str:
        if not context.approval_history:
            return f"appr-{context.case_id}"
        return f"appr-{context.case_id}-r{len(context.approval_history) + 1}"

    def _adk_binding(self) -> dict:
        if not self.adk_runtime:
            return {"enabled": False, "available": False, "framework": "google_adk"}
        return self.adk_runtime.bind_agent(
            self.identity,
            description="Manages fraud case state and human approval requests.",
            instruction=(
                "You are TraceLayer's Case Manager Agent. Convert investigation context "
                "into an auditable case state, request human review when policy requires "
                "it, and never execute a financial hold autonomously."
            ),
        ).as_dict()

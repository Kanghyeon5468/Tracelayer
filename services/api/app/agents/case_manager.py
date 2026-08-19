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

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Created {plan.strategy} investigation plan with "
                f"{len(plan.steps)} steps. {plan.rationale}"
            ),
            confidence=0.9,
            data={
                "planning_action": "dynamic_investigation_plan",
                "strategy": plan.strategy,
                "planned_agents": [step.agent_id for step in plan.steps],
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
                ],
            )

        if context.priority == Priority.LOW:
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}",
                strategy="lightweight_review",
                rationale="Low-risk cases only need compliance checks before staying open.",
                steps=[
                    completed_triage,
                    InvestigationPlanStep(
                        step_id="compliance",
                        agent_id="compliance-agent",
                        action="check_policy_and_pii",
                        reason="Confirm the low-risk case can remain in analyst review.",
                    ),
                    InvestigationPlanStep(
                        step_id="finish",
                        agent_id="case-manager-agent",
                        action="finish_case",
                        reason="Record the final case state without requesting approval.",
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

        return InvestigationPlan(
            plan_id=f"plan-{context.case_id}",
            strategy="deep_network_investigation",
            rationale=(
                "High-risk cases require network discovery, evidence collection, "
                "compliance review, and supervisor approval."
            ),
            steps=[
                completed_triage,
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
        elif context.priority in {Priority.HIGH, Priority.CRITICAL}:
            context.status = CaseStatus.NEEDS_APPROVAL
            context.approval_request = ApprovalRequest(
                approval_id=f"appr-{context.case_id}",
                action="review_outbound_transfer_hold",
                reason=(
                    "The case contains a high-value overseas transfer with shared "
                    "device or IP signals. A human reviewer must approve any hold."
                ),
            )
        elif context.priority == Priority.MEDIUM:
            context.status = CaseStatus.NEEDS_APPROVAL
            context.approval_request = ApprovalRequest(
                approval_id=f"appr-{context.case_id}",
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

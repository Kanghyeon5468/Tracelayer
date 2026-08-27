from __future__ import annotations

import json

from app.adk_runtime import AdkAgentRuntime
from app.agents.base import BaseInvestigationAgent
from app.connectors.reasoner import GeminiReasoner
from app.domain.models import (
    AgentIdentity,
    AgentOutput,
    ApprovalRequest,
    CaseStatus,
    InvestigationContext,
    InvestigationPlan,
    InvestigationPlanStep,
    PlanStepStatus,
    Priority,
)


class CaseManagerPlanningAgent(BaseInvestigationAgent):
    required_permissions = ["case.write", "reports.write"]
    ACTION_AGENT_MAP = {
        "score_transaction": "triage-agent",
        "compute_federated_intelligence": "triage-agent",
        "search_related_transactions": "network-agent",
        "trace_cluster_funds": "network-agent",
        "build_evidence_timeline": "evidence-agent",
        "check_policy_and_pii": "compliance-agent",
        "request_manual_review": "case-manager-agent",
        "request_supervisor_approval": "case-manager-agent",
        "request_more_data": "case-manager-agent",
        "pause_case": "case-manager-agent",
        "close_case": "case-manager-agent",
    }
    REQUIRED_ACTIONS_BY_STRATEGY = {
        "pause_for_more_data": {"request_more_data", "pause_case"},
        "lightweight_review": {"check_policy_and_pii", "close_case"},
        "manual_review": {
            "build_evidence_timeline",
            "check_policy_and_pii",
            "request_manual_review",
        },
        "manual_network_review": {
            "search_related_transactions",
            "build_evidence_timeline",
            "check_policy_and_pii",
            "request_manual_review",
        },
        "deep_network_investigation": {
            "search_related_transactions",
            "build_evidence_timeline",
            "check_policy_and_pii",
            "request_supervisor_approval",
        },
        "campaign_escalation_replan": {
            "search_related_transactions",
            "trace_cluster_funds",
            "build_evidence_timeline",
            "check_policy_and_pii",
            "request_supervisor_approval",
        },
        "human_feedback_replan": {
            "build_evidence_timeline",
            "check_policy_and_pii",
        },
    }

    def __init__(
        self,
        identity: AgentIdentity,
        adk_runtime: AdkAgentRuntime | None = None,
        reasoner: GeminiReasoner | None = None,
    ) -> None:
        self.identity = identity
        self.adk_runtime = adk_runtime
        self.reasoner = reasoner
        self.last_planner_metadata: dict = {}

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
                "planning_action": "gemini_validated_investigation_plan",
                "plan_phase": plan_phase,
                "strategy": plan.strategy,
                "planned_agents": [step.agent_id for step in plan.steps],
                "planned_actions": [step.action for step in plan.steps],
                "step_count": len(plan.steps),
                "planner_runtime": self.last_planner_metadata,
                "adk_runtime": self._adk_binding(),
            },
        )
        context.agent_outputs.append(output)
        return output

    def _build_plan(self, context: InvestigationContext) -> InvestigationPlan:
        baseline_plan = self._build_policy_baseline_plan(context)
        if not self._triage_was_completed(context):
            # Triage is mandatory before Gemini can choose deeper investigation steps.
            self.last_planner_metadata = {
                "mode": "policy_baseline",
                "gemini_proposal_used": False,
                "validation_status": "not_requested_before_triage",
                "fallback_strategy": baseline_plan.strategy,
            }
            return baseline_plan

        proposal_result = self._request_gemini_plan_proposal(context, baseline_plan)
        # Gemini proposes the plan, but policy validation keeps the workflow bounded.
        validated_plan = self._validate_gemini_plan(context, proposal_result, baseline_plan)
        if validated_plan:
            self.last_planner_metadata = {
                "mode": "gemini_structured_planner",
                "proposal_source": proposal_result.get("proposal_source"),
                "gemini_proposal_used": True,
                "validation_status": "approved",
                "fallback_strategy": baseline_plan.strategy,
                "raw_text_excerpt": proposal_result.get("raw_text_excerpt"),
            }
            return validated_plan

        self.last_planner_metadata = {
            "mode": "gemini_structured_planner",
            "proposal_source": proposal_result.get("proposal_source"),
            "gemini_proposal_used": False,
            "validation_status": "rejected",
            "rejection_reason": proposal_result.get("validation_error") or proposal_result.get("error"),
            "fallback_strategy": baseline_plan.strategy,
            "raw_text_excerpt": proposal_result.get("raw_text_excerpt"),
        }
        return baseline_plan

    def _build_policy_baseline_plan(self, context: InvestigationContext) -> InvestigationPlan:
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

        if context.human_feedback:
            return self._build_human_feedback_plan(context, completed_triage)

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

        if context.priority == Priority.MEDIUM and self._has_network_discovery_signal(context):
            return InvestigationPlan(
                plan_id=f"plan-{context.case_id}",
                strategy="manual_network_review",
                rationale=(
                    "Medium-risk cases with shared infrastructure or velocity signals need "
                    "network discovery before evidence, compliance, and analyst review."
                ),
                steps=[
                    completed_triage,
                    InvestigationPlanStep(
                        step_id="federated-intelligence",
                        agent_id="triage-agent",
                        action="compute_federated_intelligence",
                        reason=(
                            "Use the privacy-preserving Veritas signal already computed "
                            "during triage before network review."
                        ),
                        status=PlanStepStatus.COMPLETED,
                    ),
                    InvestigationPlanStep(
                        step_id="network",
                        agent_id="network-agent",
                        action="search_related_transactions",
                        reason="Find shared accounts, devices, IPs, emails, and counterparties.",
                        status=(
                            PlanStepStatus.COMPLETED
                            if context.related_transactions
                            else PlanStepStatus.PLANNED
                        ),
                    ),
                    InvestigationPlanStep(
                        step_id="evidence",
                        agent_id="evidence-agent",
                        action="build_evidence_timeline",
                        reason="Collect trigger, network, and federated evidence for manual review.",
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

    def _build_human_feedback_plan(
        self,
        context: InvestigationContext,
        completed_triage: InvestigationPlanStep,
    ) -> InvestigationPlan:
        feedback = context.human_feedback or "Reviewer requested additional case review."
        feedback_lower = feedback.lower()
        needs_network = any(
            token in feedback_lower
            for token in (
                "account",
                "device",
                "ip",
                "email",
                "counterparty",
                "network",
                "linked",
                "same",
                "shared",
                "cluster",
                "graph",
            )
        )
        approval_action = (
            "request_supervisor_approval"
            if context.priority in {Priority.HIGH, Priority.CRITICAL}
            else "request_manual_review"
        )
        approval_reason = (
            "Create a fresh supervisor approval after the feedback-directed investigation."
            if approval_action == "request_supervisor_approval"
            else "Create a fresh analyst review after the feedback-directed investigation."
        )
        steps = [completed_triage]
        if context.federated_risk_signal:
            steps.append(
                InvestigationPlanStep(
                    step_id="federated-intelligence",
                    agent_id="triage-agent",
                    action="compute_federated_intelligence",
                    reason="Keep the existing privacy-preserving federated signal in the resumed plan.",
                    status=PlanStepStatus.COMPLETED,
                )
            )
        if needs_network:
            steps.append(
                InvestigationPlanStep(
                    step_id="network-feedback",
                    agent_id="network-agent",
                    action="search_related_transactions",
                    reason=f"Reviewer feedback asks for network discovery: {feedback}",
                )
            )
        steps.extend(
            [
                InvestigationPlanStep(
                    step_id="evidence-feedback",
                    agent_id="evidence-agent",
                    action="build_evidence_timeline",
                    reason=f"Refresh the evidence timeline after reviewer feedback: {feedback}",
                ),
                InvestigationPlanStep(
                    step_id="compliance-feedback",
                    agent_id="compliance-agent",
                    action="check_policy_and_pii",
                    reason="Recheck PII and policy boundaries before creating a new approval.",
                ),
                InvestigationPlanStep(
                    step_id="approval-feedback",
                    agent_id="case-manager-agent",
                    action=approval_action,
                    reason=approval_reason,
                ),
            ]
        )
        return InvestigationPlan(
            plan_id=f"plan-{context.case_id}-human-feedback-r{len(context.approval_history) + 1}",
            strategy="human_feedback_replan",
            rationale=(
                "A human reviewer requested more evidence, so the Case Manager asks "
                "Gemini to choose a feedback-directed follow-up plan before issuing "
                "a new approval request."
            ),
            steps=steps,
        )

    def _request_gemini_plan_proposal(
        self,
        context: InvestigationContext,
        baseline_plan: InvestigationPlan,
    ) -> dict:
        fallback_proposal = self._plan_to_proposal(baseline_plan)
        if not self.reasoner:
            return {
                "proposal_source": "policy_baseline_no_reasoner",
                "proposal": fallback_proposal,
                "raw_text_excerpt": "",
            }
        return self.reasoner.propose_investigation_plan(
            self._planner_prompt(context, baseline_plan),
            fallback_proposal,
        )

    def _planner_prompt(
        self,
        context: InvestigationContext,
        baseline_plan: InvestigationPlan,
    ) -> str:
        state = {
            "case_id": context.case_id,
            "risk_score": context.risk_score,
            "priority": str(context.priority),
            "risk_flags": context.trigger_transaction.risk_flags,
            "missing_data": self._requires_more_data(context),
            "related_transaction_count": len(context.related_transactions),
            "network_link_count": len(context.network_links),
            "campaign_detection": self._latest_campaign_detection(context),
            "human_feedback": context.human_feedback,
            "federated_signal_available": context.federated_risk_signal is not None,
            "federated_risk_score": (
                context.federated_risk_signal.federated_risk_score
                if context.federated_risk_signal
                else None
            ),
            "available_actions": self.ACTION_AGENT_MAP,
            "policy_constraints": [
                "Return only JSON.",
                "Do not invent actions outside available_actions.",
                "Never execute or approve a financial hold autonomously.",
                "High and critical risk cases require request_supervisor_approval.",
                "Medium risk cases require request_manual_review.",
                "Medium risk cases with shared infrastructure or velocity signals must include search_related_transactions.",
                "Missing-data cases must request_more_data and pause_case.",
                "Low-risk cases may only run compliance and close_case after triage.",
                "Campaign clusters should include trace_cluster_funds after network discovery.",
                "Human feedback cases must route through the planner; if feedback asks for accounts, devices, IPs, emails, clusters, or graph discovery, run search_related_transactions before evidence.",
            ],
            "baseline_policy_plan": self._plan_to_proposal(baseline_plan),
        }
        return (
            "You are TraceLayer's Gemini Case Manager Planner. Propose the next "
            "investigation plan for a fraud agent fleet. You only choose a strategy "
            "and ordered actions; PolicyEngine and Agent Gateway will validate and "
            "execute approved tools. Return exactly one JSON object with keys: "
            "strategy, rationale, steps. steps must be an array of objects with "
            f"action and reason. Case state: {json.dumps(state, sort_keys=True, default=str)}"
        )

    def _validate_gemini_plan(
        self,
        context: InvestigationContext,
        proposal_result: dict,
        baseline_plan: InvestigationPlan,
    ) -> InvestigationPlan | None:
        proposal = proposal_result.get("proposal")
        if not isinstance(proposal, dict):
            proposal_result["validation_error"] = "Proposal payload was not an object."
            return None

        strategy = str(proposal.get("strategy") or baseline_plan.strategy)
        steps_payload = proposal.get("steps")
        if not isinstance(steps_payload, list):
            proposal_result["validation_error"] = "Proposal steps were not a list."
            return None

        proposed_actions = self._proposal_actions(steps_payload)
        invalid_actions = sorted(set(proposed_actions) - set(self.ACTION_AGENT_MAP))
        if invalid_actions:
            proposal_result["validation_error"] = (
                f"Proposal included unapproved actions: {', '.join(invalid_actions)}."
            )
            return None

        expected_strategy = baseline_plan.strategy
        if self._network_campaign_requires_replan(context):
            expected_strategy = "campaign_escalation_replan"
        if strategy != expected_strategy:
            proposal_result["validation_error"] = (
                f"Proposal strategy {strategy} did not match policy strategy {expected_strategy}."
            )
            return None

        required_actions = self.REQUIRED_ACTIONS_BY_STRATEGY.get(expected_strategy, set())
        if expected_strategy == "human_feedback_replan":
            required_actions = {
                step.action
                for step in baseline_plan.steps
                if step.status == PlanStepStatus.PLANNED
            }
        missing_actions = sorted(required_actions - set(proposed_actions))
        if missing_actions:
            proposal_result["validation_error"] = (
                f"Proposal missed required actions: {', '.join(missing_actions)}."
            )
            return None

        forbidden_error = self._forbidden_action_error(context, proposed_actions)
        if forbidden_error:
            proposal_result["validation_error"] = forbidden_error
            return None

        normalized_actions = self._normalize_actions(context, expected_strategy, proposed_actions)
        rationale = str(proposal.get("rationale") or baseline_plan.rationale)
        return self._plan_from_actions(
            context=context,
            baseline_plan=baseline_plan,
            strategy=expected_strategy,
            rationale=rationale,
            actions=normalized_actions,
            proposal_steps=steps_payload,
        )

    @staticmethod
    def _proposal_actions(steps_payload: list) -> list[str]:
        actions: list[str] = []
        for step in steps_payload:
            if isinstance(step, str):
                action = step
            elif isinstance(step, dict):
                action = step.get("action")
            else:
                continue
            if action:
                actions.append(str(action))
        return actions

    def _forbidden_action_error(
        self,
        context: InvestigationContext,
        actions: list[str],
    ) -> str | None:
        action_set = set(actions)
        if self._requires_more_data(context):
            allowed = {"request_more_data", "pause_case"}
            forbidden = sorted(action_set - allowed - {"score_transaction"})
            if forbidden:
                return f"Missing-data proposal overreached with: {', '.join(forbidden)}."
        if context.priority == Priority.LOW:
            forbidden = sorted(
                action_set
                & {
                    "search_related_transactions",
                    "trace_cluster_funds",
                    "request_manual_review",
                    "request_supervisor_approval",
                }
            )
            if forbidden:
                return f"Low-risk proposal overreached with: {', '.join(forbidden)}."
        if context.priority == Priority.MEDIUM and "request_supervisor_approval" in action_set:
            return "Medium-risk proposal escalated to supervisor hold approval."
        if context.priority in {Priority.HIGH, Priority.CRITICAL} and "close_case" in action_set:
            return "High-risk proposal tried to close without human approval."
        return None

    def _normalize_actions(
        self,
        context: InvestigationContext,
        strategy: str,
        proposed_actions: list[str],
    ) -> list[str]:
        actions = [action for action in proposed_actions if action != "score_transaction"]
        if strategy in {"deep_network_investigation", "campaign_escalation_replan"}:
            actions = self._ordered_subset(
                actions,
                [
                    "compute_federated_intelligence",
                    "search_related_transactions",
                    "trace_cluster_funds",
                    "build_evidence_timeline",
                    "check_policy_and_pii",
                    "request_supervisor_approval",
                ],
            )
        elif strategy == "manual_network_review":
            actions = self._ordered_subset(
                actions,
                [
                    "compute_federated_intelligence",
                    "search_related_transactions",
                    "build_evidence_timeline",
                    "check_policy_and_pii",
                    "request_manual_review",
                ],
            )
        elif strategy == "manual_review":
            actions = self._ordered_subset(
                actions,
                [
                    "compute_federated_intelligence",
                    "build_evidence_timeline",
                    "check_policy_and_pii",
                    "request_manual_review",
                ],
            )
        elif strategy == "lightweight_review":
            actions = self._ordered_subset(actions, ["check_policy_and_pii", "close_case"])
        elif strategy == "pause_for_more_data":
            actions = self._ordered_subset(actions, ["request_more_data", "pause_case"])
        elif strategy == "human_feedback_replan":
            actions = self._ordered_subset(
                actions,
                [
                    "compute_federated_intelligence",
                    "search_related_transactions",
                    "trace_cluster_funds",
                    "build_evidence_timeline",
                    "check_policy_and_pii",
                    "request_manual_review",
                    "request_supervisor_approval",
                ],
            )

        if context.federated_risk_signal and strategy in {
            "manual_review",
            "manual_network_review",
            "deep_network_investigation",
            "campaign_escalation_replan",
        }:
            actions = self._ensure_action(actions, "compute_federated_intelligence", before=0)
        if strategy == "campaign_escalation_replan":
            network_index = actions.index("search_related_transactions")
            trace_index = actions.index("trace_cluster_funds")
            if trace_index < network_index:
                actions.remove("trace_cluster_funds")
                actions.insert(network_index + 1, "trace_cluster_funds")
        return ["score_transaction", *actions]

    @staticmethod
    def _ordered_subset(actions: list[str], order: list[str]) -> list[str]:
        action_set = set(actions)
        return [action for action in order if action in action_set]

    @staticmethod
    def _ensure_action(actions: list[str], action: str, before: int) -> list[str]:
        if action in actions:
            return actions
        updated = list(actions)
        updated.insert(before, action)
        return updated

    def _plan_from_actions(
        self,
        context: InvestigationContext,
        baseline_plan: InvestigationPlan,
        strategy: str,
        rationale: str,
        actions: list[str],
        proposal_steps: list,
    ) -> InvestigationPlan:
        reason_by_action = self._proposal_reason_by_action(proposal_steps)
        baseline_reason_by_action = {step.action: step.reason for step in baseline_plan.steps}
        steps: list[InvestigationPlanStep] = []
        for action in actions:
            status = PlanStepStatus.PLANNED
            if action in {"score_transaction", "compute_federated_intelligence"}:
                status = PlanStepStatus.COMPLETED
            if (
                action == "search_related_transactions"
                and context.related_transactions
                and strategy != "human_feedback_replan"
            ):
                status = PlanStepStatus.COMPLETED

            steps.append(
                InvestigationPlanStep(
                    step_id=self._step_id_for_action(action),
                    agent_id=self.ACTION_AGENT_MAP[action],
                    action=action,
                    reason=reason_by_action.get(action)
                    or baseline_reason_by_action.get(action)
                    or f"Gemini planner selected {action}.",
                    status=status,
                )
            )

        return InvestigationPlan(
            plan_id=self._plan_id_for_strategy(context, strategy),
            strategy=strategy,
            rationale=rationale,
            steps=steps,
        )

    @staticmethod
    def _proposal_reason_by_action(proposal_steps: list) -> dict[str, str]:
        reasons: dict[str, str] = {}
        for step in proposal_steps:
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            reason = step.get("reason")
            if action and reason:
                reasons[str(action)] = str(reason)
        return reasons

    @staticmethod
    def _step_id_for_action(action: str) -> str:
        return action.replace("_", "-").replace("score-transaction", "triage")

    @staticmethod
    def _plan_id_for_strategy(context: InvestigationContext, strategy: str) -> str:
        if strategy == "campaign_escalation_replan":
            return f"plan-{context.case_id}-campaign-escalation"
        if strategy == "human_feedback_replan":
            return f"plan-{context.case_id}-human-feedback-r{len(context.approval_history) + 1}"
        return f"plan-{context.case_id}"

    @staticmethod
    def _plan_to_proposal(plan: InvestigationPlan) -> dict:
        return {
            "strategy": plan.strategy,
            "rationale": plan.rationale,
            "steps": [
                {
                    "action": step.action,
                    "reason": step.reason,
                }
                for step in plan.steps
                if step.action != "replan_after_triage"
            ],
        }

    @staticmethod
    def _requires_more_data(context: InvestigationContext) -> bool:
        return "missing_data" in context.trigger_transaction.risk_flags

    @staticmethod
    def _has_network_discovery_signal(context: InvestigationContext) -> bool:
        return bool(
            {
                "shared_account",
                "shared_counterparty",
                "shared_device",
                "shared_email",
                "shared_ip",
                "velocity",
            }
            & set(context.trigger_transaction.risk_flags)
        )

    @staticmethod
    def _triage_was_completed(context: InvestigationContext) -> bool:
        if context.force_retriage:
            return False
        return any(output.agent_id == "triage-agent" for output in context.agent_outputs)

    @staticmethod
    def _latest_campaign_detection(context: InvestigationContext) -> dict | None:
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
            return None
        return network_output.data.get("campaign_detection")

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

        campaign = CaseManagerPlanningAgent._latest_campaign_detection(context) or {}
        return bool(
            campaign.get("detected")
            and (
                campaign.get("severity") in {"high", "critical"}
                or campaign.get("network_link_count", 0) >= 6
                or campaign.get("linked_transaction_count", 0) >= 4
            )
        )

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
            context.status = CaseStatus.PAUSED
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

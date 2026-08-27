from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class CaseStatus(StrEnum):
    OPEN = "open"
    PAUSED = "paused"
    NEEDS_APPROVAL = "needs_approval"
    CLOSED = "closed"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PlanStepStatus(StrEnum):
    PLANNED = "planned"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class InvestigationPlanStep(BaseModel):
    step_id: str
    agent_id: str
    action: str
    reason: str
    status: PlanStepStatus = PlanStepStatus.PLANNED


class InvestigationPlan(BaseModel):
    plan_id: str
    strategy: str
    rationale: str
    created_by_agent_id: str = "case-manager-agent"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    steps: list[InvestigationPlanStep] = Field(default_factory=list)


class RiskPolicy(BaseModel):
    policy_id: str = "default"
    medium_threshold: int = Field(default=40, ge=0, le=100)
    high_threshold: int = Field(default=70, ge=0, le=100)
    critical_threshold: int = Field(default=90, ge=0, le=100)
    updated_by: str = "system"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_ordering(self) -> "RiskPolicy":
        if not self.medium_threshold < self.high_threshold < self.critical_threshold:
            raise ValueError(
                "Risk thresholds must be ordered as medium < high < critical."
            )
        return self

    def priority_for_score(self, score: int) -> Priority:
        if score >= self.critical_threshold:
            return Priority.CRITICAL
        if score >= self.high_threshold:
            return Priority.HIGH
        if score >= self.medium_threshold:
            return Priority.MEDIUM
        return Priority.LOW


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ActorRole(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    SUPERVISOR = "supervisor"
    COMPLIANCE = "compliance"
    SERVICE = "service"


class Transaction(BaseModel):
    transaction_id: str
    customer_id: str
    account_id: str
    counterparty_account_id: str
    amount: float
    currency: str
    country: str
    channel: str
    device_id: str
    ip_address: str
    email: str
    timestamp: datetime
    status: str
    risk_flags: list[str] = Field(default_factory=list)
    external_memo: str | None = None


class Customer(BaseModel):
    customer_id: str
    name: str
    home_country: str
    segment: str
    kyc_risk: str
    emails: list[str]
    primary_account_id: str


class AgentIdentity(BaseModel):
    agent_id: str
    display_name: str
    version: str
    service_account: str
    permissions: list[str]
    data_access: list[DataClassification] = Field(
        default_factory=lambda: [DataClassification.INTERNAL]
    )
    owner_department: str = "Fraud Operations"
    lifecycle_status: str = "approved"
    approved_version: str | None = None
    deployed_runtime: str = "cloud-run-adk-runner"
    allowed_tools: list[str] = Field(default_factory=list)
    data_region: str = "us-central1"
    registry_resource: str | None = None
    agent_principal: str | None = None
    identity_provider: str = "google-cloud-iam"
    managed_gateway_policy: str = "audit-only"
    health_status: str = "healthy"
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentOutput(BaseModel):
    agent_id: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    data: dict[str, Any] = Field(default_factory=dict)
    guardrail_findings: list[str] = Field(default_factory=list)


class EvidenceEvent(BaseModel):
    timestamp: datetime
    event_type: str
    description: str
    source: str
    related_transaction_id: str | None = None


class NetworkLink(BaseModel):
    source: str
    target: str
    relationship: str
    evidence_transaction_id: str


class ComplianceFinding(BaseModel):
    finding_id: str
    severity: str
    description: str
    required_action: str


class ApprovalRequest(BaseModel):
    approval_id: str
    action: str
    reason: str
    status: str = "pending"
    requested_by_agent_id: str = "case-manager-agent"
    decided_by: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None


class ApprovalDecisionRequest(BaseModel):
    approval_id: str
    decision: str = Field(pattern="^(approved|denied|more_evidence)$")
    reason: str


class MissingDataRequest(BaseModel):
    reason: str = Field(
        default=(
            "External system supplied missing beneficiary, amount, device, and IP records."
        ),
        min_length=8,
        max_length=500,
    )


class LongRunningAdvanceRequest(BaseModel):
    stage: str = Field(default="next", pattern="^(next|day3|day7|day14)$")
    note: str | None = Field(default=None, max_length=500)


class PubSubPushMessage(BaseModel):
    data: str
    message_id: str | None = Field(default=None, alias="messageId")
    publish_time: str | None = Field(default=None, alias="publishTime")
    attributes: dict[str, str] = Field(default_factory=dict)


class PubSubPushEnvelope(BaseModel):
    message: PubSubPushMessage
    subscription: str | None = None


class PendingApprovalSummary(BaseModel):
    case_id: str
    approval_id: str
    action: str
    reason: str
    risk_score: int
    priority: Priority
    trigger_transaction_id: str
    customer_id: str
    requested_by_agent_id: str
    memory_snapshot_id: str | None = None


class ApprovalLogEntry(BaseModel):
    case_id: str
    approval_id: str
    approval_status: str
    case_status: CaseStatus
    action: str
    reason: str
    risk_score: int
    priority: Priority
    trigger_transaction_id: str
    customer_id: str
    requested_by_agent_id: str
    decided_by: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    memory_snapshot_id: str | None = None


class InvestigationJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InvestigationJob(BaseModel):
    job_id: str
    status: InvestigationJobStatus
    transaction_id: str | None = None
    case_id: str | None = None
    pubsub_topic: str
    pubsub_message_id: str
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RequestContext(BaseModel):
    actor_id: str
    role: ActorRole
    scopes: list[str] = Field(default_factory=list)
    request_id: str
    trace_id: str | None = None
    cloud_trace: str | None = None
    source_ip: str | None = None


class GuardrailFinding(BaseModel):
    finding_id: str
    severity: str
    control: str
    description: str
    blocked: bool = False


class FederatedRiskSignal(BaseModel):
    signal_id: str
    model_family: str
    federated_risk_score: int = Field(ge=0, le=100)
    campaign_signature: str
    participating_nodes: list[str]
    secure_aggregation: dict[str, Any]
    differential_privacy: dict[str, Any]
    provenance_hash: str
    explanation: str
    node_indicators: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime
    case_id: str | None = None
    actor_id: str
    actor_type: str
    action: str
    resource: str
    decision: str
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str
    event_hash: str


class InvestigationContext(BaseModel):
    case_id: str
    trigger_transaction: Transaction
    customer: Customer
    related_transactions: list[Transaction] = Field(default_factory=list)
    network_search_metadata: dict[str, Any] = Field(default_factory=dict)
    risk_score: int = 0
    priority: Priority = Priority.LOW
    evidence_timeline: list[EvidenceEvent] = Field(default_factory=list)
    network_links: list[NetworkLink] = Field(default_factory=list)
    compliance_findings: list[ComplianceFinding] = Field(default_factory=list)
    approval_request: ApprovalRequest | None = None
    approval_history: list[ApprovalRequest] = Field(default_factory=list)
    investigation_plan: InvestigationPlan | None = None
    agent_outputs: list[AgentOutput] = Field(default_factory=list)
    guardrail_findings: list[GuardrailFinding] = Field(default_factory=list)
    federated_risk_signal: FederatedRiskSignal | None = None
    status: CaseStatus = CaseStatus.OPEN
    memory_snapshot_id: str | None = None
    audit_chain_tip: str | None = None
    human_feedback: str | None = None
    force_retriage: bool = False


class InvestigationRequest(BaseModel):
    transaction_id: str = "tx-9001"


class ScenarioInvestigationRequest(BaseModel):
    prompt: str = Field(min_length=12, max_length=3000)
    scenario_name: str | None = Field(default=None, max_length=80)


class InvestigationCase(BaseModel):
    case_id: str
    status: CaseStatus
    trigger_transaction_id: str
    customer_id: str
    risk_score: int
    priority: Priority
    agent_outputs: list[AgentOutput]
    network_links: list[NetworkLink]
    evidence_timeline: list[EvidenceEvent]
    compliance_findings: list[ComplianceFinding]
    investigation_plan: InvestigationPlan | None = None
    approval_request: ApprovalRequest | None = None
    approval_history: list[ApprovalRequest] = Field(default_factory=list)
    report_path: str | None = None
    guardrail_findings: list[GuardrailFinding] = Field(default_factory=list)
    federated_risk_signal: FederatedRiskSignal | None = None
    memory_snapshot_id: str | None = None
    audit_chain_tip: str | None = None
    human_feedback: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CaseStatus(StrEnum):
    OPEN = "open"
    NEEDS_APPROVAL = "needs_approval"
    CLOSED = "closed"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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
    decision: str = Field(pattern="^(approved|denied)$")
    reason: str


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


class RequestContext(BaseModel):
    actor_id: str
    role: ActorRole
    scopes: list[str] = Field(default_factory=list)
    request_id: str
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
    risk_score: int = 0
    priority: Priority = Priority.LOW
    evidence_timeline: list[EvidenceEvent] = Field(default_factory=list)
    network_links: list[NetworkLink] = Field(default_factory=list)
    compliance_findings: list[ComplianceFinding] = Field(default_factory=list)
    approval_request: ApprovalRequest | None = None
    agent_outputs: list[AgentOutput] = Field(default_factory=list)
    guardrail_findings: list[GuardrailFinding] = Field(default_factory=list)
    federated_risk_signal: FederatedRiskSignal | None = None
    status: CaseStatus = CaseStatus.OPEN
    memory_snapshot_id: str | None = None
    audit_chain_tip: str | None = None


class InvestigationRequest(BaseModel):
    transaction_id: str = "tx-9001"


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
    approval_request: ApprovalRequest | None = None
    report_path: str | None = None
    guardrail_findings: list[GuardrailFinding] = Field(default_factory=list)
    federated_risk_signal: FederatedRiskSignal | None = None
    memory_snapshot_id: str | None = None
    audit_chain_tip: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

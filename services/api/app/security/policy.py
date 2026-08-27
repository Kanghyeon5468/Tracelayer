from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ActorRole, AgentIdentity, DataClassification, RequestContext


ROLE_SCOPES: dict[ActorRole, set[str]] = {
    ActorRole.VIEWER: {"cases.read", "agents.read"},
    ActorRole.ANALYST: {
        "agents.read",
        "cases.read",
        "cases.investigate",
        "evidence.read",
        "reports.read",
        "risk_policy.read",
    },
    ActorRole.SUPERVISOR: {
        "agents.read",
        "cases.read",
        "cases.investigate",
        "evidence.read",
        "reports.read",
        "approvals.decide",
        "risk_policy.read",
        "risk_policy.update",
    },
    ActorRole.COMPLIANCE: {
        "agents.read",
        "cases.read",
        "evidence.read",
        "reports.read",
        "compliance.read",
        "audit.read",
        "risk_policy.read",
    },
    ActorRole.SERVICE: {"*"},
}


PERMISSION_TO_CLASSIFICATION: dict[str, DataClassification] = {
    "transactions.read": DataClassification.RESTRICTED,
    "bigquery.transactions.read": DataClassification.RESTRICTED,
    "graph.search": DataClassification.CONFIDENTIAL,
    "risk.score": DataClassification.CONFIDENTIAL,
    "policies.read": DataClassification.INTERNAL,
    "evidence.write": DataClassification.CONFIDENTIAL,
    "pii.redact": DataClassification.RESTRICTED,
    "case.review": DataClassification.CONFIDENTIAL,
    "case.write": DataClassification.CONFIDENTIAL,
    "approvals.request": DataClassification.CONFIDENTIAL,
    "reports.write": DataClassification.CONFIDENTIAL,
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    """Small zero-trust policy engine for demo and testable enterprise controls."""

    def actor_can(self, request: RequestContext, scope: str) -> PolicyDecision:
        role_scopes = set(request.scopes) | ROLE_SCOPES.get(request.role, set())
        if "*" in role_scopes or scope in role_scopes:
            return PolicyDecision(True, f"{request.role} has {scope}.")
        return PolicyDecision(False, f"{request.role} does not have {scope}.")

    def agent_can_run(
        self,
        identity: AgentIdentity,
        required_permissions: list[str],
    ) -> PolicyDecision:
        missing_permissions = sorted(set(required_permissions) - set(identity.permissions))
        if missing_permissions:
            return PolicyDecision(
                False,
                f"{identity.agent_id} lacks permissions: {', '.join(missing_permissions)}.",
            )

        for permission in required_permissions:
            classification = PERMISSION_TO_CLASSIFICATION.get(
                permission,
                DataClassification.INTERNAL,
            )
            if classification not in identity.data_access:
                return PolicyDecision(
                    False,
                    f"{identity.agent_id} lacks {classification} data access for {permission}.",
                )

        return PolicyDecision(True, f"{identity.agent_id} passed least-privilege checks.")

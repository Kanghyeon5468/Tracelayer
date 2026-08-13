from __future__ import annotations

from app.agents.base import BaseInvestigationAgent
from app.connectors.reasoner import GeminiReasoner
from app.domain.models import AgentIdentity, AgentOutput, InvestigationContext, RiskPolicy
from app.domain.policies import classify_transfer_amount
from app.federation.engine import VeritasFederatedRiskEngine


class TriageAgent(BaseInvestigationAgent):
    required_permissions = ["transactions.read", "risk.score"]

    def __init__(
        self,
        identity: AgentIdentity,
        reasoner: GeminiReasoner,
        federated_engine: VeritasFederatedRiskEngine | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.identity = identity
        self.reasoner = reasoner
        self.federated_engine = federated_engine or VeritasFederatedRiskEngine()
        self.risk_policy = risk_policy or RiskPolicy()

    def run(self, context: InvestigationContext) -> AgentOutput:
        transaction = context.trigger_transaction
        score = 20
        factors = [{"name": "base_review_score", "points": 20, "reason": "Flagged transaction."}]

        if classify_transfer_amount(transaction.amount) == "high":
            score += 30
            factors.append(
                {
                    "name": "high_value_transfer",
                    "points": 30,
                    "reason": "Transfer amount is above the enhanced-review threshold.",
                }
            )
        if transaction.country != context.customer.home_country:
            score += 20
            factors.append(
                {
                    "name": "new_or_foreign_country",
                    "points": 20,
                    "reason": "Destination country differs from the customer's home country.",
                }
            )
        if transaction.channel == "wire":
            score += 10
            factors.append(
                {
                    "name": "wire_channel",
                    "points": 10,
                    "reason": "Wire transfers have higher irreversible settlement risk.",
                }
            )
        if "unusual_hour" in transaction.risk_flags:
            score += 10
            factors.append(
                {
                    "name": "unusual_hour",
                    "points": 10,
                    "reason": "The transaction was initiated outside normal customer behavior.",
                }
            )
        if "shared_device" in transaction.risk_flags or "shared_ip" in transaction.risk_flags:
            score += 10
            factors.append(
                {
                    "name": "shared_infrastructure",
                    "points": 10,
                    "reason": "Device or IP overlap suggests coordinated activity.",
                }
            )

        federated_signal = self.federated_engine.score_transaction(transaction)
        context.federated_risk_signal = federated_signal
        if federated_signal.federated_risk_score >= 80:
            score += 15
            factors.append(
                {
                    "name": "veritas_federated_risk_signal",
                    "points": 15,
                    "reason": (
                        "Embedded Veritas federation produced a high cross-institution "
                        "risk score without moving raw customer records."
                    ),
                }
            )
        elif federated_signal.federated_risk_score >= 65:
            score += 8
            factors.append(
                {
                    "name": "veritas_federated_risk_signal",
                    "points": 8,
                    "reason": "Embedded Veritas federation produced an elevated risk score.",
                }
            )

        context.risk_score = min(score, 100)
        context.priority = self.risk_policy.priority_for_score(context.risk_score)

        prompt = (
            "Explain the fraud risk pattern for a flagged transaction using concise, "
            "auditable language. Include why a human reviewer should inspect the case. "
            f"Transaction features: {self._model_safe_transaction_features(context)}"
        )
        model_summary = self.reasoner.summarize_pattern(prompt)
        context.guardrail_findings.extend(self.reasoner.last_guardrail_findings)

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Assigned {context.priority} priority with risk score {context.risk_score}. "
                f"Embedded Veritas signal {federated_signal.signal_id} scored "
                f"{federated_signal.federated_risk_score}/100 with campaign signature "
                f"{federated_signal.campaign_signature}. {model_summary}"
            ),
            confidence=0.86,
            data={
                "risk_score": context.risk_score,
                "priority": context.priority,
                "risk_flags": transaction.risk_flags,
                "risk_factors": factors,
                "federated_signal_id": federated_signal.signal_id,
                "federated_risk_score": federated_signal.federated_risk_score,
                "campaign_signature": federated_signal.campaign_signature,
                "dp_epsilon": federated_signal.differential_privacy["epsilon"],
                "risk_policy": {
                    "policy_id": self.risk_policy.policy_id,
                    "medium_threshold": self.risk_policy.medium_threshold,
                    "high_threshold": self.risk_policy.high_threshold,
                    "critical_threshold": self.risk_policy.critical_threshold,
                },
            },
        )
        context.agent_outputs.append(output)
        return output

    @staticmethod
    def _model_safe_transaction_features(context: InvestigationContext) -> dict:
        transaction = context.trigger_transaction
        return {
            "amount": transaction.amount,
            "currency": transaction.currency,
            "destination_country": transaction.country,
            "customer_home_country": context.customer.home_country,
            "channel": transaction.channel,
            "utc_hour": transaction.timestamp.hour,
            "status": transaction.status,
            "risk_flags": transaction.risk_flags,
            "related_transaction_count": len(context.related_transactions),
        }

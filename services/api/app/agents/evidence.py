from __future__ import annotations

from app.agents.base import BaseInvestigationAgent
from app.domain.models import AgentIdentity, AgentOutput, EvidenceEvent, InvestigationContext


class EvidenceAgent(BaseInvestigationAgent):
    required_permissions = ["transactions.read", "policies.read", "evidence.write"]

    def __init__(self, identity: AgentIdentity, policy_text: str) -> None:
        self.identity = identity
        self.policy_text = policy_text

    def run(self, context: InvestigationContext) -> AgentOutput:
        events: list[EvidenceEvent] = [
            EvidenceEvent(
                timestamp=context.trigger_transaction.timestamp,
                event_type="trigger_transaction",
                description=(
                    f"Flagged {context.trigger_transaction.channel} transfer for "
                    f"{context.trigger_transaction.amount:.2f} "
                    f"{context.trigger_transaction.currency} to "
                    f"{context.trigger_transaction.country}."
                ),
                source="transaction_store",
                related_transaction_id=context.trigger_transaction.transaction_id,
            )
        ]

        for transaction in context.related_transactions:
            events.append(
                EvidenceEvent(
                    timestamp=transaction.timestamp,
                    event_type="related_transaction",
                    description=(
                        f"Related transaction {transaction.transaction_id} used account "
                        f"{transaction.account_id}, device {transaction.device_id}, "
                        f"IP {transaction.ip_address}, and counterparty "
                        f"{transaction.counterparty_account_id}."
                    ),
                    source="related_transaction_search",
                    related_transaction_id=transaction.transaction_id,
                )
            )

        if context.federated_risk_signal:
            signal = context.federated_risk_signal
            events.append(
                EvidenceEvent(
                    timestamp=context.trigger_transaction.timestamp,
                    event_type="federated_risk_signal",
                    description=(
                        f"Embedded Veritas federation produced risk score "
                        f"{signal.federated_risk_score}/100 with campaign signature "
                        f"{signal.campaign_signature} across "
                        f"{len(signal.participating_nodes)} institutional nodes."
                    ),
                    source="embedded_veritas_federation",
                    related_transaction_id=context.trigger_transaction.transaction_id,
                )
            )

        context.evidence_timeline = sorted(events, key=lambda event: event.timestamp)

        output = AgentOutput(
            agent_id=self.identity.agent_id,
            summary=(
                f"Built an evidence timeline with {len(context.evidence_timeline)} events "
                "and matched it against high-risk transfer, shared device, and human "
                "approval policies."
            ),
            confidence=0.88,
            data={
                "event_count": len(context.evidence_timeline),
                "policy_excerpt_names": [
                    "High-Risk Wire Transfers",
                    "Shared Device or IP",
                    "Human Approval",
                ],
                "federated_signal_id": (
                    context.federated_risk_signal.signal_id
                    if context.federated_risk_signal
                    else None
                ),
            },
        )
        context.agent_outputs.append(output)
        return output

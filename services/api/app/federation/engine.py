from __future__ import annotations

import hashlib
import json
import math
import random

from app.domain.models import Transaction
from app.federation.dp import RDPAccountant, clip_update, privatize
from app.federation.models import FederatedNodeUpdate, FederatedRiskSignal
from app.federation.secure_agg import secure_aggregate


class VeritasFederatedRiskEngine:
    """Embedded Veritas-style federated fraud intelligence for TraceLayer."""

    def __init__(
        self,
        *,
        max_norm: float = 3.0,
        noise_multiplier: float = 0.5,
        delta: float = 1e-5,
        sample_rate: float = 0.4,
    ) -> None:
        self.max_norm = max_norm
        self.noise_multiplier = noise_multiplier
        self.delta = delta
        self.sample_rate = sample_rate

    def score_transaction(self, transaction: Transaction) -> FederatedRiskSignal:
        raw_updates = self._simulate_institution_updates(transaction)
        private_updates = {
            update.node_id: self._privatize_update(transaction, update.clipped_update, update.node_id)
            for update in raw_updates
        }
        aggregate_sum, secure_metadata = secure_aggregate(
            private_updates,
            session_id=transaction.transaction_id,
            deterministic=True,
        )
        aggregate_mean = [value / len(private_updates) for value in aggregate_sum]

        accountant = RDPAccountant()
        accountant.step(self.noise_multiplier, self.sample_rate)
        dp_summary = accountant.summary(self.delta, self.noise_multiplier, self.sample_rate)

        score = self._risk_score_from_vector(aggregate_mean)
        indicators = sorted({item for update in raw_updates for item in update.local_risk_indicators})
        signature = self._campaign_signature(transaction, aggregate_mean, indicators)
        provenance_hash = self._provenance_hash(
            transaction.transaction_id,
            aggregate_mean,
            dp_summary,
            secure_metadata,
        )

        return FederatedRiskSignal(
            signal_id=f"veritas-{transaction.transaction_id}",
            model_family="veritas_embedded_federated_fraud_v1",
            federated_risk_score=score,
            campaign_signature=signature,
            participating_nodes=[update.node_id for update in raw_updates],
            secure_aggregation=secure_metadata,
            differential_privacy=dp_summary,
            provenance_hash=provenance_hash,
            explanation=(
                "Embedded Veritas federation combined privacy-preserving node updates "
                "from bank, insurer, and fintech participants. Raw rows stayed local; "
                "TraceLayer received only a secure aggregate risk signal."
            ),
            node_indicators=indicators,
        )

    def _simulate_institution_updates(self, transaction: Transaction) -> list[FederatedNodeUpdate]:
        base = self._feature_vector(transaction)
        node_specs = [
            ("bank-na-01", "bank", [0.10, 0.05, 0.08, 0.02, 0.00]),
            ("insurer-claims-02", "insurer", [0.04, 0.12, 0.02, 0.03, 0.04]),
            ("fintech-wallet-03", "fintech", [0.08, 0.03, 0.12, 0.06, 0.03]),
        ]
        updates: list[FederatedNodeUpdate] = []
        for node_id, institution_type, bias in node_specs:
            local = [feature + delta for feature, delta in zip(base, bias)]
            updates.append(
                FederatedNodeUpdate(
                    node_id=node_id,
                    institution_type=institution_type,
                    local_sample_count=1200 + len(node_id) * 17,
                    clipped_update=clip_update(local, self.max_norm),
                    local_risk_indicators=self._node_indicators(transaction, institution_type),
                )
            )
        return updates

    def _feature_vector(self, transaction: Transaction) -> list[float]:
        amount_signal = min(transaction.amount / 20_000.0, 1.5)
        foreign_signal = 1.0 if transaction.country != "US" else 0.0
        wire_signal = 1.0 if transaction.channel == "wire" else 0.0
        risk_flag_signal = min(len(transaction.risk_flags) / 4.0, 1.0)
        velocity_signal = 1.0 if "velocity" in transaction.risk_flags else 0.35
        return [amount_signal, foreign_signal, wire_signal, risk_flag_signal, velocity_signal]

    def _node_indicators(self, transaction: Transaction, institution_type: str) -> list[str]:
        indicators: list[str] = []
        if transaction.amount >= 10_000:
            indicators.append(f"{institution_type}:high_value_transfer")
        if transaction.country != "US":
            indicators.append(f"{institution_type}:cross_border_signal")
        if transaction.channel == "wire":
            indicators.append(f"{institution_type}:irreversible_payment_channel")
        if transaction.device_id.startswith("dev-a"):
            indicators.append(f"{institution_type}:device_cluster_overlap")
        if "unusual_hour" in transaction.risk_flags:
            indicators.append(f"{institution_type}:behavioral_time_anomaly")
        return indicators

    def _privatize_update(
        self,
        transaction: Transaction,
        update: list[float],
        node_id: str,
    ) -> list[float]:
        seed_material = f"{transaction.transaction_id}:{node_id}:dp-demo".encode()
        seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        rng = random.Random(seed)
        return privatize(update, self.max_norm, self.noise_multiplier, rng=rng)

    def _risk_score_from_vector(self, vector: list[float]) -> int:
        weights = [1.25, 1.10, 0.95, 1.40, 0.75]
        logit = -1.35 + sum(value * weight for value, weight in zip(vector, weights))
        probability = 1.0 / (1.0 + math.exp(-logit))
        return max(0, min(100, round(probability * 100)))

    def _campaign_signature(
        self,
        transaction: Transaction,
        aggregate_mean: list[float],
        indicators: list[str],
    ) -> str:
        signature_material = {
            "country": transaction.country,
            "channel": transaction.channel,
            "top_indicators": indicators[:6],
            "aggregate_bucket": [round(value, 2) for value in aggregate_mean],
        }
        digest = hashlib.sha256(json.dumps(signature_material, sort_keys=True).encode()).hexdigest()
        return f"vfsi-{digest[:12]}"

    def _provenance_hash(
        self,
        transaction_id: str,
        aggregate_mean: list[float],
        dp_summary: dict,
        secure_metadata: dict,
    ) -> str:
        payload = {
            "transaction_id": transaction_id,
            "aggregate_mean": [round(value, 6) for value in aggregate_mean],
            "dp": dp_summary,
            "secure_aggregation": secure_metadata,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

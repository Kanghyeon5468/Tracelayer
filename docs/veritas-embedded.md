# Embedded Veritas Integration

TraceLayer does not depend on a running Veritas API for the demo path. Instead, it embeds the minimum Veritas-inspired primitives needed for federated fraud intelligence.

## What Was Moved In

| TraceLayer Module | Source Concept from Veritas |
| --- | --- |
| `app/federation/secure_agg.py` | HMAC-SHA256 PRG, pairwise masks, secure sum. |
| `app/federation/dp.py` | L2 clipping, Gaussian noise, RDP accountant. |
| `app/federation/engine.py` | Local federation simulation that turns institutional updates into a risk signal. |

## Why This Shape

Calling a separate Veritas service would make TraceLayer look like a workflow wrapper. Embedding the primitives makes the agent fleet technically deeper: the Triage Agent consumes privacy-preserving federated intelligence as a first-class local capability.

## Demo Privacy Story

1. Bank, insurer, and fintech nodes compute local fraud update vectors.
2. Each update is clipped and noised.
3. Pairwise masks hide individual updates from the coordinator.
4. Masks cancel on the aggregate.
5. TraceLayer stores only the aggregate signal, DP summary, campaign signature, and provenance hash.

## Production Upgrade Path

- Replace simulated node updates with real bank-node workers.
- Replace deterministic demo seed dealer with authenticated Diffie-Hellman key exchange.
- Persist federation rounds and model cards in Firestore or Cloud SQL.
- Export DP accounting and secure aggregation events to BigQuery audit tables.
- Use Cloud KMS for signing federation round manifests.

# Threat Model

## Assets

- Customer PII
- Transaction history
- Device and IP intelligence
- Fraud investigation notes
- Approval decisions
- Agent reasoning traces
- Audit logs

## Primary Threats

| Threat | Risk | Control |
| --- | --- | --- |
| Prompt injection | Malicious text attempts to override investigation policy. | Model input scanning and blocking guardrail findings. |
| Tool poisoning | Retrieved records contain instructions that manipulate agents. | Agent Gateway restricts tool scope and blocks suspicious instructions. |
| Excessive agent privilege | One agent can access data or tools it should not use. | Agent identity registry and permission checks. |
| PII leakage | Reports expose raw customer identifiers. | Redaction utilities and compliance findings. |
| Unauthorized approval | Analyst approves a high-risk action without authority. | Role-based approval scope checks. |
| Audit tampering | Logs are modified after an investigation. | Hash-chained append-only ledger. |
| Unsafe automation | The fleet freezes assets without a human. | Case Manager only creates approval requests. |

## Trust Boundaries

1. Analyst browser to API.
2. API to Agent Gateway.
3. Agent Gateway to model provider.
4. Agent Gateway to data stores.
5. Agent Runtime to Pub/Sub.
6. Case Manager to approval workflow.

## Production Hardening Plan

- Replace local API keys with Identity-Aware Proxy or workload identity federation.
- Use per-agent service accounts in Cloud Run jobs or GKE workloads.
- Enforce VPC Service Controls around BigQuery, Firestore, and Cloud Storage.
- Route Gemini calls through Vertex AI with Model Armor policies.
- Export audit events to Cloud Logging and BigQuery.
- Add retention locks for final investigation reports.

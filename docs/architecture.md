# TraceLayer Architecture

TraceLayer is organized as an enterprise agent fleet. Each agent has a narrow responsibility, a declared identity, a scoped set of data permissions, and a structured output contract. The fleet is coordinated by the Case Manager and can later be moved from local orchestration to Pub/Sub-backed asynchronous execution.

## System Goals

1. Reduce fraud investigation time by automating cross-system evidence gathering.
2. Keep high-risk actions under human approval.
3. Preserve auditability for compliance and regulator review.
4. Demonstrate enterprise-grade agent controls required by the Fortified Enterprise Fleet track.

## Request Flow

1. A suspicious transaction enters the Case API.
2. The Agent Gateway validates the request, creates an investigation context, and attaches agent identity metadata.
3. The Triage Agent scores the transaction and assigns priority.
4. The embedded Veritas federation produces a privacy-preserving cross-institution risk signal.
5. The Network Agent searches related transactions by shared account, device, IP address, email, and counterparty.
6. The Evidence Agent builds a chronological evidence timeline and references internal policy and federated provenance.
7. The Compliance Agent checks whether the case contains unsafe PII exposure, policy conflicts, or unauthorized automation.
8. The Case Manager Agent produces the final case state, report metadata, and approval request.

## Enterprise Fleet Concepts

| Concept | TraceLayer Implementation |
| --- | --- |
| Agent Registry | `AgentRegistry` declares names, versions, identities, and permissions. |
| Agent Runtime | `FraudInvestigationFleet` coordinates the current local runtime; Pub/Sub stubs show the deployed path. |
| Agent Gateway | `AgentGateway` checks least privilege, executes guardrails, and writes audit events for each agent. |
| Memory Bank | `MemoryBank` writes append-only case snapshots for cross-session continuity. |
| Agent Identity | Each agent receives a service identity and permission scope. |
| Model Armor | `ModelArmorGuardrail` protects prompts, redacts PII-like values, and blocks prompt injection. |
| Observability | `AuditLedger` writes hash-chained events that can map to Cloud Logging and OpenTelemetry traces. |
| Federated Intelligence | `VeritasFederatedRiskEngine` embeds selected Veritas secure aggregation and DP accounting primitives. |

## Embedded Veritas Federation

TraceLayer uses Veritas as code, not as an external API. The embedded federation lives under `services/api/app/federation`.

The Triage Agent receives a `FederatedRiskSignal` containing:

- Federated risk score.
- Campaign signature.
- Participating institutional nodes.
- Secure aggregation metadata.
- Differential privacy epsilon and delta.
- Provenance hash.

This lets the investigation fleet explain why a transaction is suspicious while preserving the product story that raw bank, insurer, and fintech records stay local.

## Data Plane

Local mode uses JSON fixtures:

- `data/transactions.json`
- `data/customers.json`
- `data/policies.md`

Cloud mode should replace these adapters with:

- Firestore or Cloud SQL for customer and case records.
- BigQuery for historical transaction search.
- Pub/Sub for asynchronous agent jobs.
- Cloud Storage for generated reports.

## Security Posture

TraceLayer never auto-freezes funds in the demo flow. The fleet can recommend a hold, but the Case Manager creates a human approval request for final action. This design is intentional: it makes the demo safer and aligns with regulated financial workflows.

Recommended production controls:

- Use per-agent service accounts.
- Store PII in policy-scoped databases with column-level access.
- Apply Model Armor before and after Gemini calls.
- Log every tool call with case ID, agent ID, input classification, and output classification.
- Use VPC Service Controls for data sovereignty boundaries.

## Local Security Flow

1. The API creates a `RequestContext` from headers.
2. `PolicyEngine` checks the human actor's role scope.
3. `FraudInvestigationFleet` creates the case context and dispatches agent work.
4. `AgentGateway` checks each agent's required permissions against its registered identity.
5. `ModelArmorGuardrail` inspects model prompts and sanitizes agent summaries.
6. `AuditLedger` records authorization, execution, persistence, and approval events.
7. `MemoryBank` stores case snapshots so the case can be reviewed or approved later.

# Build Status and Roadmap

TraceLayer has moved beyond the initial prototype. The current repository contains a runnable Cloud Run-oriented demo with dynamic agent planning, backend-only Gemini calls, Google ADK Runner-backed tool execution, Firestore persistence, Pub/Sub push workers, supervisor approval, 3D network visualization, campaign detection, guardrails, and structured Cloud Logging traces.

## Implemented Demo Depth

| Area | Current Status |
| --- | --- |
| Secure runtime | Agent Gateway, policy engine, API-key enforcement, role-scoped request context, guardrails, memory bank, and audit ledger are implemented. |
| Dynamic orchestration | Case Manager creates an initial triage-first plan, replans after Triage, and can replan again after Network detects a campaign cluster. |
| Google Cloud deployment | Cloud Run deployment assets, Cloud Build config, Pub/Sub push setup, Firestore state, BigQuery search boundary, and Vertex AI mode are present. |
| Google ADK | Triage, Network, and Case Manager run approved tools through real Google ADK `Runner` sessions when `google-adk` is installed. |
| Federated intelligence | Veritas-inspired secure aggregation, differential privacy accounting, campaign signature, and provenance hash are embedded in-process. |
| Investigation UX | Dashboard shows the generated plan, ADK Runner session metadata, agent findings, privacy-separated federated signal, 3D network graph, campaign detection, compliance findings, live approval state, async job status, and Agent Registry. |
| Admin UX | Supervisor page lists pending approvals and approval history, supports accept, deny, request more evidence, and saves risk thresholds. |
| Human feedback | Requesting more evidence reruns Evidence, Compliance, and Case Manager, then creates a new approval request. |
| Security demo | Prompt injection scenario `tx-9701` is blocked by the guardrail while the investigation continues from structured fields. |
| Observability | Agent runs emit hash-chained audit events and structured Cloud Logging trace fields. |

## Remaining Production Hardening

| Priority | Work Item | Reason |
| --- | --- | --- |
| High | Move demo API key material into Secret Manager and rotate it before public demos. | Avoid long-lived secrets in environment variables. |
| High | Add Pub/Sub dead-letter topics and retry policy tuning. | Make async worker failures reviewable and recoverable. |
| High | Add Firestore security rules and IAM validation for the deployed collections. | Tighten access control around case, job, approval, and policy state. |
| Medium | Export audit events to BigQuery with retention policy. | Improve compliance analytics and tamper-evident review at scale. |
| Medium | Add load and failure-mode tests for async investigations. | Demonstrate reliability under parallel demo traffic. |
| Medium | Add a downloadable PDF report renderer. | Improve final case handoff for executive or compliance review. |
| Low | Add richer campaign fixtures and BigQuery seed data. | Make the network graph and campaign detection demo more varied. |

## Demo Evidence to Capture

1. Cloud Run service revision and runtime config.
2. Vertex AI Gemini mode from `/runtime/config`.
3. Firestore case and job documents after a sync and async investigation.
4. Pub/Sub topic and push subscription for `/pubsub/investigations`.
5. Dashboard showing dynamic plan, 3D graph, campaign detection, federated privacy panel, and Model Armor findings.
6. Admin console showing pending approval, request-more-evidence rerun, final decision, and approval history.
7. Cloud Logging query filtered by `case_id` and `agent_id`.

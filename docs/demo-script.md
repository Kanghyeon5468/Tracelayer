# Demo Script

Target length: four minutes.

## 0:00 - Problem

Fraud investigators in banks, insurers, and fintech companies lose time moving between transaction systems, customer records, device intelligence, policy manuals, and approval workflows.

## 0:30 - Product

TraceLayer turns one suspicious transaction into an auditable investigation case. The Case Manager Agent creates a case-specific investigation plan, then runs only the agents needed for that risk level.

## 1:00 - Dynamic Agent Demo

1. Open the dashboard.
2. Click `Run Demo Case`.
3. Show `Agent-generated Investigation Plan`.
4. Explain that low-risk, medium-risk, high-risk, and missing-data cases follow different plans.
5. For a high-risk or critical case, show Triage, Federated Intelligence, Network, Evidence, Compliance, and Human Approval.
6. If campaign detection triggers, show the plan changing to `campaign_escalation_replan` and adding `trace_cluster_funds`.

## 1:45 - Investigation Depth

1. Show the privacy-separated `Federated Intelligence` panel.
2. Point out that contributing organizations are counted, but external customer records exposed remains zero.
3. Show `Local Investigation Evidence` separately.
4. Rotate, zoom, and inspect the live 3D network graph generated from the Network Agent output.
5. Show `Fraud Campaign Detection` and shared infrastructure links.
6. Open Agent Findings and point out `Google ADK Runner` session/tool metadata on Triage, Network, and Case Manager outputs.

## 2:30 - Human Feedback Loop

1. Open the admin console.
2. Show pending approvals and approval history.
3. Click `Request More Evidence` on a pending case.
4. Return to the dashboard and show that Evidence, Compliance, and Case Manager reran.
5. Approve or deny the new request and show the live status update.

## 3:05 - Security Demo

1. Click `Run Attack Demo` on the dashboard.
2. Show the malicious external memo scenario.
3. Show Model Armor findings: prompt injection detected, external instruction blocked, PII access denied.
4. Explain that the investigation continues using structured transaction fields instead of unsafe memo text.

## 3:35 - Architecture

Show the architecture diagram and explain:

- Cloud Run hosts the Case API.
- Google ADK Runner sessions wrap approved Triage, Network, and Case Manager tool execution.
- The Case Manager Planner chooses the investigation path and can replan after Network findings.
- Pub/Sub push runs asynchronous investigations on Cloud Run.
- Firestore stores cases, approvals, risk thresholds, and job state.
- BigQuery searches related transactions when available.
- Gemini explains risk through the backend-only Vertex AI boundary.
- Model Armor, Agent Gateway, and Compliance Agent guard sensitive data.
- Cloud Logging receives structured trace events for each agent run.

## 3:55 - Why It Matters

TraceLayer reduces investigation latency, improves consistency, and keeps final enforcement decisions under human approval.

## Closing

This is a Fortified Enterprise Fleet because it demonstrates agent identity, dynamic planning, persistent memory, model guardrails, policy-aware execution, asynchronous workers, human feedback, audit traces, and production infrastructure boundaries.

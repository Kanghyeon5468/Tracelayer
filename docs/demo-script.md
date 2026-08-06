# Demo Script

Target length: four minutes.

## 0:00 - Problem

Fraud investigators in banks, insurers, and fintech companies lose time moving between transaction systems, customer records, device intelligence, policy manuals, and approval workflows.

## 0:30 - Product

TraceLayer turns one suspicious transaction into an auditable investigation case. It coordinates a fleet of specialized agents instead of asking a human analyst to manually gather every clue.

## 1:00 - Live Demo

1. Open the dashboard.
2. Trigger the demo overseas transfer case.
3. Show the risk score and priority from the Triage Agent.
4. Show related accounts and devices from the Network Agent.
5. Show the evidence timeline.
6. Show compliance checks and PII redaction.
7. Show the final human approval request.

## 2:45 - Architecture

Show the architecture diagram and explain:

- Cloud Run hosts the Case API.
- Pub/Sub distributes long-running investigation work.
- Firestore or Cloud SQL stores case state.
- BigQuery searches related transactions.
- Gemini explains patterns and summarizes evidence.
- Model Armor and the Compliance Agent guard sensitive data.

## 3:30 - Why It Matters

TraceLayer reduces investigation latency, improves consistency, and keeps final enforcement decisions under human approval.

## 3:50 - Closing

This is a Fortified Enterprise Fleet because it demonstrates agent identity, persistent memory, model guardrails, policy-aware execution, audit traces, and production infrastructure boundaries.

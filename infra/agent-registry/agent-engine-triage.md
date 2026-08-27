# Triage Agent Runtime Deployment

TraceLayer can prove real Google-managed Agent Identity by deploying only the Triage Agent to Agent Engine. The full fraud fleet can stay behind the FastAPI AgentGateway.

## Runtime Boundary

```text
Google Agent Runtime / Agent Engine
  -> Triage ADK root_agent
  -> score_trace_layer_transaction tool
  -> TraceLayer Cloud Run /agents/triage-agent/invoke
  -> TraceLayer AgentGateway
  -> BigQuery, Gemini, Model Armor, Firestore, Audit
```

## Why This Matters

- Agent Registry proves discovery and lifecycle.
- Agent Runtime proves Google-managed execution.
- Agent Identity provides a SPIFFE-style workload principal for gateway and egress policy.
- TraceLayer AgentGateway still enforces fraud-specific authorization, data classification, Model Armor, and audit controls.

## Deploy

```bash
cp services/adk/triage_agent/.env.example services/adk/triage_agent/.env

services/api/.venv/bin/adk deploy agent_engine \
  --project=project-6ecbea1e-e0c3-4325-a63 \
  --region=us-central1 \
  --display_name="TraceLayer Triage Agent Runtime" \
  --description="Google ADK Agent Runtime deployment for TraceLayer's Triage Agent." \
  --otel_to_cloud \
  services/adk/triage_agent
```

## Bind The Verified Identity Back To TraceLayer

When deployment finishes, copy the Agent Engine resource and Agent Identity principal into Cloud Run:

```bash
gcloud run services update tracelayer-api \
  --region=us-central1 \
  --project=project-6ecbea1e-e0c3-4325-a63 \
  --update-env-vars TRIAGE_AGENT_ENGINE_RESOURCE=projects/PROJECT/locations/us-central1/reasoningEngines/ENGINE_ID,TRIAGE_AGENT_RUNTIME_PRINCIPAL=principal://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID
```

## Managed Gateway Policy

Grant egress only to the Triage Agent Runtime principal when the managed Agent Gateway endpoint is configured:

```bash
gcloud iap web add-iam-policy-binding GATEWAY_RESOURCE \
  --member='principal://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID' \
  --role=roles/iap.egressor
```

Do not grant that binding to the Compliance Agent principal. Compliance remains limited to policy, PII redaction, and audit review.

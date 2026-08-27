# TraceLayer Triage Agent Runtime

This folder contains the smallest production-shaped Google ADK package for TraceLayer. It lets the Triage Agent run on Google Agent Runtime / Agent Engine while the existing FastAPI service remains the governed fraud policy backend.

## Local Import Check

```bash
cd services/api
PYTHONPATH=../adk ./.venv/bin/python -c "from triage_agent.agent import root_agent; print(root_agent.name)"
```

## Deploy To Agent Engine

Create a local `.env` from `.env.example` and deploy:

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

After deployment, copy the Agent Engine resource and Agent Identity principal into Cloud Run:

```bash
gcloud run services update tracelayer-api \
  --region=us-central1 \
  --project=project-6ecbea1e-e0c3-4325-a63 \
  --update-env-vars TRIAGE_AGENT_ENGINE_RESOURCE=projects/PROJECT/locations/us-central1/reasoningEngines/ENGINE_ID,TRIAGE_AGENT_RUNTIME_PRINCIPAL=principal://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID
```

The dashboard Agent Registry tab will then show `Verified Agent Runtime` for the Triage Agent.

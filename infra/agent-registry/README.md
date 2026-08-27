# Agent Registry And Identity Setup

TraceLayer exposes A2A Agent Cards so selected agents can be registered in Google Cloud Agent Registry without moving every local agent implementation to Agent Runtime at once.

## Register Triage Agent

```bash
PROJECT_ID=project-6ecbea1e-e0c3-4325-a63
REGION=us-central1
SERVICE_URL=https://tracelayer-api-235426782310.us-central1.run.app

gcloud services enable agentregistry.googleapis.com iam.googleapis.com bigquery.googleapis.com \
  --project=$PROJECT_ID

curl -s "$SERVICE_URL/a2a/triage-agent/agent-card.json" > /tmp/tracelayer-triage-agent-card.json

gcloud agent-registry services create tracelayer-triage-agent \
  --project=$PROJECT_ID \
  --location=$REGION \
  --display-name="TraceLayer Triage Agent" \
  --agent-spec-type=a2a-agent-card \
  --agent-spec-content=@/tmp/tracelayer-triage-agent-card.json

gcloud agent-registry agents list \
  --project=$PROJECT_ID \
  --location=$REGION \
  --filter="displayName='TraceLayer Triage Agent'"
```

## IAM Separation

The hackathon demo uses separate IAM principals for agent identities. Triage can read fraud investigation tables; Compliance can read audit and policy evidence but is intentionally not granted BigQuery table read access.

```bash
PROJECT_ID=project-6ecbea1e-e0c3-4325-a63
DATASET=fraud_investigations

gcloud iam service-accounts create tracelayer-triage-agent \
  --project=$PROJECT_ID \
  --display-name="TraceLayer Triage Agent Identity"

gcloud iam service-accounts create tracelayer-compliance-agent \
  --project=$PROJECT_ID \
  --display-name="TraceLayer Compliance Agent Identity"

bq add-iam-policy-binding \
  --member=serviceAccount:tracelayer-triage-agent@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/bigquery.dataViewer \
  --project_id=$PROJECT_ID \
  $DATASET

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:tracelayer-triage-agent@$PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/bigquery.jobUser
```

## Gateway Layering

Google managed Agent Gateway should sit at the network and IAM enforcement layer. TraceLayer AgentGateway remains inside the application as the fraud-specific policy layer:

- Managed Agent Gateway: IAP egress, registry-discovered endpoints, agent identity authorization.
- TraceLayer AgentGateway: transaction policy, data classification, Model Armor findings, immutable audit ledger, Cloud Logging trace metadata.

The dashboard Agent Registry tab shows both layers for each registered agent.

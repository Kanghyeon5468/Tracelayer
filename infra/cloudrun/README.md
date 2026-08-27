# Cloud Run Deployment Notes

The service manifest deploys the FastAPI backend to Cloud Run with backend-only Vertex AI calls and Firestore-backed case memory. For the hackathon demo, show the Cloud Run service, logs, Firestore documents, and environment variables to prove the backend is running on Google Cloud.

## Recommended Flow

1. Build the container image from the repository root.
2. Push the image to Artifact Registry.
3. Deploy `tracelayer-api` with a dedicated service account.
4. Set `SECURITY_MODE=enforcing`.
5. Prefer `AI_PROVIDER=vertex_ai` with the Cloud Run service account.
6. Set `MEMORY_BACKEND=firestore` so human approval decisions survive container restarts.
7. Set `PUBSUB_BACKEND=google` and create a push subscription for `/pubsub/investigations`.
8. Store any API keys in Secret Manager instead of plain environment variables.

## Current Command Shape

```bash
PROJECT_ID=project-6ecbea1e-e0c3-4325-a63
REGION=us-central1
IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/tracelayer/api:latest

gcloud builds submit \
  --config infra/cloudrun/cloudbuild.yaml \
  --substitutions _IMAGE=$IMAGE

gcloud run deploy tracelayer-api \
  --image $IMAGE \
  --region $REGION \
  --service-account tracelayer-agent@$PROJECT_ID.iam.gserviceaccount.com \
  --no-allow-unauthenticated \
  --set-env-vars APP_ENV=cloud,USE_MOCK_DATA=true,AI_PROVIDER=vertex_ai,GEMINI_MODEL=gemini-3.5-flash,ADK_MODEL=gemini-3.5-flash,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=us,AGENT_REGISTRY_LOCATION=us-central1,GOOGLE_API_USE_MTLS_ENDPOINT=never,GOOGLE_API_USE_CLIENT_CERTIFICATE=false,PUBLIC_SERVICE_URL=https://tracelayer-api-235426782310.us-central1.run.app,MODEL_ARMOR_BACKEND=google,MODEL_ARMOR_LOCATION=us-central1,MODEL_ARMOR_TEMPLATE_ID=tracelayer-prompt-shield,SECURITY_MODE=enforcing,DEMO_ANALYST_API_KEY=local-demo-key,MEMORY_BACKEND=firestore,FIRESTORE_DATABASE='(default)',FIRESTORE_CASE_COLLECTION=tracelayer_cases,FIRESTORE_JOB_COLLECTION=tracelayer_investigation_jobs,NETWORK_SEARCH_BACKEND=auto,NETWORK_SEARCH_TIMEOUT_SECONDS=3,BIGQUERY_TRANSACTIONS_TABLE=$PROJECT_ID.fraud_investigations.transactions,PUBSUB_BACKEND=google,PUBSUB_TOPIC_INVESTIGATIONS=tracelayer-investigations,PUBSUB_TOPIC_APPROVALS=tracelayer-approvals,PUBSUB_PUSH_SUBSCRIPTION=tracelayer-investigation-worker
```

## Pub/Sub Push Worker

Create the async work topics and a push identity:

```bash
PROJECT_ID=project-6ecbea1e-e0c3-4325-a63
REGION=us-central1
SERVICE=tracelayer-api
SERVICE_URL=$(gcloud run services describe $SERVICE --region $REGION --format='value(status.url)')
INVOKER=tracelayer-pubsub-invoker@$PROJECT_ID.iam.gserviceaccount.com

gcloud pubsub topics create tracelayer-investigations
gcloud pubsub topics create tracelayer-approvals

gcloud iam service-accounts create tracelayer-pubsub-invoker \
  --display-name="TraceLayer Pub/Sub Push Invoker"

gcloud run services add-iam-policy-binding $SERVICE \
  --region $REGION \
  --member=serviceAccount:$INVOKER \
  --role=roles/run.invoker

gcloud pubsub subscriptions create tracelayer-investigation-worker \
  --topic=tracelayer-investigations \
  --push-endpoint=$SERVICE_URL/pubsub/investigations \
  --push-auth-service-account=$INVOKER \
  --ack-deadline=600
```

After this setup, `POST /cases/demo/async` publishes a job to Pub/Sub and returns immediately. Pub/Sub then calls the Cloud Run worker endpoint, which moves the job through `queued -> running -> succeeded` in Firestore.

Authenticated smoke test:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  https://tracelayer-api-235426782310.us-central1.run.app/runtime/config

curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: local-demo-key" \
  -H "X-Tracelayer-Role: supervisor" \
  https://tracelayer-api-235426782310.us-central1.run.app/cases/demo
```

Prompt injection live demo:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: local-demo-key" \
  -H "X-Tracelayer-Role: supervisor" \
  --data '{"transaction_id":"tx-9701"}' \
  https://tracelayer-api-235426782310.us-central1.run.app/cases/investigate
```

Cloud Logging trace query:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="tracelayer-api" AND jsonPayload.case_id="CASE_ID"' \
  --project $PROJECT_ID \
  --limit 20 \
  --format json
```

Every structured trace entry includes `case_id`, `agent_id`, `agent_version`, `tool`, `latency_ms`, and `status`. HTTP requests also include `logging.googleapis.com/trace` for Cloud Run request-log correlation.

## Production Changes

- Move API keys to Secret Manager.
- Export audit events to Cloud Logging and BigQuery.
- Use dead-letter topics and retry policies for long-running Pub/Sub worker failures.
- Route Gemini calls through Vertex AI with Model Armor policies.

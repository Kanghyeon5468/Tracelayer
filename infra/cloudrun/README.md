# Cloud Run Deployment Notes

The service manifest deploys the FastAPI backend to Cloud Run with backend-only Vertex AI calls and Firestore-backed case memory. For the hackathon demo, show the Cloud Run service, logs, Firestore documents, and environment variables to prove the backend is running on Google Cloud.

## Recommended Flow

1. Build the container image from the repository root.
2. Push the image to Artifact Registry.
3. Deploy `tracelayer-api` with a dedicated service account.
4. Set `SECURITY_MODE=enforcing`.
5. Prefer `AI_PROVIDER=vertex_ai` with the Cloud Run service account.
6. Set `MEMORY_BACKEND=firestore` so human approval decisions survive container restarts.
7. Store any API keys in Secret Manager instead of plain environment variables.

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
  --set-env-vars APP_ENV=cloud,USE_MOCK_DATA=true,AI_PROVIDER=vertex_ai,GEMINI_MODEL=gemini-2.5-flash,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,SECURITY_MODE=enforcing,DEMO_ANALYST_API_KEY=local-demo-key,MEMORY_BACKEND=firestore,FIRESTORE_DATABASE='(default)',FIRESTORE_CASE_COLLECTION=tracelayer_cases
```

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

## Production Changes

- Move API keys to Secret Manager.
- Export audit events to Cloud Logging and BigQuery.
- Use Pub/Sub push or pull workers for long-running agent tasks.
- Route Gemini calls through Vertex AI with Model Armor policies.

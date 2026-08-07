# Cloud Run Deployment Notes

The current service manifest is a deployment stub. For the hackathon demo, show the Cloud Run service, logs, and environment variables to prove the backend is running on Google Cloud.

## Recommended Flow

1. Build the container image from the repository root.
2. Push the image to Artifact Registry.
3. Deploy `tracelayer-api` with a dedicated service account.
4. Set `SECURITY_MODE=enforcing`.
5. Prefer `AI_PROVIDER=vertex_ai` with the Cloud Run service account.
6. Store any API keys in Secret Manager instead of plain environment variables.

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
  --set-env-vars APP_ENV=cloud,AI_PROVIDER=vertex_ai,GEMINI_MODEL=gemini-2.5-flash,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,SECURITY_MODE=enforcing,DEMO_ANALYST_API_KEY=local-demo-key
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

- Replace local file memory with Firestore.
- Export audit events to Cloud Logging and BigQuery.
- Use Pub/Sub push or pull workers for long-running agent tasks.
- Route Gemini calls through Vertex AI with Model Armor policies.

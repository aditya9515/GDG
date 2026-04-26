# Gemini-First Firebase App Hosting Deployment

This project deploys as two services:

- Frontend: Next.js on Firebase App Hosting from `web/`.
- Backend: FastAPI on Cloud Run from `api/Dockerfile`.

The frontend calls the backend through `NEXT_PUBLIC_API_BASE_URL`. Backend-only secrets must never be placed in `NEXT_PUBLIC_*` variables.

## 1. Firebase And Google Cloud Setup

Use the project already configured in `.firebaserc`:

```powershell
npx -y firebase-tools@latest login
npx -y firebase-tools@latest use gdg-ngo-resource-aloocation
```

Confirm the project is on the Blaze plan, then enable:

- Firebase Authentication with Google sign-in.
- Firestore Native mode.
- Firebase Storage.
- Secret Manager.
- Cloud Run, Cloud Build, and Artifact Registry.
- Maps JavaScript API for the browser key.
- Geocoding API and Routes API for the backend key.
- Gemini API for backend extraction and reevaluation.

## 2. Backend Cloud Run Deployment

Production uses Gemini and disables local Gemma4/Ollama:

```env
AI_PROVIDER=gemini
GEMINI_ENABLED=true
GEMMA4_ENABLED=false
```

Create secrets:

```powershell
gcloud secrets create GEMINI_API_KEY --replication-policy=automatic --project gdg-ngo-resource-aloocation
gcloud secrets versions add GEMINI_API_KEY --data-file=- --project gdg-ngo-resource-aloocation

gcloud secrets create GOOGLE_MAPS_API_KEY --replication-policy=automatic --project gdg-ngo-resource-aloocation
gcloud secrets versions add GOOGLE_MAPS_API_KEY --data-file=- --project gdg-ngo-resource-aloocation
```

Deploy the API:

```powershell
gcloud run deploy reliefops-api `
  --project gdg-ngo-resource-aloocation `
  --region asia-south1 `
  --source api `
  --allow-unauthenticated `
  --set-env-vars APP_ENV=production,REPOSITORY_BACKEND=firestore,ALLOW_DEMO_AUTH=false,FIREBASE_PROJECT_ID=gdg-ngo-resource-aloocation,FIREBASE_STORAGE_BUCKET=<bucket>.firebasestorage.app,AI_PROVIDER=gemini,GEMINI_ENABLED=true,GEMMA4_ENABLED=false `
  --set-env-vars CORS_ORIGINS='["http://localhost:3000","http://127.0.0.1:3000","https://<app-hosting-domain>"]' `
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest
```

Copy the deployed Cloud Run URL. You will use it as `NEXT_PUBLIC_API_BASE_URL`.

## 3. Firebase App Hosting Frontend Configuration

In Firebase Console, open App Hosting backend `gdg-app` and set these environment variables, or place equivalent values in the repo-root `apphosting.yaml` before rollout:

```env
NEXT_PUBLIC_API_BASE_URL=https://<cloud-run-api-url>
NEXT_PUBLIC_ENABLE_DEMO_AUTH=false
NEXT_PUBLIC_FIREBASE_API_KEY=<firebase-web-api-key>
NEXT_PUBLIC_FIREBASE_APP_ID=<firebase-web-app-id>
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=gdg-ngo-resource-aloocation.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=gdg-ngo-resource-aloocation
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=<bucket>.firebasestorage.app
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=<browser-maps-js-key>
```

Do not add `GEMINI_API_KEY`, backend `GOOGLE_MAPS_API_KEY`, service account JSON, Geocoding-only keys, or Routes-only keys to App Hosting public env.

Deploy App Hosting:

```powershell
npx -y firebase-tools@latest deploy --only apphosting --project gdg-ngo-resource-aloocation
```

If your App Hosting backend is GitHub-connected, commit these config changes and create a rollout from the Firebase console instead.

## 4. Gemini Parity With Local Gemma4

Gemini and Gemma4 use the same backend contracts:

- `IncidentExtraction`
- `ExtractedDocumentBatch`
- `TeamDraftPayload`
- `ResourceDraftPayload`

That means Gemini handles the same Graph 1 jobs Gemma4 handled locally:

- Unknown CSV row-batch extraction.
- Mixed PDF/text/image/document extraction.
- Incident, team, and resource draft creation.
- Prompt reevaluation.
- Structured JSON output for preview, edit, confirm, tokens, vectors, duplicate checks, and geocoding.

Graph 2 assignment feasibility stays deterministic. Gemini may improve wording and explanations, but it must not decide stock math, availability, ETA truth, or hard assignment constraints.

## 5. Verification

Run locally before deploying:

```powershell
npm run test:api
npm --prefix web run test
npm --prefix web run build
```

After deployment:

1. Open the App Hosting URL.
2. Sign in with Google.
3. Open System Status.
4. Confirm `/health`, `/me`, and `/ai/status` pass.
5. Confirm `/ai/status` shows Gemini enabled/configured and Gemma4/Ollama disabled.
6. Upload CSV/PDF through `/imports`, confirm Graph 1, then run `/dispatch` -> `Plan all open cases`.
